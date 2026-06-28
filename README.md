# Crypto Paper-Trading Bot

A free, self-contained **paper-trading** (simulated, no real money) bot for Binance
spot markets. Every 15 minutes it scans **every tradeable coin** (~440, deduped by
base asset, non-USDT pairs converted to USDT), applies a technical signal, and opens
**virtual** positions. Each position gets a **stop-loss and take-profit**; when price
hits either, the position closes and the freed capital **rolls into the next coin**
(whatever is left after a loss/gain funds the next trades). State lives in
`ledger.json`, which GitHub Actions commits back to the repo after each run — so the
git history *is* your trade log. No API key required (all market data is public).

**Trade log:** every BUY (symbol, entry, SL, TP) and SELL (reason, PnL, cash left)
is recorded in `ledger.json` and mirrored to Notion (one row per event).

> ⚠️ Paper trading only. No real orders are ever placed. Backtest numbers are
> historical and **not** a promise of future profit.

## Components

| File | What it does |
|------|--------------|
| `signals.py` | 8 indicators (SMA, EMA, RSI, MACD, Bollinger, ATR, Stochastic, Donchian) + 6 signal factories. Pure stdlib. |
| `backtest.py` | No-lookahead backtest engine (win rate / return / max drawdown / fees). |
| `test_all.py` | 57 deterministic unit tests defining correctness of the above. |
| `data.py` | Public Binance REST: klines + liquid-symbol discovery (stdlib `urllib`). Uses `data-api.binance.vision` so it works from US-based CI runners (`api.binance.com` returns HTTP 451 there). Override with `BINANCE_BASE`. |
| `run_backtest.py` | Runs every signal over historical data and ranks them. **Use this to decide which signal to run live.** |
| `scanner.py` | The 15-minute cron entry point: scan → paper trade → update `ledger.json`. |
| `notion_sync.py` | Optional best-effort push of a summary row to a Notion database. |
| `.github/workflows/scan.yml` | Schedules the scanner every 15 min and commits the ledger. |

The signals + engine were generated and cross-verified by a multi-agent harness
(GPT-5.5 adversarial review); all 57 tests pass.

## Quick start

```bash
# 1. Run the test suite
python3 -m unittest test_all

# 2. See which signals performed best on recent data
python3 run_backtest.py 25 15m 1000

# 3. Run one paper-trade scan locally (creates/updates ledger.json)
python3 scanner.py
```

## Going live (free, 24/7, no server)

This runs entirely on **GitHub Actions** (free, unlimited minutes on a public repo):

1. Push this repo to GitHub (public).
2. Actions tab → enable workflows. The `scan.yml` cron fires every 15 min.
3. (Optional) Add `NOTION_TOKEN` + `NOTION_DATABASE_ID` repo secrets to mirror
   summaries into a Notion dashboard — see the header of `notion_sync.py`.

⚠️ **Never commit secrets.** The Notion token goes in GitHub Actions **Secrets**,
not in the code. The trade ledger is fine to be public (it's fake money).

## Configuration (env vars, read by `scanner.py`)

| Var | Default | Meaning |
|-----|---------|---------|
| `STRATEGY` | `donchian_breakout` | entry signal (`ma_crossover`, `rsi_reversal`, `macd_crossover`, `bollinger_breakout`, `volume_spike`, `donchian_breakout`) |
| `MIN_USDT_VOLUME` | `0` | min 24h USDT volume to include a coin (`0` = every coin) |
| `MAX_POSITIONS` | `5` | concurrent positions; cash is split evenly across open slots |
| `STARTING_CASH` | `100` | virtual starting balance (USDT) |
| `TAKE_PROFIT` | `0.05` | close a position at +5% |
| `STOP_LOSS` | `0.03` | close a position at −3% |
| `FEE_RATE` | `0.001` | simulated fee per side (0.1%) |

**Exit model:** a position is opened on a BUY signal and closed when price hits its
**take-profit** or **stop-loss** (not on an opposite signal). Freed capital rolls
into the next signal — so the bankroll compounds up or decays down over time.

> ⚠️ Scanning *every* coin includes thin/illiquid ones whose paper fills are
> optimistic. Raise `MIN_USDT_VOLUME` (e.g. `1000000`) to restrict to liquid coins.
> Re-run `run_backtest.py` periodically — signal edges are thin and shift.
