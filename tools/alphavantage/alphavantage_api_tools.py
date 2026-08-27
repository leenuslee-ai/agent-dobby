"""Alpha Vantage API tools exposed as LangChain/MCP-compatible tools.

Set ALPHAVANTAGE_API_KEY in .env.
Free tier: 25 requests/day. Premium tiers remove that limit.

Covered APIs:
  Price      : quote, daily OHLCV, intraday OHLCV
  Indicators : SMA, EMA, RSI, MACD, Bollinger Bands, VWAP, ADX, Stochastic
  Fundamental: company overview, earnings, income statement
"""

import os
import requests
from functools import lru_cache
from langchain_core.tools import tool
from config import ALPHAVANTAGE_API_KEY  # added to config.py


_BASE = "https://www.alphavantage.co/query"


def _av(params: dict) -> dict:
    """Execute a GET request against Alpha Vantage; return parsed JSON."""
    params["apikey"] = ALPHAVANTAGE_API_KEY
    resp = requests.get(_BASE, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if "Note" in data:
        return {"error": "API rate limit hit. Upgrade plan or wait 1 min."}
    if "Information" in data:
        return {"error": data["Information"]}
    return data


def _fmt_series(series: dict, n: int) -> str:
    """Format the last n rows of a time-series dict into a readable string."""
    rows = list(series.items())[:n]
    lines = []
    for date, vals in rows:
        parts = ", ".join(f"{k.split('. ')[-1]}={v}" for k, v in vals.items())
        lines.append(f"  {date}: {parts}")
    return "\n".join(lines)


def _first_n_indicator(data: dict, key: str, n: int) -> str:
    series = data.get("Technical Analysis: " + key) or data.get(f"Technical Analysis: {key}")
    if series is None:
        # try to find any key that starts with "Technical Analysis"
        series = next((v for k, v in data.items() if k.startswith("Technical Analysis")), None)
    if not series:
        return str(data)
    rows = list(series.items())[:n]
    lines = [f"  {date}: {', '.join(f'{k}={v}' for k,v in vals.items())}" for date, vals in rows]
    return "\n".join(lines)


# ── Price tools ───────────────────────────────────────────────────────────────

@tool
def av_quote(ticker: str) -> str:
    """Get the latest real-time quote for a ticker from Alpha Vantage.
    Returns price, open, high, low, volume, previous close, change%."""
    data = _av({"function": "GLOBAL_QUOTE", "symbol": ticker.upper()})
    if "error" in data:
        return data["error"]
    q = data.get("Global Quote", {})
    if not q:
        return f"No quote data for {ticker}."
    return (
        f"{ticker}: price={q.get('05. price')}, open={q.get('02. open')}, "
        f"high={q.get('03. high')}, low={q.get('04. low')}, "
        f"volume={q.get('06. volume')}, prev_close={q.get('08. previous close')}, "
        f"change={q.get('09. change')}, change%={q.get('10. change percent')}"
    )


@tool
def av_daily(ticker: str, rows: int = 10) -> str:
    """Get the last N days of daily OHLCV data for a ticker from Alpha Vantage.

    Args:
        ticker: Stock symbol
        rows:   Number of trading days to return (default 10)
    """
    data = _av({"function": "TIME_SERIES_DAILY", "symbol": ticker.upper(), "outputsize": "compact"})
    if "error" in data:
        return data["error"]
    series = data.get("Time Series (Daily)", {})
    return f"{ticker} daily OHLCV (last {rows} days):\n" + _fmt_series(series, rows)


@tool
def av_intraday(ticker: str, interval: str = "5min", rows: int = 10) -> str:
    """Get intraday OHLCV bars for a ticker from Alpha Vantage.

    Args:
        ticker:   Stock symbol
        interval: Bar size — one of '1min','5min','15min','30min','60min'
        rows:     Number of bars to return (default 10)
    """
    data = _av({
        "function": "TIME_SERIES_INTRADAY",
        "symbol": ticker.upper(),
        "interval": interval,
        "outputsize": "compact",
    })
    if "error" in data:
        return data["error"]
    key = f"Time Series ({interval})"
    series = data.get(key, {})
    return f"{ticker} intraday {interval} (last {rows} bars):\n" + _fmt_series(series, rows)


# ── Technical indicator tools ─────────────────────────────────────────────────

@tool
def av_sma(ticker: str, period: int = 20, interval: str = "daily") -> str:
    """Get Simple Moving Average (SMA) for a ticker.

    Args:
        ticker:   Stock symbol
        period:   Look-back window (default 20)
        interval: 'daily', 'weekly', or intraday e.g. '5min'
    """
    data = _av({
        "function": "SMA", "symbol": ticker.upper(),
        "interval": interval, "time_period": period, "series_type": "close",
    })
    if "error" in data:
        return data["error"]
    return f"{ticker} SMA({period}) [{interval}] — last 5:\n" + _first_n_indicator(data, "SMA", 5)


@tool
def av_ema(ticker: str, period: int = 20, interval: str = "daily") -> str:
    """Get Exponential Moving Average (EMA) for a ticker.

    Args:
        ticker:   Stock symbol
        period:   Look-back window (default 20)
        interval: 'daily', 'weekly', or intraday e.g. '5min'
    """
    data = _av({
        "function": "EMA", "symbol": ticker.upper(),
        "interval": interval, "time_period": period, "series_type": "close",
    })
    if "error" in data:
        return data["error"]
    return f"{ticker} EMA({period}) [{interval}] — last 5:\n" + _first_n_indicator(data, "EMA", 5)


@tool
def av_rsi(ticker: str, period: int = 14, interval: str = "daily") -> str:
    """Get Relative Strength Index (RSI) for a ticker.
    RSI > 70 = overbought, RSI < 30 = oversold.

    Args:
        ticker:   Stock symbol
        period:   Look-back window (default 14)
        interval: 'daily', 'weekly', or intraday e.g. '5min'
    """
    data = _av({
        "function": "RSI", "symbol": ticker.upper(),
        "interval": interval, "time_period": period, "series_type": "close",
    })
    if "error" in data:
        return data["error"]
    return f"{ticker} RSI({period}) [{interval}] — last 5:\n" + _first_n_indicator(data, "RSI", 5)


@tool
def av_macd(ticker: str, interval: str = "daily") -> str:
    """Get MACD (Moving Average Convergence Divergence) for a ticker.
    Uses standard 12/26/9 settings. Returns MACD line, signal, and histogram.

    Args:
        ticker:   Stock symbol
        interval: 'daily', 'weekly', or intraday e.g. '5min'
    """
    data = _av({
        "function": "MACD", "symbol": ticker.upper(),
        "interval": interval, "series_type": "close",
        "fastperiod": 12, "slowperiod": 26, "signalperiod": 9,
    })
    if "error" in data:
        return data["error"]
    return f"{ticker} MACD(12,26,9) [{interval}] — last 5:\n" + _first_n_indicator(data, "MACD", 5)


@tool
def av_bbands(ticker: str, period: int = 20, interval: str = "daily") -> str:
    """Get Bollinger Bands for a ticker (upper, middle, lower bands).

    Args:
        ticker:   Stock symbol
        period:   Look-back window (default 20)
        interval: 'daily', 'weekly', or intraday e.g. '5min'
    """
    data = _av({
        "function": "BBANDS", "symbol": ticker.upper(),
        "interval": interval, "time_period": period, "series_type": "close",
        "nbdevup": 2, "nbdevdn": 2,
    })
    if "error" in data:
        return data["error"]
    return f"{ticker} BBands({period}) [{interval}] — last 5:\n" + _first_n_indicator(data, "BBANDS", 5)


@tool
def av_vwap(ticker: str, interval: str = "5min") -> str:
    """Get Volume Weighted Average Price (VWAP) for a ticker.
    Only meaningful on intraday intervals.

    Args:
        ticker:   Stock symbol
        interval: Intraday bar size — '1min','5min','15min','30min','60min'
    """
    data = _av({"function": "VWAP", "symbol": ticker.upper(), "interval": interval})
    if "error" in data:
        return data["error"]
    return f"{ticker} VWAP [{interval}] — last 5:\n" + _first_n_indicator(data, "VWAP", 5)


@tool
def av_adx(ticker: str, period: int = 14, interval: str = "daily") -> str:
    """Get Average Directional Index (ADX) for a ticker.
    ADX > 25 indicates a strong trend; < 20 suggests ranging market.

    Args:
        ticker:   Stock symbol
        period:   Look-back window (default 14)
        interval: 'daily', 'weekly', or intraday e.g. '5min'
    """
    data = _av({
        "function": "ADX", "symbol": ticker.upper(),
        "interval": interval, "time_period": period,
    })
    if "error" in data:
        return data["error"]
    return f"{ticker} ADX({period}) [{interval}] — last 5:\n" + _first_n_indicator(data, "ADX", 5)


@tool
def av_stoch(ticker: str, interval: str = "daily") -> str:
    """Get Stochastic Oscillator (%K, %D) for a ticker.
    Values > 80 = overbought, < 20 = oversold.

    Args:
        ticker:   Stock symbol
        interval: 'daily', 'weekly', or intraday e.g. '5min'
    """
    data = _av({
        "function": "STOCH", "symbol": ticker.upper(), "interval": interval,
        "fastkperiod": 5, "slowkperiod": 3, "slowdperiod": 3,
    })
    if "error" in data:
        return data["error"]
    return f"{ticker} Stochastic [{interval}] — last 5:\n" + _first_n_indicator(data, "STOCH", 5)


# ── Fundamental tools ─────────────────────────────────────────────────────────

@tool
def av_company_overview(ticker: str) -> str:
    """Get fundamental company overview: sector, P/E, EPS, market cap, 52w range, etc."""
    data = _av({"function": "OVERVIEW", "symbol": ticker.upper()})
    if "error" in data:
        return data["error"]
    if not data.get("Symbol"):
        return f"No overview data for {ticker}."
    fields = [
        "Name", "Sector", "Industry", "MarketCapitalization",
        "PERatio", "ForwardPE", "EPS", "DividendYield",
        "52WeekHigh", "52WeekLow", "50DayMovingAverage", "200DayMovingAverage",
        "AnalystTargetPrice", "Beta",
    ]
    lines = [f"  {f}: {data.get(f, 'N/A')}" for f in fields]
    return f"{ticker} Overview:\n" + "\n".join(lines)


@tool
def av_earnings(ticker: str) -> str:
    """Get the last 4 quarters of earnings (EPS expected vs actual, surprise%) for a ticker."""
    data = _av({"function": "EARNINGS", "symbol": ticker.upper()})
    if "error" in data:
        return data["error"]
    quarterly = data.get("quarterlyEarnings", [])[:4]
    if not quarterly:
        return f"No earnings data for {ticker}."
    lines = []
    for q in quarterly:
        lines.append(
            f"  {q.get('fiscalDateEnding')}: "
            f"reported={q.get('reportedEPS')}, estimated={q.get('estimatedEPS')}, "
            f"surprise={q.get('surprise')}, surprise%={q.get('surprisePercentage')}"
        )
    return f"{ticker} Quarterly Earnings (last 4):\n" + "\n".join(lines)


# ── Exported tool list ────────────────────────────────────────────────────────

ALPHAVANTAGE_TOOLS = [
    av_quote,
    av_daily,
    av_intraday,
    av_sma,
    av_ema,
    av_rsi,
    av_macd,
    av_bbands,
    av_vwap,
    av_adx,
    av_stoch,
    av_company_overview,
    av_earnings,
]


if __name__ == "__main__":
    import time

    

    print(av_quote.invoke({"ticker": "AAPL"}))
    time.sleep(2)  # Pauses execution for exactly 2 seconds
    print(av_rsi.invoke({"ticker": "AAPL", "period": 14}))
    time.sleep(2)  # Pauses execution for exactly 2 seconds
    print(av_macd.invoke({"ticker": "AAPL"}))
    time.sleep(2)  # Pauses execution for exactly 2 seconds
    
    print(av_rsi.invoke({"ticker": "AAPL", "period": 20}))
