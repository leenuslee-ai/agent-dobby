"""Watchlist DB access functions."""

from sqlalchemy import select

from tools.db.session import get_session
from tools.db.models import Watchlist


def get_tickers(active_only: bool = True) -> list[str]:
    """Return tickers from the watchlist table."""
    with get_session() as session:
        q = session.query(Watchlist.ticker)
        if active_only:
            q = q.filter(Watchlist.is_active == True)
        return [row.ticker for row in q.order_by(Watchlist.ticker).all()]


def add_watchlist_entry(
    ticker: str,
    industry: str = "",
    category: str = "",
    setups: list[str] | None = None,
) -> dict:
    """Insert a new watchlist entry. Returns status 'added' or 'already_exists'."""
    with get_session() as session:
        existing = session.get(Watchlist, ticker.upper())
        if existing:
            return {
                "status":    "already_exists",
                "ticker":    existing.ticker,
                "industry":  existing.industry,
                "category":  existing.category,
                "setups":    existing.setups or [],
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
        return {
            "status":    "added",
            "ticker":    entry.ticker,
            "industry":  entry.industry,
            "category":  entry.category,
            "setups":    entry.setups,
            "is_active": entry.is_active,
        }


def update_watchlist_entry(
    ticker: str,
    industry: str = "",
    category: str = "",
    setups: list[str] | None = None,
    is_active: bool | None = None,
) -> dict:
    """Update an existing watchlist entry. Returns status 'updated' or 'not_found'."""
    with get_session() as session:
        entry = session.get(Watchlist, ticker.upper())
        if entry is None:
            return {
                "status": "not_found",
                "error":  f"Ticker '{ticker.upper()}' not found in watchlist.",
            }
        if industry:
            entry.industry = industry
        if category:
            entry.category = category
        if setups is not None:
            entry.setups = setups
        if is_active is not None:
            entry.is_active = is_active
        return {
            "status":    "updated",
            "ticker":    entry.ticker,
            "industry":  entry.industry,
            "category":  entry.category,
            "setups":    entry.setups or [],
            "is_active": entry.is_active,
        }


def list_watchlist(active_only: bool = False) -> list[dict]:
    """Return all watchlist entries as a list of dicts."""
    with get_session() as session:
        stmt = select(Watchlist)
        if active_only:
            stmt = stmt.where(Watchlist.is_active == True)
        entries = session.execute(stmt).scalars().all()
        return [
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
