"""15-minute paper-trading scanner (the live cron entry point).

Each run scans (almost) every tradeable spot COIN on Binance, applies the entry
signal to fresh candles, and opens paper positions. Each open position carries a
stop-loss and take-profit; a position is CLOSED when price hits its SL or TP,
freeing capital to rotate into the next coin. Capital rolls forward: whatever is
left after a loss (or gained after a win) is what funds the next trades.

State lives in ledger.json (the single source of truth), which the GitHub Action
commits back to the repo each run. Per-trade events (every BUY and SELL, with
symbol, SL, TP, reason, PnL, and remaining cash) are recorded so the log tells
the full story.

No real orders are ever placed. Fills are bookkeeping at the latest close price,
converted to USDT so the ledger stays in one currency. No API key required.
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor
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

# ---- Config (override via env in the workflow) -----------------------------
SIGNALS = {
    "ma_crossover": make_ma_crossover(9, 21),
    "rsi_reversal": make_rsi_reversal(14),
    "macd_crossover": make_macd_crossover(),
    "bollinger_breakout": make_bollinger_breakout(20, 2),
    "volume_spike": make_volume_spike_breakout(20, 3.0),
    "donchian_breakout": make_donchian_breakout(20),
}

STRATEGY = os.getenv("STRATEGY", "donchian_breakout")  # entry signal
MIN_USDT_VOLUME = float(os.getenv("MIN_USDT_VOLUME", "0"))  # 0 = literally all coins
MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", "5"))     # capital split evenly across slots
INTERVAL = os.getenv("INTERVAL", "15m")
KLINE_LIMIT = int(os.getenv("KLINE_LIMIT", "200"))
FEE_RATE = float(os.getenv("FEE_RATE", "0.001"))
STARTING_CASH = float(os.getenv("STARTING_CASH", "100.0"))
TAKE_PROFIT = float(os.getenv("TAKE_PROFIT", "0.05"))     # +5% -> close
STOP_LOSS = float(os.getenv("STOP_LOSS", "0.03"))         # -3% -> close
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "16"))
LEDGER_PATH = os.getenv("LEDGER_PATH", "ledger.json")


def _now():
    return datetime.now(timezone.utc).isoformat()


def load_ledger():
    if os.path.exists(LEDGER_PATH):
        with open(LEDGER_PATH) as f:
            return json.load(f)
    return {
        "starting_cash": STARTING_CASH,
        "cash": STARTING_CASH,
        "positions": {},
        "history": [],
        "events": [],          # full append-only trade log
        "last_run_events": [],  # events from the most recent run (for Notion)
        "runs": 0,
        "updated_at": None,
    }


def save_ledger(ledger):
    ledger["updated_at"] = _now()
    with open(LEDGER_PATH, "w") as f:
        json.dump(ledger, f, indent=2)


def _record(ledger, event):
    ledger["events"].append(event)
    ledger["last_run_events"].append(event)


def _open_position(ledger, sym, price_usdt, usdt_rate, budget):
    if budget <= 0 or price_usdt <= 0:
        return
    fee = budget * FEE_RATE
    units = (budget - fee) / price_usdt
    ledger["cash"] -= budget
    stop_loss = price_usdt * (1 - STOP_LOSS)
    take_profit = price_usdt * (1 + TAKE_PROFIT)
    ledger["positions"][sym] = {
        "signal": STRATEGY,
        "entry_price": price_usdt,
        "units": units,
        "notional": budget,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "usdt_rate": usdt_rate,
        "opened_at": _now(),
    }
    _record(ledger, {
        "ts": _now(), "action": "BUY", "symbol": sym,
        "price": round(price_usdt, 6),
        "stop_loss": round(stop_loss, 6), "take_profit": round(take_profit, 6),
        "reason": STRATEGY, "pnl": None,
        "cash_after": round(ledger["cash"], 4),
    })
    print(f"  BUY  {sym} @ {price_usdt:.6g}  SL={stop_loss:.6g} TP={take_profit:.6g} "
          f"notional={budget:.2f}  cash_left={ledger['cash']:.2f}")


def _close_position(ledger, sym, price_usdt, reason):
    pos = ledger["positions"].pop(sym)
    proceeds = pos["units"] * price_usdt
    fee = proceeds * FEE_RATE
    ledger["cash"] += proceeds - fee
    cost = pos["notional"]
    pnl = (proceeds - fee) - cost
    return_pct = pnl / cost * 100 if cost else 0.0
    rec = {
        "ts": _now(), "action": "SELL", "symbol": sym,
        "price": round(price_usdt, 6),
        "stop_loss": round(pos["stop_loss"], 6),
        "take_profit": round(pos["take_profit"], 6),
        "reason": reason, "pnl": round(pnl, 4),
        "return_pct": round(return_pct, 4),
        "entry_price": pos["entry_price"],
        "opened_at": pos["opened_at"], "closed_at": _now(),
        "cash_after": round(ledger["cash"], 4),
    }
    ledger["history"].append(rec)
    _record(ledger, rec)
    print(f"  SELL {sym} @ {price_usdt:.6g} ({reason})  pnl={pnl:+.2f} "
          f"({return_pct:+.2f}%)  cash={ledger['cash']:.2f}")


def _fetch_all(symbols):
    """Fetch klines for many symbols concurrently. Returns {symbol: candles}."""
    out = {}

    def one(sym):
        try:
            return sym, data.get_klines(sym, interval=INTERVAL, limit=KLINE_LIMIT)
        except Exception:
            return sym, None

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for sym, candles in ex.map(one, symbols):
            if candles:
                out[sym] = candles
    return out


def scan():
    if STRATEGY not in SIGNALS:
        raise SystemExit(f"Unknown STRATEGY={STRATEGY}; choose from {list(SIGNALS)}")
    signal_fn = SIGNALS[STRATEGY]
    ledger = load_ledger()
    ledger["runs"] += 1
    ledger["last_run_events"] = []
    ledger.setdefault("events", [])
    print(f"[{_now()}] run #{ledger['runs']}  strategy={STRATEGY}  "
          f"cash={ledger['cash']:.2f}  positions={len(ledger['positions'])}  "
          f"SL={STOP_LOSS:.0%} TP={TAKE_PROFIT:.0%}")

    coins = data.get_all_coins(min_usdt_volume=MIN_USDT_VOLUME)
    rate = {c["symbol"]: c["usdt_rate"] for c in coins}
    symbols = [c["symbol"] for c in coins]
    for held in ledger["positions"]:
        if held not in rate:
            symbols.append(held)
            rate[held] = ledger["positions"][held].get("usdt_rate", 1.0)
    print(f"  scanning {len(symbols)} coins...")

    klines = _fetch_all(symbols)
    marks = {}  # symbol -> current USDT price

    # --- EXITS FIRST: free up capital before looking for new entries ---
    for sym in list(ledger["positions"]):
        candles = klines.get(sym)
        if not candles:
            continue
        price_usdt = candles[-1]["close"] * rate.get(sym, 1.0)
        marks[sym] = price_usdt
        pos = ledger["positions"][sym]
        if price_usdt <= pos["stop_loss"]:
            _close_position(ledger, sym, price_usdt, "stop-loss")
        elif price_usdt >= pos["take_profit"]:
            _close_position(ledger, sym, price_usdt, "take-profit")

    # --- ENTRIES: rotate freed capital into fresh signals ---
    for sym in symbols:
        if sym in ledger["positions"]:
            continue
        if len(ledger["positions"]) >= MAX_POSITIONS or ledger["cash"] <= 0:
            break
        candles = klines.get(sym)
        if not candles:
            continue
        if signal_fn(candles) == "BUY":
            price_usdt = candles[-1]["close"] * rate.get(sym, 1.0)
            marks[sym] = price_usdt
            # Split remaining cash evenly across remaining slots, so capital is
            # fully deployed and rolls forward (whatever is left funds the rest).
            slots_left = MAX_POSITIONS - len(ledger["positions"])
            budget = ledger["cash"] / slots_left if slots_left > 0 else 0.0
            _open_position(ledger, sym, price_usdt, rate.get(sym, 1.0), budget)

    # --- mark-to-market equity ---
    holdings_value = 0.0
    for sym, pos in ledger["positions"].items():
        px = marks.get(sym)
        if px is None:
            c = klines.get(sym)
            px = c[-1]["close"] * rate.get(sym, 1.0) if c else pos["entry_price"]
        holdings_value += pos["units"] * px
    equity = ledger["cash"] + holdings_value
    ledger["equity"] = round(equity, 4)
    ledger["total_return_pct"] = round(
        (equity - ledger["starting_cash"]) / ledger["starting_cash"] * 100, 4
    )
    # stamp equity on this run's events for context
    for ev in ledger["last_run_events"]:
        ev["equity"] = ledger["equity"]
    save_ledger(ledger)
    print(f"  equity={equity:.2f}  total_return={ledger['total_return_pct']:+.2f}%  "
          f"open={len(ledger['positions'])}  closed={len(ledger['history'])}  "
          f"events_this_run={len(ledger['last_run_events'])}")
    return ledger


if __name__ == "__main__":
    scan()
