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
                "responseType":    "WatchlistEntry",
                "status":          "added",
                "ticker":          entry.ticker,
                "industry":        entry.industry,
                "category":        entry.category,
                "setups":          entry.setups,
                "is_active":       entry.is_active,
                "already_formatted": True,
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
                "responseType":    "WatchlistEntry",
                "status":          "updated",
                "ticker":          entry.ticker,
                "industry":        entry.industry,
                "category":        entry.category,
                "setups":          entry.setups or [],
                "is_active":       entry.is_active,
                "already_formatted": True,
            }
        return result
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
        with get_session() as session:
            from sqlalchemy import select
            stmt = select(Watchlist)
            if active_only:
                stmt = stmt.where(Watchlist.is_active == True)
            entries = session.execute(stmt).scalars().all()
            result = [
                {
                    "ticker":    e.ticker,
                    "industry":  e.industry,
                    "category":  e.category,
                    "setups":    e.setups or [],
                    "is_active": e.is_active,
                    "added_at":  str(e.added_at),
                }
                for e in entries
            ]
        return {
            "responseType":    "WatchlistEntries",
            "count":           len(result),
            "entries":         result,
            "already_formatted": True,
        }
    except Exception as e:
        return {"responseType": "WatchlistEntries", "status": "error", "error": str(e)}


WATCHLIST_TOOLS = [add_watchlist_entry, update_watchlist_entry, list_watchlist]
