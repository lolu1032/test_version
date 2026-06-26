"""15-minute paper-trading scanner (the live cron entry point).

Each run: scan the most liquid USDT coins, apply the configured signal to fresh
candles, open paper positions on BUY and close them on SELL. State lives in
ledger.json (the single source of truth) which the GitHub Action commits back to
the repo after every run -- so the git history *is* the trade log.

No real orders are ever placed. "Fills" are just bookkeeping at the latest close
price. No API key required (market data is public).

Semantics deliberately mirror backtest.py so live behaviour matches what the
test-gated engine measured: enter on BUY, exit on SELL, long-only, one position
per symbol, fee applied per side.
"""

import json
import os
from datetime import datetime, timezone

import data
from signals import (
    make_ma_crossover,
    make_rsi_reversal,
    make_macd_crossover,
    make_bollinger_breakout,
    make_volume_spike_breakout,
    make_donchian_breakout,
)

# ---- Config (override via env in the workflow if you like) -----------------
SIGNALS = {
    "ma_crossover": make_ma_crossover(9, 21),
    "rsi_reversal": make_rsi_reversal(14),
    "macd_crossover": make_macd_crossover(),
    "bollinger_breakout": make_bollinger_breakout(20, 2),
    "volume_spike": make_volume_spike_breakout(20, 3.0),
    "donchian_breakout": make_donchian_breakout(20),
}

STRATEGY = os.getenv("STRATEGY", "donchian_breakout")  # which signal drives entries
TOP_N = int(os.getenv("TOP_N", "30"))               # how many coins to scan
MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", "5"))
POSITION_PCT = float(os.getenv("POSITION_PCT", "0.20"))  # of starting cash / trade
INTERVAL = os.getenv("INTERVAL", "15m")
KLINE_LIMIT = int(os.getenv("KLINE_LIMIT", "200"))
FEE_RATE = float(os.getenv("FEE_RATE", "0.001"))
STARTING_CASH = float(os.getenv("STARTING_CASH", "100.0"))
LEDGER_PATH = os.getenv("LEDGER_PATH", "ledger.json")

# Optional safety exits (off by default so live == backtest). Set to e.g. 0.10
# and 0.05 to enable a 10% take-profit / 5% stop-loss.
TAKE_PROFIT = os.getenv("TAKE_PROFIT")
STOP_LOSS = os.getenv("STOP_LOSS")


def _now():
    return datetime.now(timezone.utc).isoformat()


def load_ledger():
    if os.path.exists(LEDGER_PATH):
        with open(LEDGER_PATH) as f:
            return json.load(f)
    return {
        "starting_cash": STARTING_CASH,
        "cash": STARTING_CASH,
        "positions": {},   # symbol -> position dict
        "history": [],     # list of closed trades
        "runs": 0,
        "updated_at": None,
    }


def save_ledger(ledger):
    ledger["updated_at"] = _now()
    with open(LEDGER_PATH, "w") as f:
        json.dump(ledger, f, indent=2)


def _close_position(ledger, sym, price, reason):
    pos = ledger["positions"].pop(sym)
    proceeds = pos["units"] * price
    fee = proceeds * FEE_RATE
    ledger["cash"] += proceeds - fee
    cost = pos["notional"]
    pnl = (proceeds - fee) - cost
    return_pct = pnl / cost * 100 if cost else 0.0
    ledger["history"].append({
        "symbol": sym,
        "signal": pos["signal"],
        "entry_price": pos["entry_price"],
        "exit_price": price,
        "units": pos["units"],
        "pnl": round(pnl, 4),
        "return_pct": round(return_pct, 4),
        "reason": reason,
        "opened_at": pos["opened_at"],
        "closed_at": _now(),
    })
    print(f"  SELL {sym} @ {price:.6g} ({reason})  pnl={pnl:+.2f} ({return_pct:+.2f}%)")


def _open_position(ledger, sym, price):
    budget = min(ledger["starting_cash"] * POSITION_PCT, ledger["cash"])
    if budget <= 0:
        return False
    fee = budget * FEE_RATE
    units = (budget - fee) / price
    ledger["cash"] -= budget
    ledger["positions"][sym] = {
        "signal": STRATEGY,
        "entry_price": price,
        "units": units,
        "notional": budget,
        "opened_at": _now(),
    }
    print(f"  BUY  {sym} @ {price:.6g}  notional={budget:.2f}")
    return True


def _safety_exit(pos, price):
    """Return a reason string if a TP/SL threshold is breached, else None."""
    change = (price - pos["entry_price"]) / pos["entry_price"]
    if TAKE_PROFIT and change >= float(TAKE_PROFIT):
        return "take-profit"
    if STOP_LOSS and change <= -float(STOP_LOSS):
        return "stop-loss"
    return None


def scan():
    if STRATEGY not in SIGNALS:
        raise SystemExit(f"Unknown STRATEGY={STRATEGY}; choose from {list(SIGNALS)}")
    signal_fn = SIGNALS[STRATEGY]
    ledger = load_ledger()
    ledger["runs"] += 1
    print(f"[{_now()}] run #{ledger['runs']}  strategy={STRATEGY}  "
          f"cash={ledger['cash']:.2f}  positions={len(ledger['positions'])}")

    symbols = data.get_usdt_symbols(top_n=TOP_N)
    # Always include symbols we already hold, even if they fell out of top_n.
    for held in ledger["positions"]:
        if held not in symbols:
            symbols.append(held)

    marks = {}  # symbol -> latest close, for mark-to-market
    for sym in symbols:
        try:
            candles = data.get_klines(sym, interval=INTERVAL, limit=KLINE_LIMIT)
        except Exception as e:
            print(f"  {sym}: fetch failed ({e})")
            continue
        if not candles:
            continue
        price = candles[-1]["close"]
        marks[sym] = price
        decision = signal_fn(candles)  # full window; NO LOOKAHEAD inside

        if sym in ledger["positions"]:
            reason = _safety_exit(ledger["positions"][sym], price)
            if reason:
                _close_position(ledger, sym, price, reason)
            elif decision == "SELL":
                _close_position(ledger, sym, price, "signal")
        else:
            if (decision == "BUY"
                    and len(ledger["positions"]) < MAX_POSITIONS
                    and ledger["cash"] > 0):
                _open_position(ledger, sym, price)

    # Mark-to-market equity snapshot.
    holdings_value = sum(
        pos["units"] * marks.get(sym, pos["entry_price"])
        for sym, pos in ledger["positions"].items()
    )
    equity = ledger["cash"] + holdings_value
    ledger["equity"] = round(equity, 4)
    ledger["total_return_pct"] = round(
        (equity - ledger["starting_cash"]) / ledger["starting_cash"] * 100, 4
    )
    save_ledger(ledger)
    print(f"  equity={equity:.2f}  total_return={ledger['total_return_pct']:+.2f}%  "
          f"open={len(ledger['positions'])}  closed={len(ledger['history'])}")
    return ledger


if __name__ == "__main__":
    scan()
