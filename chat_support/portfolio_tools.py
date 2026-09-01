"""LangChain tools for portfolio account management."""

import uuid

from langchain_core.tools import tool

from db.session import get_session
from db.models import PortfolioAccount


@tool
def create_portfolio_account(
    broker: str,
    account_id: str,
    display_name: str = "",
    is_paper: bool = True,
    cash: float = 0.0,
    equity: float = 0.0,
) -> dict:
    """Create and persist a new portfolio account in the database.

    Use this tool when the user asks to add, create, or register a new
    portfolio account or brokerage account. Examples:
      - "Add a new Alpaca paper account with account ID ABC123"
      - "Create a portfolio account for my live Alpaca account"
      - "Register my TD Ameritrade account"

    Args:
        broker:       Broker name (e.g. "alpaca", "td_ameritrade")
        account_id:   The broker-assigned account identifier
        display_name: Optional friendly label for this account
        is_paper:     True for paper/simulated trading, False for live (default True)
        cash:         Starting cash balance (default 0.0)
        equity:       Starting equity value (default 0.0)

    Returns:
        JSON with the created account details or an error message.
    """
    try:
        with get_session() as session:
            existing = (
                session.query(PortfolioAccount)
                .filter_by(broker=broker.lower(), account_id=account_id)
                .first()
            )
            if existing:
                return {
                    "responseType": "PortfolioAccount",
                    "status": "already_exists",
                    "id": existing.id,
                    "broker": existing.broker,
                    "account_id": existing.account_id,
                    "display_name": existing.display_name,
                    "is_paper": existing.is_paper,
                }

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
            result = {
                "responseType":    "PortfolioAccount",
                "status":          "created",
                "id":              account.id,
                "broker":          account.broker,
                "account_id":      account.account_id,
                "display_name":    account.display_name,
                "is_paper":        account.is_paper,
                "cash":            account.cash,
                "equity":          account.equity,
                "already_formatted": True,
            }

        return result
    except Exception as e:
        return {"responseType": "PortfolioAccount", "status": "error", "error": str(e)}


@tool
def list_portfolio_accounts() -> dict:
    """List all portfolio accounts stored in the database.

    Use this tool when the user asks to see, list, or show their accounts.
    Examples:
      - "Show me my accounts"
      - "List all portfolio accounts"
      - "What accounts do I have?"

    Returns:
        JSON with a list of portfolio accounts.
    """
    try:
        with get_session() as session:
            accounts = session.query(PortfolioAccount).order_by(PortfolioAccount.created_at).all()
            result = [
                {
                    "id":           a.id,
                    "broker":       a.broker,
                    "account_id":   a.account_id,
                    "display_name": a.display_name,
                    "is_paper":     a.is_paper,
                    "cash":         a.cash,
                    "equity":       a.equity,
                    "created_at":   a.created_at.isoformat() if a.created_at else None,
                }
                for a in accounts
            ]
        return {"responseType": "PortfolioAccountList", "accounts": result, "total": len(result), "already_formatted": True}
    except Exception as e:
        return {"responseType": "PortfolioAccountList", "status": "error", "error": str(e)}


PORTFOLIO_TOOLS = [create_portfolio_account, list_portfolio_accounts]
