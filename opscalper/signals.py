"""Underlying signal engines: VWAP momentum + opening range breakout.

Pure functions over 1-min bar lists (bars need .open/.high/.low/.close/.volume/.timestamp).
"""
from dataclasses import dataclass
from datetime import time as dtime
from enum import Enum
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


class Direction(str, Enum):
    CALL = "call"
    PUT = "put"


@dataclass
class Signal:
    direction: Direction
    source: str          # "vwap" or "orb"
    reason: str


def _vwap(bars) -> float:
    pv = sum(((b.high + b.low + b.close) / 3) * b.volume for b in bars)
    vol = sum(b.volume for b in bars)
    return pv / vol if vol else 0.0


def _avg_vol(bars) -> float:
    vols = [b.volume for b in bars]
    return sum(vols) / len(vols) if vols else 0.0


def vwap_signal(bars, cfg) -> Signal | None:
    """VWAP cross + volume spike + momentum (same engine as the stock scalper)."""
    if len(bars) < cfg.momentum_lookback + 5:
        return None
    vwap = _vwap(bars)
    if vwap == 0:
        return None
    last, prev = bars[-1], bars[-2]
    dist_pct = (last.close - vwap) / vwap * 100
    mom = last.close - bars[-1 - cfg.momentum_lookback].close
    baseline = _avg_vol(bars[:-1][-20:])
    if baseline <= 0 or last.volume < baseline * cfg.volume_spike_mult:
        return None
    crossed_up = prev.close <= vwap and last.close > vwap
    crossed_down = prev.close >= vwap and last.close < vwap
    if (crossed_up or dist_pct > cfg.vwap_min_distance_pct) and mom > 0 and last.close > vwap:
        return Signal(Direction.CALL, "vwap", f"VWAP cross up, vol x{last.volume/baseline:.1f}")
    if (crossed_down or dist_pct < -cfg.vwap_min_distance_pct) and mom < 0 and last.close < vwap:
        return Signal(Direction.PUT, "vwap", f"VWAP cross down, vol x{last.volume/baseline:.1f}")
    return None


def orb_signal(bars, cfg) -> Signal | None:
    """Opening range breakout: first ORB_MINUTES defines the range; a close
    beyond it on elevated volume triggers a directional entry. ORB entries
    stop after cfg.orb_cutoff ET."""
    if not bars:
        return None
    first_ts = bars[0].timestamp.astimezone(ET)
    open_t = dtime(9, 30)
    orb_end_min = 30 + cfg.orb_minutes
    orb_end = dtime(orb_end_min // 60, orb_end_min % 60)
    h, m = map(int, cfg.orb_cutoff.split(":"))
    cutoff = dtime(h, m)

    last = bars[-1]
    t = last.timestamp.astimezone(ET).time()
    if t < orb_end or t > cutoff:
        return None

    opening = [b for b in bars if b.timestamp.astimezone(ET).time() < orb_end]
    if len(opening) < cfg.orb_minutes // 2:
        return None
    hi = max(b.high for b in opening)
    lo = min(b.low for b in opening)

    post = [b for b in bars if b.timestamp.astimezone(ET).time() >= orb_end]
    if len(post) < 2:
        return None
    prev = post[-2] if len(post) >= 2 else None
    baseline = _avg_vol(bars[:-1][-20:])
    vol_ok = baseline > 0 and last.volume >= baseline * (cfg.volume_spike_mult * 0.75)

    if not vol_ok:
        return None
    if prev and prev.close <= hi and last.close > hi:
        return Signal(Direction.CALL, "orb", f"ORB break above {hi:.2f}, vol x{last.volume/baseline:.1f}")
    if prev and prev.close >= lo and last.close < lo:
        return Signal(Direction.PUT, "orb", f"ORB break below {lo:.2f}, vol x{last.volume/baseline:.1f}")
    return None


def generate_signals(bars, cfg) -> list[Signal]:
    out = []
    s = vwap_signal(bars, cfg)
    if s:
        out.append(s)
    s = orb_signal(bars, cfg)
    if s:
        out.append(s)
    return out
