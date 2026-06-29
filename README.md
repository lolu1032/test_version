# Crypto Paper-Trading Bot

A free, self-contained **paper-trading** (simulated, no real money) bot for Binance
spot markets. Every 15 minutes it scans **every tradeable coin** (~440, deduped by
base asset, non-USDT pairs converted to USDT), applies a technical signal, and opens
**virtual** positions. Each position gets a **stop-loss and take-profit**; when price
hits either, the position closes and the freed capital **rolls into the next coin**
(whatever is left after a loss/gain funds the next trades). State lives in
`ledger.json`, which GitHub Actions commits back to the repo after each run — so the
git history *is* your trade log. No API key required (all market data is public).

**Live status:** [`STATUS.md`](STATUS.md) is an auto-generated dashboard (equity,
return, every open position with live unrealized PnL / SL / TP, recent closed
trades). It's rewritten and committed every run — just open it on GitHub.

**Trade log:** every BUY (symbol, entry, SL, TP) and SELL (reason, PnL, cash left)
is recorded in `ledger.json` and mirrored to Notion (one row per event).

> ⚠️ Paper trading only. No real orders are ever placed. Backtest numbers are
> historical and **not** a promise of future profit.

## Components

| File | What it does |
|------|--------------|
| `signals.py` | 8 indicators (SMA, EMA, RSI, MACD, Bollinger, ATR, Stochastic, Donchian) + 6 signal factories. Pure stdlib. |
| `backtest.py` | No-lookahead backtest engine (win rate / return / max drawdown / fees). |
| `test_all.py` | 57 unit tests for the indicators (`signals.py`) and the backtest engine (`backtest.py`). |
| `test_scanner.py` | 11 unit tests for the live scanner's money logic: intrabar SL/TP fills, stop-priority, and mark-to-market fallback. |
| `data.py` | Public Binance REST: klines + symbol discovery (stdlib `urllib`). Uses `data-api.binance.vision` so it works from US-based CI runners (`api.binance.com` returns HTTP 451 there). Override with `BINANCE_BASE`. |
| `run_backtest.py` | Runs every signal over historical data and ranks them. A rough read on signal edge — **not** an exact model of the live bot (see "Backtest vs live" below). |
| `scanner.py` | The 15-minute cron entry point: scan → paper trade → update `ledger.json`. |
| `notion_sync.py` | Optional best-effort push of one row per trade event to a Notion database. |
| `.github/workflows/scan.yml` | Runs the tests, then the scanner every 15 min, and commits the ledger. |

All 68 tests pass (`python3 -m unittest discover`), covering the indicators, the
backtest engine, and the live scanner's exit/marking logic. The `data.py` network
layer (symbol discovery / quote→USDT conversion) is not yet unit-tested.

## Quick start

```bash
# 1. Run the test suite (indicators + backtest + live scanner)
python3 -m unittest discover

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
   each trade into a Notion database. Create the database first with these
   properties (exact names/types, since `notion_sync.py` writes to them):
   `Name` (Title), `Action` (Text), `Symbol` (Text), `Price` (Number),
   `Stop Loss` (Number), `Take Profit` (Number), `Reason` (Text), `PnL` (Number),
   `Cash After` (Number), `Equity` (Number). Share it with your integration.

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
**take-profit** or **stop-loss** (not on an opposite signal). The trigger is the
intrabar **touch** — a stop fires when the candle's *low* reaches it, a take-profit
when the *high* reaches it — and the fill is booked **at that threshold** (when a
single candle touches both, it's treated as the stop-loss). Freed capital rolls
into the next signal, so the bankroll compounds up or decays down over time.

> ⚠️ SL/TP are checked once per 15-minute candle, not tick-by-tick. A gap or a
> delayed cron can blow through a level intrabar; the fill is still booked at the
> threshold, so on fast moves real results would be *worse* than recorded. There is
> no slippage model — thin coins (`MIN_USDT_VOLUME=0`) fill optimistically. Raise
> `MIN_USDT_VOLUME` (e.g. `1000000`) to restrict to liquid coins.

> ⚠️ **Backtest vs live differ.** `run_backtest.py` exits on the *opposite signal*
> with one all-in position and no SL/TP, over ~25 liquid majors. The live bot exits
> on **fixed SL/TP**, ignores SELL signals, and splits a shared bankroll across 5
> slots over ~440 coins. Treat the ranking as a rough signal-edge hint, **not** a
> prediction of live results. Signal edges are thin and shift — re-check often.
