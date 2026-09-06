"""LangChain tools for executing market orders via the Alpaca MCP server / REST API.

These tools are designed to be imported into agent.py and bound to the LLM.
They connect to Alpaca's paper or live trading endpoint based on ALPACA_PAPER in .env.

MCP server note:
  If you run the official Alpaca MCP server (https://github.com/alpacahq/alpaca-mcp),
  set ALPACA_MCP_MODE=true in .env and this module will proxy calls through it instead
  of hitting the REST API directly.
"""

import os
from functools import lru_cache

from langchain_core.tools import tool
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

from config import ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_PAPER


# ── Client factory ────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _get_client() -> TradingClient:
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        raise RuntimeError(
            "Alpaca credentials missing. Set ALPACA_API_KEY and ALPACA_SECRET_KEY in .env"
        )
    return TradingClient(
        api_key=ALPACA_API_KEY,
        secret_key=ALPACA_SECRET_KEY,
        paper=ALPACA_PAPER,
    )


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool
def buy_market_order(ticker: str, qty: float) -> str:
    """Place a market BUY order for the given ticker and quantity of shares.

    Args:
        ticker: Stock symbol, e.g. 'AAPL'
        qty:    Number of shares to buy (fractional shares supported)
    Returns:
        Confirmation string with order ID and status.
    """
    try:
        client = _get_client()
        req = MarketOrderRequest(
            symbol=ticker.upper(),
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )
        order = client.submit_order(req)
        mode = "PAPER" if ALPACA_PAPER else "LIVE"
        return (
            f"[{mode}] BUY order submitted: {order.qty} x {order.symbol} | "
            f"order_id={order.id} | status={order.status}"
        )
    except Exception as e:
        return f"BUY order failed for {ticker}: {e}"


@tool
def sell_market_order(ticker: str, qty: float) -> str:
    """Place a market SELL order for the given ticker and quantity of shares.

    Args:
        ticker: Stock symbol, e.g. 'AAPL'
        qty:    Number of shares to sell (fractional shares supported)
    Returns:
        Confirmation string with order ID and status.
    """
    try:
        client = _get_client()
        req = MarketOrderRequest(
            symbol=ticker.upper(),
            qty=qty,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        order = client.submit_order(req)
        mode = "PAPER" if ALPACA_PAPER else "LIVE"
        return (
            f"[{mode}] SELL order submitted: {order.qty} x {order.symbol} | "
            f"order_id={order.id} | status={order.status}"
        )
    except Exception as e:
        return f"SELL order failed for {ticker}: {e}"


@tool
def get_positions() -> str:
    """Return all currently held positions in the Alpaca account."""
    try:
        client = _get_client()
        positions = client.get_all_positions()
        if not positions:
            return "No open positions."
        lines = []
        for p in positions:
            lines.append(
                f"{p.symbol}: qty={p.qty}, avg_entry=${p.avg_entry_price}, "
                f"market_value=${p.market_value}, unrealized_pl=${p.unrealized_pl}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Could not fetch positions: {e}"


@tool
def get_account_info() -> str:
    """Return Alpaca account buying power, portfolio value, and cash balance."""
    try:
        client = _get_client()
        acct = client.get_account()
        mode = "PAPER" if ALPACA_PAPER else "LIVE"
        return (
            f"[{mode}] Account: portfolio_value=${acct.portfolio_value}, "
            f"cash=${acct.cash}, buying_power=${acct.buying_power}, "
            f"status={acct.status}"
        )
    except Exception as e:
        return f"Could not fetch account info: {e}"


@tool
def get_order_status(order_id: str) -> str:
    """Return the current status of an Alpaca order by its order ID.

    Use this after placing a buy or sell order to confirm whether it has been
    filled, is still pending, or was rejected.

    Args:
        order_id: The Alpaca order ID returned when the order was submitted.

    Returns:
        String with order symbol, qty, side, status, and filled details.
    """
    try:
        client = _get_client()
        order = client.get_order_by_id(order_id)
        mode = "PAPER" if ALPACA_PAPER else "LIVE"
        filled = (
            f"filled_qty={order.filled_qty} @ avg_price=${order.filled_avg_price}"
            if order.filled_qty else "not yet filled"
        )
        return (
            f"[{mode}] Order {order.id}: {order.side} {order.qty} x {order.symbol} | "
            f"status={order.status} | {filled}"
        )
    except Exception as e:
        return f"Could not fetch order status for {order_id}: {e}"


@tool
def cancel_all_orders() -> str:
    """Cancel all open/pending orders in the Alpaca account."""
    try:
        client = _get_client()
        cancelled = client.cancel_orders()
        return f"Cancelled {len(cancelled)} order(s)."
    except Exception as e:
        return f"Could not cancel orders: {e}"


# ── Exported list for agent.py ────────────────────────────────────────────────

TRADING_TOOLS = [
    buy_market_order,
    sell_market_order,
    get_order_status,
    get_positions,
    get_account_info,
    cancel_all_orders,
]


if __name__ == "__main__":
    buy_market_order.invoke({"ticker":"TSLA", "qty": 10})
    print(get_account_info.invoke({}))
    print(get_positions.invoke({}))
