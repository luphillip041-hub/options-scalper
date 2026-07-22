"""Black-Scholes delta — free plan has no greeks, so we compute our own."""
import math
from datetime import date


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_delta(spot: float, strike: float, expiry: date, iv: float, call: bool,
             r: float = 0.05) -> float:
    """Approximate BS delta. Good enough for picking a ~0.40-delta weekly."""
    dte = max((expiry - date.today()).days, 1) / 365.0
    if spot <= 0 or strike <= 0 or iv <= 0:
        return 0.5 if call else -0.5
    d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * dte) / (iv * math.sqrt(dte))
    return _norm_cdf(d1) if call else _norm_cdf(d1) - 1
