"""Backtest runner: measure which signals actually make money on recent data.

Fetches historical klines for the most liquid USDT symbols and runs every
signal through the (test-gated) backtest engine, then prints a comparison
table ranked by average return. This is how you decide which signals are worth
running live -- the numbers come from the data, not from intuition.

Usage:
    python3 run_backtest.py                 # defaults: top 25 symbols, 1000x15m
    python3 run_backtest.py 40 1h 1000      # top 40, 1h candles, 1000 bars
"""

import sys

import data
from backtest import backtest
from signals import (
    make_ma_crossover,
    make_rsi_reversal,
    make_macd_crossover,
    make_bollinger_breakout,
    make_volume_spike_breakout,
    make_donchian_breakout,
)

# The canonical, most widely-used signals with sensible default parameters.
STRATEGIES = {
    "ma_crossover(9/21)": make_ma_crossover(9, 21),
    "rsi_reversal(14)": make_rsi_reversal(14),
    "macd_crossover": make_macd_crossover(),
    "bollinger_breakout(20,2)": make_bollinger_breakout(20, 2),
    "volume_spike(20,3x)": make_volume_spike_breakout(20, 3.0),
    "donchian_breakout(20)": make_donchian_breakout(20),
}

FEE_RATE = 0.001  # 0.1% per side, realistic Binance spot taker fee


def run(top_n=25, interval="15m", limit=1000):
    symbols = data.get_usdt_symbols(top_n=top_n)
    print(f"Backtesting {len(symbols)} symbols on {limit}x{interval} candles "
          f"(fee {FEE_RATE*100:.2f}%/side)\n")

    # name -> aggregated stats across all symbols
    agg = {name: {"ret": [], "win": [], "trades": 0} for name in STRATEGIES}

    for i, sym in enumerate(symbols, 1):
        try:
            candles = data.get_klines(sym, interval=interval, limit=limit)
        except Exception as e:
            print(f"  [{i}/{len(symbols)}] {sym}: fetch failed ({e})")
            continue
        if len(candles) < 60:
            continue
        for name, fn in STRATEGIES.items():
            r = backtest(candles, fn, starting_cash=1000.0,
                         position_pct=1.0, fee_rate=FEE_RATE)
            agg[name]["ret"].append(r["total_return_pct"])
            if r["num_trades"]:
                agg[name]["win"].append(r["win_rate"])
            agg[name]["trades"] += r["num_trades"]
        print(f"  [{i}/{len(symbols)}] {sym}: done")

    print("\n" + "=" * 78)
    print(f"{'SIGNAL':<26}{'avg ret %':>12}{'avg win %':>12}{'trades':>10}{'symbols':>10}")
    print("-" * 78)
    ranked = []
    for name, a in agg.items():
        n = len(a["ret"])
        avg_ret = sum(a["ret"]) / n if n else 0.0
        avg_win = (sum(a["win"]) / len(a["win"]) * 100) if a["win"] else 0.0
        ranked.append((avg_ret, name, avg_win, a["trades"], n))
    ranked.sort(reverse=True)
    for avg_ret, name, avg_win, trades, n in ranked:
        print(f"{name:<26}{avg_ret:>12.2f}{avg_win:>12.1f}{trades:>10}{n:>10}")
    print("=" * 78)
    if ranked:
        print(f"\nTop performer on this window: {ranked[0][1]} "
              f"({ranked[0][0]:+.2f}% avg)")
        print("NOTE: past performance on recent candles != future profit. "
              "Re-run periodically and treat results as relative, not promises.")
    return ranked


if __name__ == "__main__":
    top_n = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    interval = sys.argv[2] if len(sys.argv) > 2 else "15m"
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 1000
    run(top_n, interval, limit)
