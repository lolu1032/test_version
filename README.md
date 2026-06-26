# Crypto Paper-Trading Bot

A free, self-contained **paper-trading** (simulated, no real money) bot for Binance
spot markets. Every 15 minutes it scans the most liquid USDT coins, applies a
technical signal, and opens/closes **virtual** positions. State lives in
`ledger.json`, which GitHub Actions commits back to the repo after each run — so
the git history *is* your trade log. No API key required (all market data is public).

> ⚠️ Paper trading only. No real orders are ever placed. Backtest numbers are
> historical and **not** a promise of future profit.

## Components

| File | What it does |
|------|--------------|
| `signals.py` | 8 indicators (SMA, EMA, RSI, MACD, Bollinger, ATR, Stochastic, Donchian) + 6 signal factories. Pure stdlib. |
| `backtest.py` | No-lookahead backtest engine (win rate / return / max drawdown / fees). |
| `test_all.py` | 57 deterministic unit tests defining correctness of the above. |
| `data.py` | Public Binance REST: klines + liquid-symbol discovery (stdlib `urllib`). |
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
| `STRATEGY` | `macd_crossover` | which signal drives entries (`ma_crossover`, `rsi_reversal`, `macd_crossover`, `bollinger_breakout`, `volume_spike`, `donchian_breakout`) |
| `TOP_N` | `30` | how many top-volume coins to scan |
| `MAX_POSITIONS` | `5` | max simultaneous open positions |
| `POSITION_PCT` | `0.20` | fraction of starting cash per trade |
| `STARTING_CASH` | `1000` | virtual starting balance (USDT) |
| `FEE_RATE` | `0.001` | simulated fee per side (0.1%) |
| `TAKE_PROFIT` / `STOP_LOSS` | off | optional safety exits, e.g. `0.10` / `0.05` |

Live behaviour mirrors `backtest.py` exactly (enter on BUY, exit on SELL,
long-only, one position per symbol), so what you measure is what you run.

> ⚠️ `volume_spike` is **entry-only** (it never emits SELL by design). Used alone
> it buys and never exits, so its backtest "return" is just an open buy-and-hold
> position, not realized trades. Only pair it with `TAKE_PROFIT`/`STOP_LOSS`.
> The default `donchian_breakout` was the only signal that both round-trips and
> stayed positive on the test window — but margins are thin; re-run
> `run_backtest.py` periodically and tune.
