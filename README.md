# Intraday Options Scalping Bot (Alpaca)

Scalps **weekly options (~0.40 delta)** on AAPL/TSLA/META using two intraday
signal engines, with premium-based exits and Discord alerts. Paper trading
by default.

## How it works

**Signals (on the underlying's 1-min bars):**
1. **VWAP momentum** — price crosses session VWAP with a ≥2× volume spike and
   5-bar momentum → buy calls (or puts on the mirror image)
2. **Opening range breakout** — first 15 minutes define a range; a close
   beyond it on elevated volume → directional entry (ORB entries stop at 11:00)

**Contract selection:**
- Nearest weekly expiry (1–10 DTE), calls or puts matching the signal
- Targets **delta ≈ 0.40** via Black-Scholes (Alpaca's free plan has no greeks,
  so delta is computed with a configurable `DEFAULT_IV`)
- Skips contracts with bid/ask spreads wider than `MAX_SPREAD_PCT` (8%)

**Exits (managed manually — Alpaca has no bracket orders for options):**
- **+30%** on premium (take profit) / **−15%** (stop loss), polled every 15s
- 20-minute max hold — scalps don't linger
- Hard flat by 15:30 ET; no new entries after 14:45

**Risk:**
- $500 premium per trade, max 2 concurrent positions
- $200 daily-loss circuit breaker, 15 trades/day cap
- One open trade per underlying at a time

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in your Alpaca keys (+ optional Discord webhook)
python main.py
```

Requires an Alpaca account with options trading approved (any level ≥ 1 for
long calls/puts). Paper accounts work out of the box.

## Deploy

Same as the stock scalper: Railway / Kimi Claw → deploy from repo, set
`ALPACA_API_KEY`, `ALPACA_API_SECRET` (and `DISCORD_WEBHOOK_URL`), start
command `python main.py`. It sleeps outside market hours.

**Running alongside the stock scalper?** They share the paper account — the
bots track only their own positions, but daily-loss limits are per-bot. Split
Discord webhooks into separate channels to tell their alerts apart.

## Disclaimer

Options scalping is extremely high risk: contracts can go to zero, spreads
widen fast, and backtests don't capture slippage. Paper trade extensively
before even thinking about real funds.
