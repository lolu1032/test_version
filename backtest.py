"""Backtest engine for the paper-trading bot.

Walks candles chronologically with NO LOOKAHEAD: the decision at index t may
use only candles[0..t] (signal_fn receives candles[:t+1]); a triggered trade
EXECUTES at candle t's close. Long-only, one position at a time. The engine
treats signal_fn as a black box and NEVER raises.
"""


def backtest(
    candles,
    signal_fn,
    *,
    starting_cash=1000.0,
    position_pct=1.0,
    fee_rate=0.0,
):
    result = {
        "trades": [],
        "num_trades": 0,
        "win_rate": 0.0,
        "total_return_pct": 0.0,
        "max_drawdown_pct": 0.0,
    }
    if not candles:
        return result

    cash = float(starting_cash)
    units = 0.0
    in_position = False
    entry_index = None
    entry_price = None
    notional_committed = None

    trades = []
    equity_curve = []

    for t in range(len(candles)):
        window = candles[: t + 1]  # NO LOOKAHEAD: only candles[0..t]
        try:
            decision = signal_fn(window)
        except Exception:
            decision = "HOLD"

        price = candles[t]["close"]

        if decision == "BUY" and not in_position:
            notional = cash * position_pct
            if notional > 0 and price > 0:
                fee_in = notional * fee_rate
                units = (notional - fee_in) / price
                cash -= notional
                in_position = True
                entry_index = t
                entry_price = price
                notional_committed = notional
        elif decision == "SELL" and in_position:
            gross = units * price
            fee_out = gross * fee_rate
            net = gross - fee_out
            cash += net
            return_pct = (net - notional_committed) / notional_committed * 100
            trades.append(
                {
                    "entry_index": entry_index,
                    "entry_price": entry_price,
                    "exit_index": t,
                    "exit_price": price,
                    "return_pct": return_pct,
                }
            )
            units = 0.0
            in_position = False
            entry_index = entry_price = notional_committed = None
        # BUY-while-in-position and SELL-while-flat are ignored.

        equity = cash + units * price  # mark-to-market at this close
        equity_curve.append(equity)

    final_equity = equity_curve[-1]
    num_trades = len(trades)
    wins = sum(1 for tr in trades if tr["return_pct"] > 0)

    result["trades"] = trades
    result["num_trades"] = num_trades
    result["win_rate"] = wins / num_trades if num_trades > 0 else 0.0
    result["total_return_pct"] = (
        (final_equity - starting_cash) / starting_cash * 100 if starting_cash > 0 else 0.0
    )
    result["max_drawdown_pct"] = _max_drawdown_pct(equity_curve)
    return result


def _max_drawdown_pct(equity_curve):
    """Max peak-to-trough decline as a positive percent magnitude. 0.0 if the
    curve is empty or never declines."""
    if not equity_curve:
        return 0.0
    max_dd = 0.0
    peak = equity_curve[0]
    for e in equity_curve:
        if e > peak:
            peak = e
        if peak > 0:
            dd = (peak - e) / peak * 100
            if dd > max_dd:
                max_dd = dd
    return max_dd
