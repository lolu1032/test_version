"""Deterministic unittest suite for the paper-trading bot (variant-1).

Run with:  python3 -m unittest discover
"""

import math
import unittest

import signals as S
from backtest import backtest


def C(o, h, l, c, v):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


def candle_from_close(c, v=100):
    """Minimal candle where high==low==close (handy for price-only tests)."""
    return {"open": c, "high": c, "low": c, "close": c, "volume": v}


def scripted(decisions):
    """signal_fn that returns a decision keyed by current index (len(window)-1)."""

    def fn(window):
        return decisions.get(len(window) - 1, "HOLD")

    return fn


# ===========================================================================
# PART A -- INDICATORS
# ===========================================================================
class TestSMA(unittest.TestCase):
    def test_full_period(self):
        self.assertEqual(S.sma([1, 2, 3, 4, 5], 5), 3.0)

    def test_partial_window(self):
        self.assertEqual(S.sma([1, 2, 3, 4, 5], 3), 4.0)

    def test_insufficient_returns_none(self):
        self.assertIsNone(S.sma([1, 2], 5))

    def test_table(self):
        cases = [
            ([1, 2, 3, 4, 5], 5, 3.0),
            ([1, 2, 3, 4, 5], 3, 4.0),
            ([2, 4, 6, 8], 2, 7.0),
            ([10], 1, 10.0),
        ]
        for values, period, expected in cases:
            with self.subTest(values=values, period=period):
                self.assertAlmostEqual(S.sma(values, period), expected, delta=1e-9)


class TestEMA(unittest.TestCase):
    def test_known_series(self):
        self.assertEqual(S.ema([1, 2, 3, 4, 5], 3), [2.0, 3.0, 4.0])

    def test_first_value_is_sma_seed(self):
        values = [3, 7, 2, 9, 11, 4]
        period = 3
        series = S.ema(values, period)
        seed = sum(values[:period]) / period
        self.assertAlmostEqual(series[0], seed, delta=1e-9)

    def test_recurrence(self):
        values = [1, 2, 3, 4, 5]
        period = 3
        k = 2 / (period + 1)
        series = S.ema(values, period)
        # out[1] = values[3]*k + out[0]*(1-k)
        self.assertAlmostEqual(
            series[1], values[3] * k + series[0] * (1 - k), delta=1e-9
        )

    def test_insufficient_returns_none(self):
        self.assertIsNone(S.ema([1, 2], 3))


class TestRSI(unittest.TestCase):
    def test_monotonic_increasing_is_100(self):
        closes = list(range(1, 21))  # strictly increasing, no losses
        self.assertAlmostEqual(S.rsi(closes, 14), 100.0, delta=1e-9)

    def test_monotonic_decreasing_is_0(self):
        closes = list(range(20, 0, -1))  # strictly decreasing, no gains
        self.assertAlmostEqual(S.rsi(closes, 14), 0.0, delta=1e-9)

    def test_one_too_few_deltas_returns_none(self):
        closes = list(range(1, 15))  # len == period == 14 -> only 13 deltas
        self.assertIsNone(S.rsi(closes, 14))

    def test_series_prev_matches_prior_slice(self):
        # Locked property: rsi(closes[:-1]) == _rsi_series(closes)[-2]
        closes = [44, 44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42,
                  45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28]
        series = S._rsi_series(closes, 14)
        self.assertAlmostEqual(series[-2], S.rsi(closes[:-1], 14), delta=1e-9)


class TestMACD(unittest.TestCase):
    def test_small_reference(self):
        m, sig, hist = S.macd([1, 2, 3, 4, 5], fast=2, slow=3, signal=2)
        self.assertAlmostEqual(m, 0.5, delta=1e-9)
        self.assertAlmostEqual(sig, 0.5, delta=1e-9)
        self.assertAlmostEqual(hist, 0.0, delta=1e-9)

    def test_insufficient_returns_none(self):
        # need slow+signal-1 = 4 closes
        self.assertIsNone(S.macd([1, 2, 3], fast=2, slow=3, signal=2))


class TestBollinger(unittest.TestCase):
    def test_reference_population_std(self):
        upper, mid, lower = S.bollinger([2, 4, 6, 8, 10], period=5, num_std=2)
        self.assertAlmostEqual(upper, 6 + 2 * math.sqrt(8), delta=1e-9)
        self.assertAlmostEqual(mid, 6.0, delta=1e-9)
        self.assertAlmostEqual(lower, 6 - 2 * math.sqrt(8), delta=1e-9)
        # explicit pinned constants
        self.assertAlmostEqual(upper, 11.65685424949238, delta=1e-9)
        self.assertAlmostEqual(lower, 0.3431457505076194, delta=1e-9)

    def test_insufficient_returns_none(self):
        self.assertIsNone(S.bollinger([1, 2, 3], period=20))


class TestATR(unittest.TestCase):
    def test_reference(self):
        candles = [C(9, 10, 8, 9, 1), C(11, 12, 9, 11, 1), C(9, 11, 7, 8, 1)]
        self.assertAlmostEqual(S.atr(candles, period=2), 3.25, delta=1e-9)

    def test_insufficient_returns_none(self):
        self.assertIsNone(S.atr([C(9, 10, 8, 9, 1)], period=2))


class TestStochastic(unittest.TestCase):
    def test_reference(self):
        candles = [C(7, 10, 5, 7, 1), C(11, 12, 6, 11, 1), C(8, 11, 7, 8, 1)]
        k, d = S.stochastic(candles, k_period=2, d_period=2)
        self.assertAlmostEqual(k, 33.333333333333336, delta=1e-9)
        self.assertAlmostEqual(d, 59.52380952380952, delta=1e-9)

    def test_flat_range_k_zero(self):
        # highestHigh == lowestLow -> %K convention 0.0
        candles = [C(5, 5, 5, 5, 1), C(5, 5, 5, 5, 1), C(5, 5, 5, 5, 1)]
        k, d = S.stochastic(candles, k_period=2, d_period=2)
        self.assertEqual(k, 0.0)
        self.assertEqual(d, 0.0)

    def test_insufficient_returns_none(self):
        candles = [C(7, 10, 5, 7, 1), C(11, 12, 6, 11, 1)]
        self.assertIsNone(S.stochastic(candles, k_period=2, d_period=2))


class TestDonchian(unittest.TestCase):
    def test_reference(self):
        candles = [C(0, 10, 5, 7, 1), C(0, 12, 6, 11, 1), C(0, 11, 7, 8, 1)]
        upper, lower = S.donchian(candles, period=3)
        self.assertEqual(upper, 12)
        self.assertEqual(lower, 5)

    def test_insufficient_returns_none(self):
        candles = [C(0, 10, 5, 7, 1), C(0, 12, 6, 11, 1)]
        self.assertIsNone(S.donchian(candles, period=3))


# ===========================================================================
# PART B -- SIGNALS
# ===========================================================================
class TestMACrossover(unittest.TestCase):
    def setUp(self):
        self.sig = S.make_ma_crossover(2, 3)

    def test_golden_cross_buy_on_exact_candle(self):
        closes = [20, 18, 16, 14, 19, 22]
        candles = [candle_from_close(c) for c in closes]
        # cross happens at index 4 (window closes[:5])
        self.assertEqual(self.sig(candles[:5]), "BUY")
        # immediately prior window is a genuine HOLD (short < long, no cross)
        self.assertEqual(self.sig(candles[:4]), "HOLD")
        # next window: still short>long but not a cross -> HOLD
        self.assertEqual(self.sig(candles[:6]), "HOLD")

    def test_death_cross_sell(self):
        closes = [14, 16, 18, 20, 15, 12]
        candles = [candle_from_close(c) for c in closes]
        self.assertEqual(self.sig(candles[:5]), "SELL")
        self.assertEqual(self.sig(candles[:4]), "HOLD")

    def test_insufficient_holds(self):
        candles = [candle_from_close(c) for c in [1, 2, 3]]
        self.assertEqual(self.sig(candles), "HOLD")
        self.assertEqual(self.sig([]), "HOLD")


class TestRSIReversal(unittest.TestCase):
    def setUp(self):
        self.sig = S.make_rsi_reversal(period=3)

    def test_buy_only_on_upward_cross_through_30(self):
        closes = [100, 90, 80, 70, 60, 50, 55, 65, 80]
        candles = [candle_from_close(c) for c in closes]
        # RSI series (close idx 3..8) ~ [0,0,0,20,50,72.88]
        # staying below 30 (both prev & cur < 30) -> HOLD
        self.assertEqual(self.sig(candles[:7]), "HOLD")
        # crosses up through 30 (20 -> 50) -> BUY
        self.assertEqual(self.sig(candles[:8]), "BUY")
        # already above -> HOLD
        self.assertEqual(self.sig(candles[:9]), "HOLD")

    def test_sell_only_on_downward_cross_through_70(self):
        closes = [50, 60, 70, 80, 90, 100, 95, 85, 70]
        candles = [candle_from_close(c) for c in closes]
        # staying above 70 (both prev & cur > 70) -> HOLD
        self.assertEqual(self.sig(candles[:7]), "HOLD")
        # crosses down through 70 (80 -> 50) -> SELL
        self.assertEqual(self.sig(candles[:8]), "SELL")

    def test_insufficient_holds(self):
        candles = [candle_from_close(c) for c in [1, 2]]
        self.assertEqual(self.sig(candles), "HOLD")


class TestMACDCrossover(unittest.TestCase):
    def setUp(self):
        self.sig = S.make_macd_crossover(fast=2, slow=3, signal=2)

    def test_bullish_cross_buy(self):
        closes = [10, 9, 8, 7, 8, 10, 12]
        candles = [candle_from_close(c) for c in closes]
        self.assertEqual(self.sig(candles[:5]), "BUY")
        self.assertEqual(self.sig(candles[:4]), "HOLD")  # hist series too short
        self.assertEqual(self.sig(candles[:6]), "HOLD")  # already positive
        self.assertEqual(self.sig(candles[:7]), "HOLD")

    def test_bearish_cross_sell(self):
        closes = [7, 8, 9, 10, 9, 7, 5]
        candles = [candle_from_close(c) for c in closes]
        self.assertEqual(self.sig(candles[:5]), "SELL")
        self.assertEqual(self.sig(candles[:4]), "HOLD")

    def test_insufficient_holds(self):
        candles = [candle_from_close(c) for c in [1, 2, 3]]
        self.assertEqual(self.sig(candles), "HOLD")


class TestBollingerBreakout(unittest.TestCase):
    def setUp(self):
        self.sig = S.make_bollinger_breakout(period=3, num_std=1)

    def test_breakout_above_upper_buy(self):
        closes = [10, 10, 10, 10, 13]
        candles = [candle_from_close(c) for c in closes]
        self.assertEqual(self.sig(candles[:5]), "BUY")
        self.assertEqual(self.sig(candles[:4]), "HOLD")

    def test_breakdown_below_lower_sell(self):
        closes = [10, 10, 10, 10, 7]
        candles = [candle_from_close(c) for c in closes]
        self.assertEqual(self.sig(candles[:5]), "SELL")
        self.assertEqual(self.sig(candles[:4]), "HOLD")

    def test_insufficient_holds(self):
        candles = [candle_from_close(c) for c in [1, 2]]
        self.assertEqual(self.sig(candles), "HOLD")


class TestVolumeSpikeBreakout(unittest.TestCase):
    def setUp(self):
        self.sig = S.make_volume_spike_breakout(N=3, volume_multiplier=2)

    def _candles(self):
        return [
            C(0, 0, 0, 10, 100),
            C(0, 0, 0, 11, 100),
            C(0, 0, 0, 12, 100),
            C(0, 0, 0, 13, 100),
            C(0, 0, 0, 14, 1000),  # volume spike + price up -> BUY
        ]

    def test_volume_spike_with_price_up_buys(self):
        candles = self._candles()
        self.assertEqual(self.sig(candles[:5]), "BUY")
        self.assertEqual(self.sig(candles[:4]), "HOLD")

    def test_never_returns_sell_even_on_down_spike(self):
        candles = [
            C(0, 0, 0, 14, 100),
            C(0, 0, 0, 13, 100),
            C(0, 0, 0, 12, 100),
            C(0, 0, 0, 11, 100),
            C(0, 0, 0, 9, 1000),  # huge volume but price DOWN
        ]
        self.assertEqual(self.sig(candles), "HOLD")
        # exhaustively assert it never yields SELL across all prefixes
        for i in range(1, len(candles) + 1):
            self.assertIn(self.sig(candles[:i]), ("BUY", "HOLD"))

    def test_spike_needs_both_conditions(self):
        # price up but no volume spike -> HOLD
        candles = [
            C(0, 0, 0, 10, 100),
            C(0, 0, 0, 11, 100),
            C(0, 0, 0, 12, 100),
            C(0, 0, 0, 13, 100),
            C(0, 0, 0, 14, 150),  # 150 <= 2*100
        ]
        self.assertEqual(self.sig(candles), "HOLD")

    def test_insufficient_holds(self):
        candles = [C(0, 0, 0, 10, 100), C(0, 0, 0, 11, 100)]
        self.assertEqual(self.sig(candles), "HOLD")


class TestDonchianBreakout(unittest.TestCase):
    def setUp(self):
        self.sig = S.make_donchian_breakout(period=3)

    def _candles(self):
        return [
            C(0, 12, 8, 10, 1),
            C(0, 13, 9, 11, 1),
            C(0, 12, 8, 10, 1),
            C(0, 12, 9, 11, 1),  # inside channel -> HOLD
            C(0, 20, 10, 18, 1),  # close 18 > prior upper 13 -> BUY
            C(0, 12, 3, 4, 1),  # close 4 < prior lower 8 -> SELL
        ]

    def test_breakout_above_prior_channel_buy(self):
        candles = self._candles()
        self.assertEqual(self.sig(candles[:5]), "BUY")
        self.assertEqual(self.sig(candles[:4]), "HOLD")  # genuine inside channel

    def test_breakdown_below_prior_channel_sell(self):
        candles = self._candles()
        self.assertEqual(self.sig(candles[:6]), "SELL")

    def test_uses_prior_period_excluding_current(self):
        # current candle's own high must NOT be part of the channel it breaks
        candles = self._candles()
        prior = candles[1:4]  # the period BEFORE candle index 4
        prior_upper = max(c["high"] for c in prior)
        self.assertEqual(prior_upper, 13)
        self.assertTrue(candles[4]["close"] > prior_upper)

    def test_insufficient_holds(self):
        candles = [C(0, 12, 8, 10, 1), C(0, 13, 9, 11, 1)]
        self.assertEqual(self.sig(candles), "HOLD")


# ===========================================================================
# PART C -- BACKTEST ENGINE
# ===========================================================================
class TestBacktestExactTrades(unittest.TestCase):
    def test_exact_trades_list(self):
        closes = [100, 110, 90, 99]
        candles = [candle_from_close(c) for c in closes]
        sig = scripted({0: "BUY", 1: "SELL", 2: "BUY", 3: "SELL"})
        res = backtest(candles, sig, starting_cash=1000.0, fee_rate=0.0)

        self.assertEqual(res["num_trades"], 2)
        self.assertEqual(len(res["trades"]), 2)

        t1 = res["trades"][0]
        self.assertEqual(t1["entry_index"], 0)
        self.assertAlmostEqual(t1["entry_price"], 100, delta=1e-9)
        self.assertEqual(t1["exit_index"], 1)
        self.assertAlmostEqual(t1["exit_price"], 110, delta=1e-9)
        self.assertAlmostEqual(t1["return_pct"], 10.0, delta=1e-9)

        t2 = res["trades"][1]
        self.assertEqual(t2["entry_index"], 2)
        self.assertAlmostEqual(t2["entry_price"], 90, delta=1e-9)
        self.assertEqual(t2["exit_index"], 3)
        self.assertAlmostEqual(t2["exit_price"], 99, delta=1e-9)
        self.assertAlmostEqual(t2["return_pct"], 10.0, delta=1e-9)

        self.assertAlmostEqual(res["win_rate"], 1.0, delta=1e-9)
        self.assertAlmostEqual(res["total_return_pct"], 21.0, delta=1e-9)


class TestBacktestFeeMath(unittest.TestCase):
    def test_ten_percent_no_fee(self):
        candles = [candle_from_close(100), candle_from_close(110)]
        sig = scripted({0: "BUY", 1: "SELL"})
        res = backtest(candles, sig, fee_rate=0.0)
        self.assertAlmostEqual(res["total_return_pct"], 10.0, delta=1e-9)

    def test_fee_reduces_return(self):
        candles = [candle_from_close(100), candle_from_close(110)]
        sig = scripted({0: "BUY", 1: "SELL"})
        res = backtest(candles, sig, fee_rate=0.001)
        expected = ((1 - 0.001) ** 2 * 1.1 - 1) * 100
        self.assertAlmostEqual(res["total_return_pct"], expected, delta=1e-9)
        self.assertAlmostEqual(res["total_return_pct"], 9.78011, delta=1e-9)
        self.assertLess(res["total_return_pct"], 10.0)


class TestBacktestNoLookahead(unittest.TestCase):
    def test_window_is_exactly_prefix(self):
        candles = [candle_from_close(c) for c in [10, 20, 30, 40, 50]]
        seen = []

        def spy(window):
            seen.append(window)
            return "HOLD"

        backtest(candles, spy)
        self.assertEqual(len(seen), len(candles))
        for t, window in enumerate(seen):
            self.assertEqual(len(window), t + 1)
            self.assertIs(window[-1], candles[t])  # current candle identity
            # the future candle is never present in the window
            self.assertNotIn(candles[t + 1] if t + 1 < len(candles) else None, window)

    def test_cannot_peek_future_higher_bar(self):
        # Strictly rising prices: a signal that would BUY iff it could see the
        # NEXT (higher) candle. Since the engine never passes the future bar,
        # the condition can never fire -> zero trades.
        candles = [candle_from_close(c) for c in [10, 20, 30, 40, 50]]

        def future_peeker(window):
            cur_idx = len(window) - 1
            nxt = cur_idx + 1
            if nxt < len(window) and window[nxt]["close"] > window[cur_idx]["close"]:
                return "BUY"
            return "HOLD"

        res = backtest(candles, future_peeker)
        self.assertEqual(res["num_trades"], 0)
        self.assertAlmostEqual(res["total_return_pct"], 0.0, delta=1e-9)


class TestBacktestExecutionAtClose(unittest.TestCase):
    def test_executes_at_current_close(self):
        closes = [50, 60, 70, 80]
        candles = [candle_from_close(c) for c in closes]
        sig = scripted({2: "BUY", 3: "SELL"})
        res = backtest(candles, sig)
        self.assertEqual(res["trades"][0]["entry_index"], 2)
        self.assertAlmostEqual(res["trades"][0]["entry_price"], 70, delta=1e-9)


class TestBacktestOnePosition(unittest.TestCase):
    def test_repeated_buys_and_premature_sells_ignored(self):
        closes = [100, 100, 100, 110]
        candles = [candle_from_close(c) for c in closes]
        # SELL while flat (idx0) ignored; repeated BUY while long (idx1,2)
        # opens no extra trade; single SELL closes the one position.
        sig = scripted({0: "SELL", 1: "BUY", 2: "BUY", 3: "SELL"})
        res = backtest(candles, sig)
        self.assertEqual(res["num_trades"], 1)
        self.assertEqual(res["trades"][0]["entry_index"], 1)
        self.assertEqual(res["trades"][0]["exit_index"], 3)


class TestBacktestMaxDrawdown(unittest.TestCase):
    def test_up_then_down_drawdown(self):
        # buy & hold; equity tracks price: 1000,1200,1500,900,1100
        closes = [100, 120, 150, 90, 110]
        candles = [candle_from_close(c) for c in closes]
        sig = scripted({0: "BUY"})  # buy once, hold forever
        res = backtest(candles, sig)
        # peak 1500 -> trough 900 => 40% drawdown, independent of recovery
        self.assertAlmostEqual(res["max_drawdown_pct"], 40.0, delta=1e-9)


class TestBacktestWinRate(unittest.TestCase):
    def test_mixed_wins_and_losses(self):
        closes = [100, 110, 100, 90]
        candles = [candle_from_close(c) for c in closes]
        sig = scripted({0: "BUY", 1: "SELL", 2: "BUY", 3: "SELL"})
        res = backtest(candles, sig)
        self.assertEqual(res["num_trades"], 2)
        self.assertAlmostEqual(res["win_rate"], 0.5, delta=1e-9)

    def test_zero_trades_win_rate_zero(self):
        candles = [candle_from_close(c) for c in [100, 110]]
        res = backtest(candles, scripted({}))
        self.assertEqual(res["num_trades"], 0)
        self.assertEqual(res["win_rate"], 0.0)


# ===========================================================================
# PART D -- EDGE CASES
# ===========================================================================
class TestEdgeCases(unittest.TestCase):
    def test_empty_backtest(self):
        res = backtest([], scripted({}))
        self.assertEqual(res["trades"], [])
        self.assertEqual(res["num_trades"], 0)
        self.assertEqual(res["win_rate"], 0.0)
        self.assertEqual(res["total_return_pct"], 0.0)
        self.assertEqual(res["max_drawdown_pct"], 0.0)

    def test_all_indicators_none_on_subperiod(self):
        small_vals = [1, 2]
        small_candles = [C(0, 1, 0, 1, 1), C(0, 2, 1, 2, 1)]
        self.assertIsNone(S.sma(small_vals, 5))
        self.assertIsNone(S.ema(small_vals, 5))
        self.assertIsNone(S.rsi(small_vals, 14))
        self.assertIsNone(S.macd(small_vals))
        self.assertIsNone(S.bollinger(small_vals, period=20))
        self.assertIsNone(S.atr(small_candles, period=14))
        self.assertIsNone(S.stochastic(small_candles, k_period=14))
        self.assertIsNone(S.donchian(small_candles, period=20))

    def test_all_signals_hold_on_subperiod(self):
        small_candles = [C(0, 1, 0, 1, 1), C(0, 2, 1, 2, 1)]
        factories = [
            S.make_ma_crossover(2, 3),
            S.make_rsi_reversal(period=14),
            S.make_macd_crossover(),
            S.make_bollinger_breakout(period=20),
            S.make_volume_spike_breakout(N=3, volume_multiplier=2),
            S.make_donchian_breakout(period=20),
        ]
        for fn in factories:
            with self.subTest(fn=fn):
                self.assertEqual(fn(small_candles), "HOLD")
                self.assertEqual(fn([]), "HOLD")

    def test_backtest_never_raises_with_real_signal(self):
        # End-to-end smoke: run a real signal over a non-trivial series.
        closes = [10, 11, 12, 11, 10, 9, 8, 9, 11, 13, 15, 14, 16, 18, 20]
        candles = [candle_from_close(c, v=100 + i) for i, c in enumerate(closes)]
        for fn in (
            S.make_ma_crossover(2, 5),
            S.make_rsi_reversal(period=3),
            S.make_macd_crossover(fast=2, slow=3, signal=2),
            S.make_bollinger_breakout(period=3, num_std=1),
            S.make_donchian_breakout(period=3),
            S.make_volume_spike_breakout(N=2, volume_multiplier=1.0),
        ):
            with self.subTest(fn=fn):
                res = backtest(candles, fn, fee_rate=0.001)
                self.assertIn("total_return_pct", res)
                self.assertIsInstance(res["trades"], list)


if __name__ == "__main__":
    unittest.main()
