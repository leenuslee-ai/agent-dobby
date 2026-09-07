"""Latest price fetching for live and simulation modes.

Live mode   : calls Alpha Vantage TIME_SERIES_INTRADAY (5-min bars) to get the
              most recent traded price during market hours.
Simulation  : reads the daily close for the given date straight from the CSV cache,
              so no extra API calls are needed during back-tests.
"""

from __future__ import annotations

import requests
import pandas as pd
from datetime import date
from pathlib import Path

from config import ALPHAVANTAGE_API_KEY

_CACHE_DIR = Path(__file__).parent / "cache"
_BASE_URL  = "https://www.alphavantage.co/query"


def get_latest_price(ticker: str, sim_date: date | None = None) -> float | None:
    """Return the most recent available price for *ticker*.

    Args:
        ticker:   Stock symbol (e.g. "SPY").
        sim_date: When set, returns the daily close for that date from the local
                  CSV cache instead of calling the live intraday API.
    """
    if sim_date is not None:
        return _daily_close_for_date(ticker, sim_date)
    return _fetch_intraday_latest(ticker)


# ── Simulation helper ─────────────────────────────────────────────────────────

def _daily_close_for_date(ticker: str, for_date: date) -> float | None:
    """Read the closing price on or before *for_date* from the cached CSV."""
    cache_file = _CACHE_DIR / f"{ticker}_daily.csv"
    if not cache_file.exists():
        print(f"  [intraday] Cache file not found for {ticker}: {cache_file}")
        return None
    try:
        df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
        df = df[df.index.date <= for_date]
        if df.empty:
            print(f"  [intraday] No data for {ticker} up to {for_date}")
            return None
        return float(df.iloc[-1]["close"])
    except Exception as exc:
        print(f"  [intraday] Error reading daily close for {ticker}: {exc}")
        return None


# ── Live helper ───────────────────────────────────────────────────────────────

def _fetch_intraday_latest(ticker: str) -> float | None:
    """Fetch the close of the most recent 5-min bar from Alpha Vantage."""
    try:
        resp = requests.get(_BASE_URL, params={
            "function":   "TIME_SERIES_INTRADAY",
            "symbol":     ticker.upper(),
            "interval":   "5min",
            "outputsize": "compact",
            "apikey":     ALPHAVANTAGE_API_KEY,
        }, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        series = data.get("Time Series (5min)", {})
        if not series:
            note = data.get("Note") or data.get("Information", "")
            print(f"  [intraday] No intraday data for {ticker}: {note[:100]}")
            return None

        latest_ts = max(series.keys())
        price = float(series[latest_ts]["4. close"])
        print(f"  [intraday] {ticker} latest 5-min close: ${price:.2f}  (bar={latest_ts})")
        return price

    except Exception as exc:
        print(f"  [intraday] Could not fetch intraday price for {ticker}: {exc}")
        return None
