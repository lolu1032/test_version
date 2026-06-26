"""Technical indicators and trading signals for a crypto paper-trading bot.

Strategy: FULL-SERIES FUNCTIONAL.
- Internal `_*_series` helpers build the ENTIRE indicator series as plain lists.
- Public scalar indicators return `series[-1]` (or a tuple of series tails).
- `ema` is the exception: it returns the whole SERIES (per the locked contract).
- Signals index `[-1]` and `[-2]` of the relevant series to detect crosses,
  with no re-slicing, guarding for None / short series -> 'HOLD'.

LOCKED CONVENTIONS:
- Candle = dict with keys open/high/low/close/volume. Lists oldest-first.
- INSUFFICIENT DATA: every indicator returns None; every signal returns 'HOLD'.
- Pure, side-effect-free functions only. Standard library only.
"""

import statistics


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _closes(candles):
    return [c["close"] for c in candles]


# ---------------------------------------------------------------------------
# PART A -- INDICATORS (full-series helpers + public scalar/tuple/series API)
# ---------------------------------------------------------------------------
def _sma_series(values, period):
    """Rolling simple moving average; one value per window starting at index
    `period-1`. Returns None when there are fewer than `period` values."""
    if period <= 0 or len(values) < period:
        return None
    out = []
    for i in range(period - 1, len(values)):
        window = values[i - period + 1 : i + 1]
        out.append(sum(window) / period)
    return out


def sma(values, period):
    s = _sma_series(values, period)
    return None if s is None else s[-1]


def ema(values, period):
    """Exponential moving average SERIES (locked contract).

    k = 2/(period+1); seed = mean(values[:period]) sits at input index
    period-1; out[0] == seed; out[i] = values[period-1+i]*k + out[i-1]*(1-k).
    Returns None when len(values) < period.
    """
    if period <= 0 or len(values) < period:
        return None
    k = 2 / (period + 1)
    seed = sum(values[:period]) / period
    out = [seed]
    for i in range(period, len(values)):
        out.append(values[i] * k + out[-1] * (1 - k))
    return out


def _rsi_series(closes, period=14):
    """Wilder-smoothed RSI series. First value sits at close index `period`.
    Anchored at the series start so rsi(closes[:-1]) == series[-2]. Returns
    None when len(closes) < period+1 (not enough deltas to seed)."""
    if period <= 0 or len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    def _rsi(ag, al):
        if al == 0:
            return 100.0
        rs = ag / al
        return 100 - 100 / (1 + rs)

    out = [_rsi(avg_gain, avg_loss)]
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        out.append(_rsi(avg_gain, avg_loss))
    return out


def rsi(closes, period=14):
    s = _rsi_series(closes, period)
    return None if s is None else s[-1]


def _macd_series(closes, fast=12, slow=26, signal=9):
    """Returns (macd_line, signal_line, hist) as aligned lists.

    macd_line is defined for absolute input index idx in [slow-1 .. end] as
    ema_fast_at(idx) - ema_slow_at(idx). signal_line = ema(macd_line, signal).
    hist[j] = macd_line[offset+j] - signal_line[j], offset = signal-1.
    Returns None when len(closes) < slow+signal-1.
    """
    if fast <= 0 or slow <= 0 or signal <= 0 or fast >= slow:
        return None
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    if ema_fast is None or ema_slow is None:
        return None
    n = len(closes)
    macd_line = []
    for idx in range(slow - 1, n):
        f = ema_fast[idx - (fast - 1)]
        s = ema_slow[idx - (slow - 1)]
        macd_line.append(f - s)
    signal_line = ema(macd_line, signal)
    if signal_line is None:
        return None
    offset = len(macd_line) - len(signal_line)  # == signal - 1
    hist = [macd_line[offset + j] - signal_line[j] for j in range(len(signal_line))]
    return macd_line, signal_line, hist


def macd(closes, fast=12, slow=26, signal=9):
    res = _macd_series(closes, fast, slow, signal)
    if res is None:
        return None
    macd_line, signal_line, hist = res
    return (macd_line[-1], signal_line[-1], hist[-1])


def _bollinger_series(closes, period=20, num_std=2):
    """Per-window (upper, mid, lower) using POPULATION std (statistics.pstdev).
    Returns None when len(closes) < period."""
    if period <= 0 or len(closes) < period:
        return None
    out = []
    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1 : i + 1]
        mid = sum(window) / period
        std = statistics.pstdev(window)
        out.append((mid + num_std * std, mid, mid - num_std * std))
    return out


def bollinger(closes, period=20, num_std=2):
    s = _bollinger_series(closes, period, num_std)
    return None if s is None else s[-1]


def _tr_series(candles):
    trs = []
    for i, c in enumerate(candles):
        if i == 0:
            trs.append(c["high"] - c["low"])
        else:
            pc = candles[i - 1]["close"]
            trs.append(
                max(c["high"] - c["low"], abs(c["high"] - pc), abs(c["low"] - pc))
            )
    return trs


def _atr_series(candles, period=14):
    """Wilder-smoothed ATR series. TR[0] = high0-low0. seed = mean(TR[:period])
    sits at index period-1. Returns None when len(candles) < period."""
    if period <= 0 or len(candles) < period:
        return None
    trs = _tr_series(candles)
    seed = sum(trs[:period]) / period
    out = [seed]
    for i in range(period, len(trs)):
        out.append((out[-1] * (period - 1) + trs[i]) / period)
    return out


def atr(candles, period=14):
    s = _atr_series(candles, period)
    return None if s is None else s[-1]


def _stoch_k_series(candles, k_period=14):
    """%K per window. range==0 -> %K=0.0 (locked). None if len < k_period."""
    if k_period <= 0 or len(candles) < k_period:
        return None
    out = []
    for i in range(k_period - 1, len(candles)):
        window = candles[i - k_period + 1 : i + 1]
        hh = max(c["high"] for c in window)
        ll = min(c["low"] for c in window)
        close = candles[i]["close"]
        if hh - ll == 0:
            out.append(0.0)
        else:
            out.append(100 * (close - ll) / (hh - ll))
    return out


def stochastic(candles, k_period=14, d_period=3):
    """Returns (%K, %D). %D = SMA(d_period) of the %K series. Returns None when
    len(candles) < k_period + d_period - 1."""
    if k_period <= 0 or d_period <= 0 or len(candles) < k_period + d_period - 1:
        return None
    k_series = _stoch_k_series(candles, k_period)
    if k_series is None:
        return None
    d_series = _sma_series(k_series, d_period)
    if d_series is None:
        return None
    return (k_series[-1], d_series[-1])


def donchian(candles, period=20):
    """Returns (upper=highest high, lower=lowest low) over the last `period`
    candles. Returns None when len(candles) < period."""
    if period <= 0 or len(candles) < period:
        return None
    window = candles[-period:]
    upper = max(c["high"] for c in window)
    lower = min(c["low"] for c in window)
    return (upper, lower)


# ---------------------------------------------------------------------------
# PART B -- SIGNALS (factory closures returning fn(window)->'BUY'/'SELL'/'HOLD')
# ---------------------------------------------------------------------------
def make_ma_crossover(short, long):
    """Golden cross (short crosses above long) -> BUY; death cross -> SELL."""

    def signal(window):
        closes = _closes(window)
        s = _sma_series(closes, short)
        l = _sma_series(closes, long)
        if s is None or l is None or len(s) < 2 or len(l) < 2:
            return "HOLD"
        s_t, s_p = s[-1], s[-2]
        l_t, l_p = l[-1], l[-2]
        if s_t > l_t and s_p <= l_p:
            return "BUY"
        if s_t < l_t and s_p >= l_p:
            return "SELL"
        return "HOLD"

    return signal


def make_rsi_reversal(period=14, low=30, high=70):
    """BUY on upward cross through `low`; SELL on downward cross through `high`.
    Merely staying below `low` (both prev and cur < low) -> HOLD."""

    def signal(window):
        closes = _closes(window)
        r = _rsi_series(closes, period)
        if r is None or len(r) < 2:
            return "HOLD"
        prev, cur = r[-2], r[-1]
        if prev < low and cur >= low:
            return "BUY"
        if prev > high and cur <= high:
            return "SELL"
        return "HOLD"

    return signal


def make_macd_crossover(fast=12, slow=26, signal=9):
    """BUY when histogram crosses up through 0; SELL when it crosses down."""

    def sig(window):
        closes = _closes(window)
        res = _macd_series(closes, fast, slow, signal)
        if res is None:
            return "HOLD"
        _, _, hist = res
        if len(hist) < 2:
            return "HOLD"
        prev, cur = hist[-2], hist[-1]
        if prev <= 0 and cur > 0:
            return "BUY"
        if prev >= 0 and cur < 0:
            return "SELL"
        return "HOLD"

    return sig


def make_bollinger_breakout(period=20, num_std=2):
    """BUY when close crosses above the upper band; SELL below the lower band."""

    def signal(window):
        closes = _closes(window)
        b = _bollinger_series(closes, period, num_std)
        if b is None or len(b) < 2:
            return "HOLD"
        upper_t, _, lower_t = b[-1]
        upper_p, _, lower_p = b[-2]
        close_t = closes[-1]
        close_p = closes[-2]
        if close_p <= upper_p and close_t > upper_t:
            return "BUY"
        if close_p >= lower_p and close_t < lower_t:
            return "SELL"
        return "HOLD"

    return signal


def make_volume_spike_breakout(N, volume_multiplier):
    """BUY iff current volume > multiplier * mean(prior N volumes) AND close is
    up vs the prior close. NEVER emits SELL (BUY-only by definition)."""

    def signal(window):
        if N <= 0 or len(window) < N + 1:
            return "HOLD"
        prior = window[-(N + 1) : -1]
        avg_vol = sum(c["volume"] for c in prior) / N
        vol_t = window[-1]["volume"]
        close_t = window[-1]["close"]
        close_p = window[-2]["close"]
        if vol_t > volume_multiplier * avg_vol and close_t > close_p:
            return "BUY"
        return "HOLD"

    return signal


def make_donchian_breakout(period=20):
    """Level breakout vs the channel of the `period` candles BEFORE the current
    one. BUY iff close > prior-period upper; SELL iff close < prior-period
    lower."""

    def signal(window):
        if period <= 0 or len(window) < period + 1:
            return "HOLD"
        prior = window[-(period + 1) : -1]
        prior_upper = max(c["high"] for c in prior)
        prior_lower = min(c["low"] for c in prior)
        close_t = window[-1]["close"]
        if close_t > prior_upper:
            return "BUY"
        if close_t < prior_lower:
            return "SELL"
        return "HOLD"

    return signal
