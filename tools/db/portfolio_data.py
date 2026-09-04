"""DB access functions for portfolio accounts."""

from __future__ import annotations

import uuid

from tools.db.session import get_session
from tools.db.models import PortfolioAccount


def _to_dict(a: PortfolioAccount) -> dict:
    return {
        "id":           a.id,
        "broker":       a.broker,
        "account_id":   a.account_id,
        "display_name": a.display_name,
        "is_paper":     a.is_paper,
        "cash":         a.cash,
        "equity":       a.equity,
        "created_at":   a.created_at.isoformat() if a.created_at else None,
    }


def create_account(
    broker: str,
    account_id: str,
    display_name: str = "",
    is_paper: bool = True,
    cash: float = 0.0,
    equity: float = 0.0,
) -> dict:
    """Create a portfolio account. Returns the account dict with a 'status' key.

    status is 'created' for new accounts or 'already_exists' if a duplicate is found.
    """
    with get_session() as session:
        existing = (
            session.query(PortfolioAccount)
            .filter_by(broker=broker.lower(), account_id=account_id)
            .first()
        )
        if existing:
            return {"status": "already_exists", **_to_dict(existing)}

        account = PortfolioAccount(
            id=str(uuid.uuid4()),
            broker=broker.lower(),
            account_id=account_id,
            display_name=display_name or f"{broker} {account_id}",
            is_paper=is_paper,
            cash=cash,
            equity=equity,
        )
        session.add(account)
        session.flush()
        return {"status": "created", **_to_dict(account)}


def list_accounts() -> list[dict]:
    """Return all portfolio accounts ordered by creation date."""
    with get_session() as session:
        rows = session.query(PortfolioAccount).order_by(PortfolioAccount.created_at).all()
        return [_to_dict(a) for a in rows]
