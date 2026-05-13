"""
Clawzd — Market Data Fetcher Tool.

Unified tool for fetching financial data from multiple sources:
  - crypto:  Binance public API (no auth required)
  - stock:   yahooquery Ticker
  - forex:   Dukascopy binary LZMA tick data

Returns JSON-serializable OHLCV data ready for analysis or charting.
"""
import logging
import datetime
from typing import Dict, Optional

import pandas as pd
import requests

logger = logging.getLogger("clawzd.tools_market")


# ---------------------------------------------------------------------------
#  Binance — Crypto OHLCV (public, no auth)
# ---------------------------------------------------------------------------

_BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"

_BINANCE_COLUMNS = [
    "timestamp", "open", "high", "low", "close", "volume",
    "close_time", "quote_vol", "trades",
    "taker_buy_base", "taker_buy_quote", "ignore",
]


def _fetch_crypto(symbol: str, interval: str = "1d",
                  limit: int = 30) -> Dict:
    """Fetch crypto OHLCV from Binance public API."""
    # Normalize symbol (BTCUSDT, BTC/USDT, BTC-USDT → BTCUSDT)
    sym = symbol.upper().replace("/", "").replace("-", "")
    params = {"symbol": sym, "interval": interval, "limit": min(limit, 1000)}

    try:
        r = requests.get(_BINANCE_KLINES_URL, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return {"error": f"Binance API error: {e}"}

    if not data or not isinstance(data, list):
        return {"error": f"No data returned for {sym}"}

    df = pd.DataFrame(data, columns=_BINANCE_COLUMNS)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = df[c].astype(float)

    # Return clean OHLCV
    out = df[["timestamp", "open", "high", "low", "close", "volume"]].copy()
    out["timestamp"] = out["timestamp"].dt.strftime("%Y-%m-%d %H:%M")

    return {
        "source": "binance",
        "symbol": sym,
        "interval": interval,
        "count": len(out),
        "columns": ["timestamp", "open", "high", "low", "close", "volume"],
        "data": out.values.tolist(),
    }


# ---------------------------------------------------------------------------
#  Yahoo — Stock OHLCV via yahooquery
# ---------------------------------------------------------------------------

def _fetch_stock(symbol: str, period: str = "1mo",
                 interval: str = "1d") -> Dict:
    """Fetch stock OHLCV from Yahoo Finance via yahooquery."""
    try:
        from yahooquery import Ticker
    except ImportError:
        return {"error": "yahooquery is not installed. Run: pip install yahooquery"}

    try:
        t = Ticker(symbol, formatted=True)
        df = t.history(period=period, interval=interval)
    except Exception as e:
        return {"error": f"yahooquery error: {e}"}

    if isinstance(df, str) or df is None or (hasattr(df, 'empty') and df.empty):
        return {"error": f"No data returned for {symbol}"}

    df = df.reset_index()

    # Normalize column names (yahooquery uses lowercase)
    col_map = {}
    for c in df.columns:
        col_map[c] = c.lower()
    df = df.rename(columns=col_map)

    # Find date column
    date_col = None
    for candidate in ["date", "index", "datetime"]:
        if candidate in df.columns:
            date_col = candidate
            break

    if date_col is None:
        # Fallback: use the first datetime-like column
        for c in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[c]):
                date_col = c
                break

    if date_col:
        df[date_col] = pd.to_datetime(df[date_col]).dt.strftime("%Y-%m-%d")

    # Select OHLCV columns
    keep = []
    if date_col:
        keep.append(date_col)
    for c in ["open", "high", "low", "close", "volume", "adjclose"]:
        if c in df.columns:
            keep.append(c)

    if not keep:
        keep = list(df.columns)

    out = df[keep]

    return {
        "source": "yahooquery",
        "symbol": symbol.upper(),
        "period": period,
        "interval": interval,
        "count": len(out),
        "columns": list(out.columns),
        "data": out.values.tolist(),
    }


# ---------------------------------------------------------------------------
#  Dukascopy — Forex tick data (LZMA binary)
# ---------------------------------------------------------------------------

def _fetch_forex(symbol: str, year: int = 0, month: int = 0,
                 day: int = 0, hour: int = 12) -> Dict:
    """Fetch forex tick data from Dukascopy datafeed."""
    import lzma
    import struct

    # Default to yesterday if no date given
    if year == 0:
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        # Skip weekends
        while yesterday.weekday() >= 5:
            yesterday -= datetime.timedelta(days=1)
        year = yesterday.year
        month = yesterday.month - 1  # Dukascopy uses 0-indexed months
        day = yesterday.day

    sym = symbol.upper().replace("/", "")
    url = (
        f"https://datafeed.dukascopy.com/datafeed/{sym}/"
        f"{year}/{month:02d}/{day:02d}/{hour:02d}h_ticks.bi5"
    )

    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
    except Exception as e:
        return {"error": f"Dukascopy fetch error: {e}"}

    if len(r.content) == 0:
        return {
            "source": "dukascopy",
            "symbol": sym,
            "info": f"No data for {year}/{month:02d}/{day:02d} {hour:02d}h (market closed?)",
            "count": 0,
            "data": [],
        }

    try:
        raw = lzma.decompress(r.content)
    except Exception:
        return {"error": "Failed to decompress LZMA data (corrupt file?)"}

    records = []
    for i in range(0, len(raw), 20):
        chunk = raw[i:i + 20]
        if len(chunk) == 20:
            records.append(struct.unpack(">LLLff", chunk))

    columns = ["time_ms", "ask", "bid", "ask_volume", "bid_volume"]
    df = pd.DataFrame(records, columns=columns)

    # Adjust pip values (5-decimal pairs)
    pip_divisor = 100000 if "JPY" not in sym else 1000
    df["ask"] = df["ask"] / pip_divisor
    df["bid"] = df["bid"] / pip_divisor

    return {
        "source": "dukascopy",
        "symbol": sym,
        "date": f"{year}-{month + 1:02d}-{day:02d} {hour:02d}:00",
        "count": len(df),
        "columns": columns,
        "data": df.values.tolist(),
    }


# ---------------------------------------------------------------------------
#  Unified entry point
# ---------------------------------------------------------------------------

_SOURCE_MAP = {
    "crypto": _fetch_crypto,
    "binance": _fetch_crypto,
    "stock": _fetch_stock,
    "stocks": _fetch_stock,
    "yahoo": _fetch_stock,
    "yahooquery": _fetch_stock,
    "forex": _fetch_forex,
    "fx": _fetch_forex,
    "dukascopy": _fetch_forex,
}


def fetch_market_data(params: dict) -> dict:
    """Unified market data fetcher.

    Params:
        symbol (str):   Ticker symbol, e.g. "BTCUSDT", "AAPL", "EURUSD"
        source (str):   "crypto" | "stock" | "forex"  (auto-detected if omitted)
        interval (str): Candle interval, e.g. "1d", "1h", "15m" (default: "1d")
        limit (int):    Number of candles (crypto only, default: 30)
        period (str):   History period (stock only, default: "1mo")

    Returns:
        dict with source, symbol, count, columns, data (list of lists)
    """
    symbol = params.get("symbol", "")
    if not symbol:
        return {"error": "symbol is required (e.g. 'BTCUSDT', 'AAPL', 'EURUSD')"}

    source = params.get("source", "").lower()

    # Auto-detect source from symbol if not specified
    if not source:
        sym_upper = symbol.upper()
        # Common crypto suffixes
        if any(sym_upper.endswith(s) for s in ("USDT", "BUSD", "BTC", "ETH", "BNB")):
            source = "crypto"
        # Common forex pairs
        elif len(sym_upper.replace("/", "")) == 6 and all(
            c.isalpha() for c in sym_upper.replace("/", "")
        ):
            # Could be forex (EURUSD) or stock (GOOGL)
            forex_currencies = {"EUR", "USD", "GBP", "JPY", "CHF", "AUD", "NZD", "CAD"}
            pair = sym_upper.replace("/", "")
            if pair[:3] in forex_currencies and pair[3:] in forex_currencies:
                source = "forex"
            else:
                source = "stock"
        else:
            source = "stock"

    fetcher = _SOURCE_MAP.get(source)
    if not fetcher:
        return {"error": f"Unknown source: {source}. Use: crypto, stock, forex"}

    logger.info("fetch_market_data: %s → %s (%s)", symbol, source, params)

    if source in ("crypto", "binance"):
        return fetcher(
            symbol,
            interval=params.get("interval", "1d"),
            limit=params.get("limit", 30),
        )
    elif source in ("stock", "stocks", "yahoo", "yahooquery"):
        return fetcher(
            symbol,
            period=params.get("period", "1mo"),
            interval=params.get("interval", "1d"),
        )
    elif source in ("forex", "fx", "dukascopy"):
        return fetcher(
            symbol,
            year=params.get("year", 0),
            month=params.get("month", 0),
            day=params.get("day", 0),
            hour=params.get("hour", 12),
        )

    return fetcher(symbol)
