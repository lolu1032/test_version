"""Binance public market-data layer (stdlib only, no API key needed).

Fetches klines (candles) and 24h tickers via the public REST API. Used by both
the backtest runner and the live 15-minute scanner. Everything here is read-only
public data, so no authentication is involved.
"""

import json
import os
import time
import urllib.request
import urllib.error

# data-api.binance.vision is Binance's public market-data domain: same /api/v3/*
# routes, no API key, and (unlike api.binance.com) NOT geo-blocked -- so it works
# from US-based CI runners like GitHub Actions, which otherwise get HTTP 451.
BASE = os.getenv("BINANCE_BASE", "https://data-api.binance.vision")

# Leveraged tokens and obvious non-spot oddities we never want to paper-trade.
_EXCLUDE_SUFFIXES = ("UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT")

# Quote assets treated as ~1 USDT for converting non-USDT pairs into USDT terms.
_STABLE_QUOTES = {"USDT", "USDC", "FDUSD", "TUSD", "DAI", "USDP", "BUSD"}


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


def get_all_coins(min_usdt_volume=0.0):
    """Return (almost) every tradeable spot COIN, deduped by base asset.

    Scans all spot TRADING pairs across every quote currency (USDT, BTC, ETH,
    ...), converts each pair's quote volume + price into USDT terms, and keeps
    the single most-liquid pair per base coin. So "all coins" stays coherent --
    one entry per coin (not the same coin five times via five quote markets),
    priced in USDT so the paper ledger has one currency.

    Returns a list of dicts: {symbol, base, quote, usdt_rate, usdt_volume},
    sorted by USDT volume (high first). usdt_rate converts the pair's native
    price into USDT (1.0 for stable-quoted pairs).
    """
    tickers = _get("/api/v3/ticker/24hr")
    info = _get("/api/v3/exchangeInfo")

    price = {}
    qvol = {}
    for t in tickers:
        sym = t.get("symbol", "")
        try:
            price[sym] = float(t.get("lastPrice", 0) or 0)
            qvol[sym] = float(t.get("quoteVolume", 0) or 0)
        except (TypeError, ValueError):
            continue

    def quote_to_usdt(quote):
        if quote in _STABLE_QUOTES:
            return 1.0
        p = price.get(quote + "USDT")
        return p if p else None

    best = {}  # base -> (usdt_volume, symbol, quote, usdt_rate)
    for s in info.get("symbols", []):
        if s.get("status") != "TRADING" or not s.get("isSpotTradingAllowed"):
            continue
        sym = s["symbol"]
        if sym.endswith(_EXCLUDE_SUFFIXES):
            continue
        base, quote = s["baseAsset"], s["quoteAsset"]
        rate = quote_to_usdt(quote)
        if not rate or sym not in price or price[sym] <= 0:
            continue
        usdt_vol = qvol.get(sym, 0.0) * rate
        if usdt_vol < min_usdt_volume:
            continue
        if base not in best or usdt_vol > best[base][0]:
            best[base] = (usdt_vol, sym, quote, rate)

    coins = [
        {"symbol": sym, "base": base, "quote": quote,
         "usdt_rate": rate, "usdt_volume": vol}
        for base, (vol, sym, quote, rate) in best.items()
    ]
    coins.sort(key=lambda c: c["usdt_volume"], reverse=True)
    return coins


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
