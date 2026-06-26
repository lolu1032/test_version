"""Binance public market-data layer (stdlib only, no API key needed).

Fetches klines (candles) and 24h tickers via the public REST API. Used by both
the backtest runner and the live 15-minute scanner. Everything here is read-only
public data, so no authentication is involved.
"""

import json
import time
import urllib.request
import urllib.error

BASE = "https://api.binance.com"

# Leveraged tokens and obvious non-spot oddities we never want to paper-trade.
_EXCLUDE_SUFFIXES = ("UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT")


def _get(path, params=None, retries=3, backoff=1.0):
    """GET a JSON endpoint with simple retry/backoff."""
    url = BASE + path
    if params:
        query = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}?{query}"
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "paper-bot/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.load(r)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            last_err = e
            time.sleep(backoff * (attempt + 1))
    raise RuntimeError(f"GET {path} failed after {retries} tries: {last_err}")


def get_klines(symbol, interval="15m", limit=500):
    """Return a chronological list of candle dicts (oldest first).

    Each candle: {open, high, low, close, volume} as floats. Matches the
    contract expected by signals.py / backtest.py.
    """
    raw = _get(
        "/api/v3/klines",
        {"symbol": symbol, "interval": interval, "limit": limit},
    )
    candles = []
    for k in raw:
        candles.append(
            {
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
            }
        )
    return candles


def get_usdt_symbols(top_n=30, min_quote_volume=5_000_000.0):
    """Return the most liquid USDT spot symbols by 24h quote volume.

    Filters to symbols quoted in USDT, drops leveraged tokens, and keeps only
    those above a liquidity floor. Sorted high->low volume, capped at top_n.
    """
    tickers = _get("/api/v3/ticker/24hr")
    rows = []
    for t in tickers:
        sym = t.get("symbol", "")
        if not sym.endswith("USDT"):
            continue
        if sym.endswith(_EXCLUDE_SUFFIXES):
            continue
        try:
            qv = float(t.get("quoteVolume", 0.0))
        except (TypeError, ValueError):
            continue
        if qv < min_quote_volume:
            continue
        rows.append((sym, qv))
    rows.sort(key=lambda x: x[1], reverse=True)
    return [sym for sym, _ in rows[:top_n]]
