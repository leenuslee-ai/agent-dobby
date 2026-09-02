"""LangChain tools for watchlist management."""

from langchain_core.tools import tool

from db.watchlist_data import (
    add_watchlist_entry as _add,
    update_watchlist_entry as _update,
    list_watchlist as _list,
)


@tool
def add_watchlist_entry(
    ticker: str,
    industry: str = "",
    category: str = "",
    setups: list[str] = [],
) -> dict:
    """Add a new ticker to the watchlist.

    Use this tool when the user wants to add or track a new stock.
    Examples:
      - "Add NVDA to my watchlist"
      - "Track AAPL in the Technology / Large Cap Tech category"
      - "Add TSLA to watchlist with the EMA20_PB setup"

    Args:
        ticker:   Stock symbol (e.g. "NVDA")
        industry: Industry name (e.g. "Semiconductors")
        category: Category label (e.g. "Large Cap Tech")
        setups:   List of backtested setup names to associate (e.g. ["EMA20_PB"])

    Returns:
        JSON with the created or existing watchlist entry.
    """
    try:
        result = _add(ticker=ticker, industry=industry, category=category, setups=setups or None)
        return {"responseType": "WatchlistEntry", "already_formatted": True, **result}
    except Exception as e:
        return {"responseType": "WatchlistEntry", "status": "error", "error": str(e)}


@tool
def update_watchlist_entry(
    ticker: str,
    industry: str = "",
    category: str = "",
    setups: list[str] | None = None,
    is_active: bool = None,
) -> dict:
    """Update an existing watchlist entry.

    Use this tool when the user wants to update a ticker's industry, category,
    associated setups, or active status.
    Examples:
      - "Update NVDA watchlist entry to add the RSI_MACD_TREND setup"
      - "Change TSLA category to EV / Auto"
      - "Deactivate AAPL in the watchlist"
      - "Add EMA20_PB setup to MSFT"

    Args:
        ticker:    Stock symbol to update (e.g. "NVDA")
        industry:  New industry value (leave empty to keep existing)
        category:  New category value (leave empty to keep existing)
        setups:    New full list of setup names (pass [] to clear, omit to keep existing)
        is_active: Set active/inactive status (None to keep existing)

    Returns:
        JSON with the updated watchlist entry.
    """
    try:
        result = _update(ticker=ticker, industry=industry, category=category, setups=setups, is_active=is_active)
        return {"responseType": "WatchlistEntry", "already_formatted": True, **result}
    except Exception as e:
        return {"responseType": "WatchlistEntry", "status": "error", "error": str(e)}


@tool
def list_watchlist(active_only: bool = False) -> dict:
    """List all tickers in the watchlist.

    Use this tool when the user wants to see their watchlist.
    Examples:
      - "Show me my watchlist"
      - "List all watched stocks"
      - "What stocks am I tracking?"
      - "Show only active watchlist entries"

    Args:
        active_only: If True, return only active entries (default False — return all).

    Returns:
        JSON with a list of watchlist entries.
    """
    try:
        entries = _list(active_only=active_only)
        return {
            "responseType":    "WatchlistEntries",
            "count":           len(entries),
            "entries":         entries,
            "already_formatted": True,
        }
    except Exception as e:
        return {"responseType": "WatchlistEntries", "status": "error", "error": str(e)}


WATCHLIST_TOOLS = [add_watchlist_entry, update_watchlist_entry, list_watchlist]
