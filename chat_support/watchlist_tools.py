"""LangChain tools for watchlist management."""

from langchain_core.tools import tool

from db.session import get_session
from db.models import Watchlist


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
        with get_session() as session:
            existing = session.get(Watchlist, ticker.upper())
            if existing:
                return {
                    "responseType": "WatchlistEntry",
                    "status": "already_exists",
                    "ticker": existing.ticker,
                    "industry": existing.industry,
                    "category": existing.category,
                    "setups": existing.setups or [],
                    "is_active": existing.is_active,
                }
            entry = Watchlist(
                ticker=ticker.upper(),
                industry=industry,
                category=category,
                setups=setups or [],
                is_active=True,
            )
            session.add(entry)
            result = {
                "responseType": "WatchlistEntry",
                "status": "added",
                "ticker": entry.ticker,
                "industry": entry.industry,
                "category": entry.category,
                "setups": entry.setups,
                "is_active": entry.is_active,
            }
        return result
    except Exception as e:
        return {"responseType": "WatchlistEntry", "status": "error", "error": str(e)}


@tool
def update_watchlist_entry(
    ticker: str,
    industry: str = "",
    category: str = "",
    setups: list[str] = [],
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
        setups:    New full list of setup names (leave empty to keep existing)
        is_active: Set active/inactive status (None to keep existing)

    Returns:
        JSON with the updated watchlist entry.
    """
    try:
        with get_session() as session:
            entry = session.get(Watchlist, ticker.upper())
            if entry is None:
                return {
                    "responseType": "WatchlistEntry",
                    "status": "not_found",
                    "error": f"Ticker '{ticker.upper()}' not found in watchlist.",
                }
            if industry:
                entry.industry = industry
            if category:
                entry.category = category
            if setups:
                entry.setups = setups
            if is_active is not None:
                entry.is_active = is_active
            result = {
                "responseType": "WatchlistEntry",
                "status": "updated",
                "ticker": entry.ticker,
                "industry": entry.industry,
                "category": entry.category,
                "setups": entry.setups or [],
                "is_active": entry.is_active,
            }
        return result
    except Exception as e:
        return {"responseType": "WatchlistEntry", "status": "error", "error": str(e)}


WATCHLIST_TOOLS = [add_watchlist_entry, update_watchlist_entry]
