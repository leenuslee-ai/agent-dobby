"""Alpaca client for the SPY/QQQ positional trader (second paper account).

Uses ALPACA_API_KEY_2 / ALPACA_SECRET_KEY_2 from .env, keeping it completely
separate from the primary Alpaca account used by PortfolioManagerAgent.
"""

from __future__ import annotations

import time
from functools import lru_cache

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestTradeRequest

from config import ALPACA_API_KEY_2, ALPACA_SECRET_KEY_2, ALPACA_PAPER


# ── Client factories ──────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _trading_client() -> TradingClient:
    if not ALPACA_API_KEY_2 or not ALPACA_SECRET_KEY_2:
        raise RuntimeError(
            "ALPACA_API_KEY_2 / ALPACA_SECRET_KEY_2 not set in .env — "
            "add credentials for the second paper account."
        )
    return TradingClient(
        api_key=ALPACA_API_KEY_2,
        secret_key=ALPACA_SECRET_KEY_2,
        paper=ALPACA_PAPER,
    )


@lru_cache(maxsize=1)
def _data_client() -> StockHistoricalDataClient:
    return StockHistoricalDataClient(
        api_key=ALPACA_API_KEY_2,
        secret_key=ALPACA_SECRET_KEY_2,
    )


# ── Account ───────────────────────────────────────────────────────────────────

def get_account() -> dict:
    """Return cash, equity, buying_power and portfolio_value for account 2."""
    acct = _trading_client().get_account()
    return {
        "cash":            float(acct.cash),
        "equity":          float(acct.equity),
        "buying_power":    float(acct.buying_power),
        "portfolio_value": float(acct.portfolio_value),
    }


# ── Positions ─────────────────────────────────────────────────────────────────

def get_positions() -> dict[str, dict]:
    """Return {ticker: {qty, market_value, avg_entry_price}} for all open positions."""
    positions = _trading_client().get_all_positions()
    return {
        p.symbol: {
            "qty":             float(p.qty),
            "market_value":    float(p.market_value),
            "avg_entry_price": float(p.avg_entry_price),
        }
        for p in positions
    }


def get_portfolio_value() -> float:
    """Return total portfolio value (cash + all open positions)."""
    return float(_trading_client().get_account().portfolio_value)


# ── Live price ────────────────────────────────────────────────────────────────

def get_live_price(ticker: str) -> float | None:
    """Return the latest trade price from Alpaca market data."""
    try:
        result = _data_client().get_stock_latest_trade(
            StockLatestTradeRequest(symbol_or_symbols=ticker.upper())
        )
        return float(result[ticker.upper()].price)
    except Exception as exc:
        print(f"  [spyqqq_client] Could not fetch live price for {ticker}: {exc}")
        return None


# ── Orders ────────────────────────────────────────────────────────────────────

def place_order(ticker: str, qty: float, side: str) -> dict:
    """Submit a market order. side must be 'BUY' or 'SELL'.

    Returns a dict with order_id, status, ticker, qty, side.
    Raises on submission failure.
    """
    order_side = OrderSide.BUY if side.upper() == "BUY" else OrderSide.SELL
    order = _trading_client().submit_order(MarketOrderRequest(
        symbol=ticker.upper(),
        qty=round(qty, 6),
        side=order_side,
        time_in_force=TimeInForce.DAY,
    ))
    return {
        "order_id": str(order.id),
        "status":   str(order.status),
        "ticker":   ticker.upper(),
        "qty":      qty,
        "side":     side.upper(),
    }


def cancel_all_orders() -> int:
    """Cancel all open/pending orders. Returns the number cancelled."""
    cancelled = _trading_client().cancel_orders()
    return len(cancelled)


def poll_order(order_id: str, max_attempts: int = 10, pause_secs: float = 2.0) -> dict:
    """Poll until an order is filled or max_attempts is reached.

    Returns a dict with status, filled_qty, filled_avg_price.
    """
    client = _trading_client()
    for _ in range(max_attempts):
        order = client.get_order_by_id(order_id)
        status = str(order.status)
        if status in ("filled", "partially_filled", "cancelled", "expired", "rejected"):
            return {
                "status":           status,
                "filled_qty":       float(order.filled_qty or 0),
                "filled_avg_price": float(order.filled_avg_price or 0),
            }
        time.sleep(pause_secs)
    return {"status": "timeout", "filled_qty": 0, "filled_avg_price": 0}
