"""Fetch and cache historical OHLCV + technical indicators from Alpha Vantage.

Data is cached as CSV in ./backtest_cache/ so you don't burn API calls on reruns.
Indicators are computed locally using the `ta` library (no extra API calls).

Usage:
    from tools.alphavantage.alphavantage_data import get_ohlcv_with_indicators
    df = get_ohlcv_with_indicators("NVDA", lookback_days=365)
"""

import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
import ta

from config import ALPHAVANTAGE_API_KEY

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)
_BASE = "https://www.alphavantage.co/query"


# ── Data fetching ─────────────────────────────────────────────────────────────

def _fetch_daily_full(ticker: str) -> pd.DataFrame:
    """Fetch full daily OHLCV history from Alpha Vantage (up to 20 years)."""
    cache_file = CACHE_DIR / f"{ticker}_daily.csv"

    # Use cache if less than 1 day old
    if cache_file.exists():
        age = datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)
        if age < timedelta(hours=23):
            print(f"  [cache] Loading {ticker} from {cache_file}")
            return pd.read_csv(cache_file, index_col=0, parse_dates=True)

    print(f"  [fetch] Downloading {ticker} full daily history from Alpha Vantage...")
    for attempt in range(3):
        try:
            resp = requests.get(_BASE, params={
                "function": "TIME_SERIES_DAILY",
                "symbol": ticker.upper(),
                "outputsize": "full",
                "apikey": ALPHAVANTAGE_API_KEY,
            }, timeout=120)
            break
        except requests.exceptions.ReadTimeout:
            if attempt == 2:
                raise RuntimeError(f"Alpha Vantage timed out after 3 attempts for {ticker}")
            print(f"  [fetch] Timeout, retrying ({attempt + 2}/3)...")
    resp.raise_for_status()
    data = resp.json()

    if "Note" in data:
        raise RuntimeError("Alpha Vantage rate limit hit. Wait 1 minute.")
    if "Information" in data:
        raise RuntimeError(data["Information"])

    series = data.get("Time Series (Daily)", {})
    if not series:
        raise RuntimeError(f"No data returned for {ticker}")

    df = pd.DataFrame.from_dict(series, orient="index")
    df.index = pd.to_datetime(df.index)
    df.sort_index(inplace=True)
    df.columns = ["open", "high", "low", "close", "volume"]
    df = df.astype(float)

    df.to_csv(cache_file)
    print(f"  [cache] Saved {len(df)} rows to {cache_file}")
    return df


# ── Indicator computation ─────────────────────────────────────────────────────

def _add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add common technical indicators using the `ta` library."""
    close = df["close"]
    high  = df["high"]
    low   = df["low"]
    vol   = df["volume"]

    # Trend
    df["sma_20"]  = ta.trend.sma_indicator(close, window=20)
    df["sma_50"]  = ta.trend.sma_indicator(close, window=50)
    df["sma_200"] = ta.trend.sma_indicator(close, window=200)
    df["ema_8"]   = ta.trend.ema_indicator(close, window=8)
    df["ema_12"]  = ta.trend.ema_indicator(close, window=12)
    df["ema_20"]  = ta.trend.ema_indicator(close, window=20)
    df["ema_21"]  = ta.trend.ema_indicator(close, window=21)
    df["ema_26"]  = ta.trend.ema_indicator(close, window=26)
    df["adx"]     = ta.trend.adx(high, low, close, window=14)

    # Momentum
    df["rsi"]          = ta.momentum.rsi(close, window=14)
    df["rsi_2"]        = ta.momentum.rsi(close, window=2)
    macd_obj           = ta.trend.MACD(close)
    df["macd"]         = macd_obj.macd()
    df["macd_signal"]  = macd_obj.macd_signal()
    df["macd_hist"]    = macd_obj.macd_diff()
    stoch              = ta.momentum.StochasticOscillator(high, low, close)
    df["stoch_k"]      = stoch.stoch()
    df["stoch_d"]      = stoch.stoch_signal()

    # Volatility
    bb                 = ta.volatility.BollingerBands(close, window=20)
    df["bb_upper"]     = bb.bollinger_hband()
    df["bb_middle"]    = bb.bollinger_mavg()
    df["bb_lower"]     = bb.bollinger_lband()
    df["bb_pct"]       = bb.bollinger_pband()   # 0=lower band, 1=upper band
    df["atr"]          = ta.volatility.average_true_range(high, low, close)

    # Volume
    df["obv"]        = ta.volume.on_balance_volume(close, vol)
    df["vol_sma_20"] = ta.trend.sma_indicator(vol, window=20)

    # Derived signals (True/False columns for easy setup evaluation)
    df["macd_crossover_up"]   = (df["macd"] > df["macd_signal"]) & (df["macd"].shift(1) <= df["macd_signal"].shift(1))
    df["macd_crossover_down"] = (df["macd"] < df["macd_signal"]) & (df["macd"].shift(1) >= df["macd_signal"].shift(1))
    df["price_above_sma50"]   = close > df["sma_50"]
    df["price_above_sma200"]  = close > df["sma_200"]
    df["golden_cross"]        = (df["sma_50"] > df["sma_200"]) & (df["sma_50"].shift(1) <= df["sma_200"].shift(1))
    df["death_cross"]         = (df["sma_50"] < df["sma_200"]) & (df["sma_50"].shift(1) >= df["sma_200"].shift(1))

    # ── EMA crossover signals (generated for all meaningful fast/slow pairs) ──
    _ema_pairs = [(8, 21), (8, 20), (12, 26)]
    for fast, slow in _ema_pairs:
        f, s = df[f"ema_{fast}"], df[f"ema_{slow}"]
        df[f"ema_{fast}_cross_above_{slow}"] = (f > s) & (f.shift(1) <= s.shift(1))
        df[f"ema_{fast}_cross_below_{slow}"] = (f < s) & (f.shift(1) >= s.shift(1))

    # ── EMA pullback signals (generated for every EMA window computed above) ────
    for window in [8, 12, 20, 21, 26]:
        ema_col = f"ema_{window}"
        df[f"ema{window}_rising"]       = df[ema_col] > df[ema_col].shift(5)
        df[f"touched_ema{window}"]      = low <= df[ema_col]
        df[f"closed_above_ema{window}"] = close > df[ema_col]

    # Hammer: lower wick >= 2× body; upper wick <= body; body in upper 1/3 of range
    op            = df["open"]
    candle_range  = high - low
    body          = (close - op).abs()
    lower_wick    = op.where(close >= op, close) - low
    upper_wick    = high - close.where(close >= op, op)
    df["hammer"]  = (
        (candle_range > 0) &
        (lower_wick >= 2 * body) &
        (upper_wick <= body) &
        (close > op)
    )

    # Bullish engulfing: prev bar bearish, current bar bullish & body wraps prev body
    prev_open  = op.shift(1)
    prev_close = close.shift(1)
    df["bullish_engulfing"] = (
        (prev_close < prev_open) &
        (close > op) &
        (op <= prev_close) &
        (close >= prev_open)
    )

    return df


# ── Public API ────────────────────────────────────────────────────────────────

def get_ohlcv_with_indicators(ticker: str, lookback_days: int = 365) -> pd.DataFrame:
    """Return a DataFrame with OHLCV + all indicators for the last N days.

    Args:
        ticker:        Stock symbol
        lookback_days: How many calendar days of history to return (default 365)
    """
    df = _fetch_daily_full(ticker)
    df = _add_indicators(df)

    cutoff = df.index.max() - pd.Timedelta(days=lookback_days)
    df = df[df.index >= cutoff].copy()
    df.dropna(inplace=True)

    print(f"  [data] {ticker}: {len(df)} trading days after indicator warmup")
    return df


if __name__ == "__main__":
    df = get_ohlcv_with_indicators("NVDA", lookback_days=365)
    print(df[["close", "rsi", "macd", "macd_signal", "sma_50", "adx"]].tail(10))
