"""Configuration loaded from environment variables. See .env.example."""
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    api_key: str = os.getenv("ALPACA_API_KEY", "")
    api_secret: str = os.getenv("ALPACA_API_SECRET", "")
    paper: bool = os.getenv("ALPACA_PAPER", "true").lower() == "true"

    # Underlyings (from stock scalper backtest: these carry the edge)
    symbols: list = field(
        default_factory=lambda: os.getenv("SYMBOLS", "AAPL,TSLA,META").split(",")
    )

    # Contract selection
    target_delta: float = float(os.getenv("TARGET_DELTA", "0.40"))
    delta_tolerance: float = float(os.getenv("DELTA_TOLERANCE", "0.15"))
    default_iv: float = float(os.getenv("DEFAULT_IV", "0.30"))  # BS fallback (no greeks on free plan)
    min_days_to_expiry: int = int(os.getenv("MIN_DTE", "1"))    # weekly, not 0DTE
    max_days_to_expiry: int = int(os.getenv("MAX_DTE", "10"))
    max_spread_pct: float = float(os.getenv("MAX_SPREAD_PCT", "8"))  # skip illiquid contracts

    # Trade sizing / exits (premium-based)
    premium_per_trade: float = float(os.getenv("PREMIUM_PER_TRADE", "500"))
    take_profit_pct: float = float(os.getenv("TAKE_PROFIT_PCT", "30"))   # +30% on premium
    stop_loss_pct: float = float(os.getenv("STOP_LOSS_PCT", "15"))       # -15% on premium
    max_hold_minutes: int = int(os.getenv("MAX_HOLD_MINUTES", "20"))

    # Risk
    max_positions: int = int(os.getenv("MAX_POSITIONS", "2"))
    max_daily_loss_usd: float = float(os.getenv("MAX_DAILY_LOSS_USD", "200"))
    max_trades_per_day: int = int(os.getenv("MAX_TRADES_PER_DAY", "15"))

    # Strategy params (underlying 1-min bars)
    vwap_min_distance_pct: float = float(os.getenv("VWAP_MIN_DISTANCE_PCT", "0.05"))
    volume_spike_mult: float = float(os.getenv("VOLUME_SPIKE_MULT", "2.0"))
    momentum_lookback: int = int(os.getenv("MOMENTUM_LOOKBACK", "5"))
    orb_minutes: int = int(os.getenv("ORB_MINUTES", "15"))       # opening range length
    orb_cutoff: str = os.getenv("ORB_CUTOFF", "11:00")           # no ORB entries after this

    # Session (ET)
    trade_start: str = os.getenv("TRADE_START", "09:35")
    no_new_entries_after: str = os.getenv("NO_NEW_ENTRIES_AFTER", "14:45")
    flat_by: str = os.getenv("FLAT_BY", "15:30")
    poll_seconds: int = int(os.getenv("POLL_SECONDS", "15"))

    def validate(self):
        if not self.api_key or not self.api_secret:
            raise ValueError("Set ALPACA_API_KEY and ALPACA_API_SECRET in .env")
