"""Contract selection: nearest weekly expiry, delta closest to target."""
import logging
from datetime import date, timedelta

from alpaca.data.requests import OptionSnapshotRequest
from alpaca.trading.enums import AssetStatus, ContractType
from alpaca.trading.requests import GetOptionContractsRequest

from .pricing import bs_delta
from .signals import Direction

log = logging.getLogger("opscalper.selector")


def pick_contract(trading, options_data, underlying: str, spot: float,
                  direction: Direction, cfg) -> dict | None:
    """Return {'symbol','strike','expiry','delta','bid','ask','mid'} or None."""
    today = date.today()
    req = GetOptionContractsRequest(
        underlying_symbols=[underlying],
        status=AssetStatus.ACTIVE,
        expiration_date_gte=today + timedelta(days=cfg.min_days_to_expiry),
        expiration_date_lte=today + timedelta(days=cfg.max_days_to_expiry),
        type=ContractType.CALL if direction == Direction.CALL else ContractType.PUT,
        limit=500,
    )
    contracts = list(trading.get_option_contracts(req).option_contracts)
    if not contracts:
        log.warning("%s: no contracts found", underlying)
        return None

    # nearest expiry only (the weekly)
    nearest = min(c.expiration_date for c in contracts)
    weekly = [c for c in contracts if c.expiration_date == nearest and c.tradable]

    # rough pre-filter: within 8% of spot to limit snapshot calls
    near = [c for c in weekly if abs(float(c.strike_price) - spot) / spot < 0.08]
    if not near:
        return None

    syms = [c.symbol for c in near]
    snaps = options_data.get_option_snapshot(OptionSnapshotRequest(symbol_or_symbols=syms))

    is_call = direction == Direction.CALL
    target = cfg.target_delta if is_call else -cfg.target_delta
    best = None
    for c in near:
        snap = snaps.get(c.symbol)
        if not snap or not snap.latest_quote:
            continue
        bid = float(snap.latest_quote.bid_price or 0)
        ask = float(snap.latest_quote.ask_price or 0)
        if bid <= 0 or ask <= 0 or ask < bid:
            continue
        mid = (bid + ask) / 2
        spread_pct = (ask - bid) / mid * 100 if mid else 999
        if spread_pct > cfg.max_spread_pct:
            continue
        delta = bs_delta(spot, float(c.strike_price), c.expiration_date, cfg.default_iv, is_call)
        if abs(abs(delta) - cfg.target_delta) > cfg.delta_tolerance:
            continue
        score = abs(delta - target)
        if best is None or score < best["score"]:
            best = {"symbol": c.symbol, "strike": float(c.strike_price),
                    "expiry": c.expiration_date, "delta": delta,
                    "bid": bid, "ask": ask, "mid": mid, "score": score}
    if best is None:
        log.info("%s %s: no contract near delta %.2f with tight spread",
                 underlying, direction.value, target)
    return best
