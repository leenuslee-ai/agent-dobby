"""LangChain tools for portfolio account management."""

from langchain_core.tools import tool

from tools.db.portfolio_data import create_account, list_accounts


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
        data = create_account(broker, account_id, display_name, is_paper, cash, equity)
        return {"responseType": "PortfolioAccount", "already_formatted": True, **data}
    except Exception as e:
        return {"responseType": "PortfolioAccount", "status": "error", "error": str(e)}


@tool
def list_portfolio_accounts() -> dict:
    """List all portfolio brokerage accounts (not run history or trades).

    Use this tool ONLY when the user asks about their brokerage accounts themselves.
    Examples:
      - "Show me my accounts"
      - "List all portfolio accounts"
      - "What accounts do I have?"

    Do NOT use this for PM agent runs, trade history, or run results.

    Returns:
        JSON with a list of portfolio accounts.
    """
    try:
        accounts = list_accounts()
        return {
            "responseType":    "PortfolioAccountList",
            "accounts":        accounts,
            "total":           len(accounts),
            "already_formatted": True,
        }
    except Exception as e:
        return {"responseType": "PortfolioAccountList", "status": "error", "error": str(e)}


PORTFOLIO_TOOLS = [create_portfolio_account, list_portfolio_accounts]
