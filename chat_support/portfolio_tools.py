"""LangChain tools for portfolio account management."""

from datetime import datetime, timezone

from langchain_core.tools import tool

from tools.db.portfolio_data import create_account, list_accounts
from tools.db.trade_data import get_holdings, get_open_holdings, get_trades


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


def _resolve_account_id(account_id: str) -> str:
    """Resolve a display_name or UUID to an account UUID."""
    accounts = list_accounts()
    if not accounts:
        return account_id
    match = next((a for a in accounts if a["id"] == account_id), None)
    if match is None:
        match = next((a for a in accounts if account_id.lower() in a["display_name"].lower()), None)
    return match["id"] if match else account_id


@tool
def get_portfolio_holdings(
    account_id: str = "",
    ticker: str = "",
) -> dict:
    """Get all holdings (open and closed) for a portfolio account.

    Use this when the user asks about holdings, positions, or what stocks
    the agent has bought — including fully closed positions. Examples:
      - "Show me all holdings for PaperAcct1"
      - "What positions does the agent have?"
      - "Show DOBBY holdings"

    Do NOT use this for PM agent run results — use list_pm_run_results for that.

    Args:
        account_id: Account name or UUID. Defaults to the first account.
        ticker:     Optional ticker to filter by (e.g. "DOBBY").

    Returns:
        JSON with a list of holding records.
    """
    try:
        accounts = list_accounts()
        if not accounts:
            return {"responseType": "HoldingList", "error": "No portfolio accounts found."}
        resolved = _resolve_account_id(account_id) if account_id else accounts[0]["id"]
        rows = get_holdings(resolved, opening_transaction_type="BUY")
        if ticker:
            rows = [r for r in rows if r["ticker"] == ticker.upper()]
        return {"responseType": "HoldingList", "account_id": resolved, "count": len(rows), "holdings": rows, "already_formatted": True}
    except Exception as e:
        return {"responseType": "HoldingList", "status": "error", "error": str(e)}


@tool
def get_open_portfolio_holdings(
    account_id: str = "",
    ticker: str = "",
) -> dict:
    """Get currently open (not yet fully sold) holdings for a portfolio account.

    Use this when the user asks about open positions or what the agent is
    currently holding. Examples:
      - "What is the agent currently holding?"
      - "Show open positions for PaperAcct1"
      - "What open DOBBY positions are there?"

    Do NOT use this for PM agent run results — use list_pm_run_results for that.

    Args:
        account_id: Account name or UUID. Defaults to the first account.
        ticker:     Optional ticker to filter by (e.g. "DOBBY").

    Returns:
        JSON with a list of open holding records.
    """
    try:
        accounts = list_accounts()
        if not accounts:
            return {"responseType": "OpenHoldingList", "error": "No portfolio accounts found."}
        resolved = _resolve_account_id(account_id) if account_id else accounts[0]["id"]
        rows = get_open_holdings(resolved, opening_transaction_type="BUY")
        if ticker:
            rows = [r for r in rows if r["ticker"] == ticker.upper()]
        return {"responseType": "OpenHoldingList", "account_id": resolved, "count": len(rows), "holdings": rows, "already_formatted": True}
    except Exception as e:
        return {"responseType": "OpenHoldingList", "status": "error", "error": str(e)}


@tool
def get_portfolio_trades(
    account_id: str = "",
    ticker: str = "",
    side: str = "",
    from_date: str = "",
    to_date: str = "",
) -> dict:
    """Get trade transactions (buys and sells) for a portfolio account.

    Use this when the user asks about trades, transactions, buy/sell history,
    or what the agent executed. Examples:
      - "Show me all trades for PaperAcct1"
      - "List DOBBY buy transactions"
      - "What did the agent sell in September?"
      - "Show trades from 2026-09-01 to 2026-09-30"

    Do NOT use this for PM agent run results — use list_pm_run_results for that.

    Args:
        account_id: Account name or UUID. Defaults to the first account.
        ticker:     Optional ticker filter (e.g. "DOBBY").
        side:       Optional "BUY" or "SELL" filter.
        from_date:  Optional start date filter (YYYY-MM-DD).
        to_date:    Optional end date filter (YYYY-MM-DD).

    Returns:
        JSON with a list of trade transaction records.
    """
    try:
        accounts = list_accounts()
        if not accounts:
            return {"responseType": "TradeList", "error": "No portfolio accounts found."}
        resolved = _resolve_account_id(account_id) if account_id else accounts[0]["id"]
        from_dt = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) if from_date else None
        to_dt   = datetime.strptime(to_date,   "%Y-%m-%d").replace(tzinfo=timezone.utc) if to_date   else None
        rows = get_trades(
            resolved,
            ticker=ticker or None,
            side=side or None,
            from_date=from_dt,
            to_date=to_dt,
        )
        return {"responseType": "TradeList", "account_id": resolved, "count": len(rows), "trades": rows, "already_formatted": True}
    except Exception as e:
        return {"responseType": "TradeList", "status": "error", "error": str(e)}


PORTFOLIO_TOOLS = [
    create_portfolio_account,
    list_portfolio_accounts,
    get_portfolio_holdings,
    get_open_portfolio_holdings,
    get_portfolio_trades,
]
