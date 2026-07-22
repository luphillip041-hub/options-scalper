"""Intraday options scalping bot (Alpaca paper).

Loop: pull underlying 1-min bars -> VWAP/ORB signals -> pick weekly
~0.40-delta contract -> buy with $premium -> manage exits by polling the
option's mid price (Alpaca has no bracket orders for options).

Exits: +TP% / -SL% on premium, max-hold timer, hard flat before the close.
"""
import logging
import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from alpaca.data.enums import DataFeed
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import OptionSnapshotRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

from .config import Config
from .notify import send
from .selector import pick_contract
from .signals import Direction, generate_signals

log = logging.getLogger("opscalper")
ET = ZoneInfo("America/New_York")


@dataclass
class OpenOptionTrade:
    contract: str
    underlying: str
    direction: Direction
    qty: int
    entry_premium: float   # per share
    entry_time: datetime
    source: str


class RiskState:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.day = None
        self.pnl = 0.0
        self.trades = 0
        self.halted = False

    def roll(self, today):
        if self.day != today:
            self.day, self.pnl, self.trades, self.halted = today, 0.0, 0, False

    def can_trade(self, open_n: int, today):
        self.roll(today)
        if self.halted:
            return False, f"daily loss ${self.pnl:+.2f}"
        if self.trades >= self.cfg.max_trades_per_day:
            return False, "max trades/day"
        if open_n >= self.cfg.max_positions:
            return False, "max positions"
        return True, "ok"

    def record(self, pnl, today):
        self.roll(today)
        self.pnl += pnl
        if self.pnl <= -abs(self.cfg.max_daily_loss_usd):
            self.halted = True


class OptionsScalper:
    def __init__(self, cfg: Config):
        cfg.validate()
        self.cfg = cfg
        self.trading = TradingClient(cfg.api_key, cfg.api_secret, paper=cfg.paper)
        self.stock_data = StockHistoricalDataClient(cfg.api_key, cfg.api_secret)
        self.opt_data = OptionHistoricalDataClient(cfg.api_key, cfg.api_secret)
        self.risk = RiskState(cfg)
        self.open: dict[str, OpenOptionTrade] = {}   # contract symbol -> trade
        self._was_in_session = False

    # ---------- market data ----------
    def _bars(self, symbol: str):
        now = datetime.now(ET)
        start = now.replace(hour=9, minute=30, second=0, microsecond=0)
        req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Minute,
                               start=start, end=now, feed=DataFeed.IEX)
        return list(self.stock_data.get_stock_bars(req).data.get(symbol, []))

    def _mid(self, contract: str) -> float | None:
        try:
            snap = self.opt_data.get_option_snapshot(OptionSnapshotRequest(symbol_or_symbols=contract))
            s = snap.get(contract)
            if s and s.latest_quote and s.latest_quote.bid_price and s.latest_quote.ask_price:
                return (float(s.latest_quote.bid_price) + float(s.latest_quote.ask_price)) / 2
        except Exception as e:
            log.warning("quote %s: %s", contract, e)
        return None

    # ---------- session ----------
    def _t(self) -> tuple:
        now = datetime.now(ET)
        return now, now.strftime("%H:%M"), now.weekday() < 5

    def _in_session(self) -> bool:
        _, t, wd = self._t()
        return wd and self.cfg.trade_start <= t <= self.cfg.flat_by

    # ---------- trading ----------
    def _enter(self, underlying: str, sig):
        bars = self._bars(underlying)
        if not bars:
            return
        spot = bars[-1].close
        c = pick_contract(self.trading, self.opt_data, underlying, spot, sig.direction, self.cfg)
        if not c:
            return
        qty = max(1, math.floor(self.cfg.premium_per_trade / (c["ask"] * 100)))
        order = MarketOrderRequest(symbol=c["symbol"], qty=qty,
                                   side=OrderSide.BUY, time_in_force=TimeInForce.DAY)
        self.trading.submit_order(order)
        self.open[c["symbol"]] = OpenOptionTrade(
            contract=c["symbol"], underlying=underlying, direction=sig.direction,
            qty=qty, entry_premium=c["ask"], entry_time=datetime.now(ET), source=sig.source)
        self.risk.trades += 1
        log.info("ENTER %s x%d %s @ ask %.2f (%s)", c["symbol"], qty, sig.direction.value, c["ask"], sig.reason)
        send(f"{'📈' if sig.direction == Direction.CALL else '📉'} Bought {sig.direction.value.upper()} {underlying}",
             sig.reason, sig.direction.value,
             {"Contract": c["symbol"], "Qty": qty, "Premium": f"${c['ask']:.2f}",
              "Delta": f"{c['delta']:.2f}", "Expiry": c["expiry"], "Spot": f"${spot:.2f}"})

    def _exit(self, contract: str, why: str):
        t = self.open.get(contract)
        if not t:
            return
        try:
            self.trading.close_position(contract)
        except Exception as e:
            log.error("close %s: %s", contract, e)
            return
        mid = self._mid(contract) or t.entry_premium
        pnl = (mid - t.entry_premium) * 100 * t.qty
        self.open.pop(contract, None)
        self.risk.record(pnl, datetime.now(ET).date())
        log.info("EXIT %s %s pnl≈$%.2f (daily $%.2f)", contract, why, pnl, self.risk.pnl)
        send(f"{'✅' if pnl > 0 else '❌'} Sold {t.underlying} {t.direction.value.upper()}  ${pnl:+.2f}",
             why, "win" if pnl > 0 else "loss",
             {"Contract": contract, "Entry": f"${t.entry_premium:.2f}",
              "Exit ~": f"${mid:.2f}", "Daily P&L": f"${self.risk.pnl:+.2f}"})
        if self.risk.halted:
            send("🛑 Daily loss limit hit — options bot halted for today",
                 f"Realized P&L: ${self.risk.pnl:+.2f}", "halt")

    def _manage_open(self):
        now = datetime.now(ET)
        for contract, t in list(self.open.items()):
            mid = self._mid(contract)
            if mid is None:
                continue
            chg = (mid - t.entry_premium) / t.entry_premium * 100
            held = (now - t.entry_time).total_seconds() / 60
            _, tt, _ = self._t()
            if chg >= self.cfg.take_profit_pct:
                self._exit(contract, f"Take profit +{chg:.1f}%")
            elif chg <= -self.cfg.stop_loss_pct:
                self._exit(contract, f"Stop loss {chg:.1f}%")
            elif held >= self.cfg.max_hold_minutes:
                self._exit(contract, f"Time exit after {held:.0f}m ({chg:+.1f}%)")
            elif tt >= self.cfg.flat_by:
                self._exit(contract, "Flatten before close")

    # ---------- main loop ----------
    def run(self):
        acct = self.trading.get_account()
        log.info("Options scalper online. Equity $%s | options BP $%s",
                 acct.equity, acct.options_buying_power)
        send("🤖 Options scalper online",
             f"Symbols: {', '.join(self.cfg.symbols)} | weekly Δ{self.cfg.target_delta} | ${self.cfg.premium_per_trade:.0f}/trade",
             "info", {"Equity": f"${float(acct.equity):,.2f}",
                      "TP/SL": f"+{self.cfg.take_profit_pct}% / −{self.cfg.stop_loss_pct}%"})
        while True:
            try:
                _, t, wd = self._t()
                if not self._in_session():
                    if self._was_in_session:
                        send("📋 Options daily recap",
                             f"Session over. Realized P&L: ${self.risk.pnl:+.2f}",
                             "win" if self.risk.pnl > 0 else "loss",
                             {"Trades": self.risk.trades, "Halted": self.risk.halted})
                        self._was_in_session = False
                    log.info("Outside session. Sleeping 60s.")
                    time.sleep(60)
                    continue
                self._was_in_session = True

                self._manage_open()

                today = datetime.now(ET).date()
                if t <= self.cfg.no_new_entries_after:
                    ok, why = self.risk.can_trade(len(self.open), today)
                    if not ok:
                        log.info("no new entries: %s", why)
                    else:
                        for sym in self.cfg.symbols:
                            if any(t2.underlying == sym for t2 in self.open.values()):
                                continue
                            try:
                                bars = self._bars(sym)
                                if len(bars) < 20:
                                    continue
                                sigs = generate_signals(bars, self.cfg)
                                if sigs:
                                    self._enter(sym, sigs[0])
                            except Exception as e:
                                log.error("%s: %s", sym, e)
                time.sleep(self.cfg.poll_seconds)
            except KeyboardInterrupt:
                break
            except Exception as e:
                log.exception("loop error: %s", e)
                time.sleep(self.cfg.poll_seconds)
