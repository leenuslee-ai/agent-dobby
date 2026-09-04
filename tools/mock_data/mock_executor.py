"""Simulated order execution for mock tickers.

Returns a fill dict in the same shape as poll_order_status() so the rest of
the agent pipeline (save_trade, logging) is identical for real and mock orders.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from config import MOCK_SIMULATION_DATE

_CACHE_DIR = Path(__file__).parent.parent / "alphavantage" / "cache"


def _mock_price(ticker: str) -> float:
    """Read the closing price for ticker at the simulation date from the local CSV."""
    cache_file = _CACHE_DIR / f"{ticker}_daily.csv"
    if not cache_file.exists():
        raise FileNotFoundError(f"No mock price data for {ticker}")
    df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
    cutoff = MOCK_SIMULATION_DATE or datetime.now(timezone.utc).date()
    df = df[df.index.date <= cutoff]
    if df.empty:
        raise ValueError(f"No price rows for {ticker} up to {cutoff}")
    return float(df.iloc[-1]["close"])


def simulate_fill(ticker: str, qty: float, side: str) -> dict:
    """Return a simulated filled order dict without touching Alpaca.

    Args:
        ticker: Stock symbol (must be a mock ticker).
        qty:    Number of shares (may be fractional).
        side:   "BUY" or "SELL"

    Returns:
        Dict matching the shape of poll_order_status():
        {order_id, status, filled_qty, filled_avg_price, filled_at}
    """
    price = _mock_price(ticker.upper())
    order_id = f"mock-{uuid.uuid4()}"
    fill = {
        "order_id":         order_id,
        "status":           "filled",
        "filled_qty":       qty,
        "filled_avg_price": price,
        "filled_at":        datetime.now(timezone.utc).isoformat(),
    }
    sim_date = MOCK_SIMULATION_DATE or datetime.now(timezone.utc).date()
    print(
        f"  [mock_order] {side} {qty} x {ticker} @ ${price:.2f} "
        f"(sim_date={sim_date})  order_id={order_id}"
    )
    return fill
