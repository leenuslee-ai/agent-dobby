"""LangChain tools for retrieving PortfolioManagerAgent run summaries."""

from __future__ import annotations

from datetime import datetime, timezone

from langchain_core.tools import tool

from tools.db.pm_agent_runs import get_pm_run, list_pm_runs
from tools.db.portfolio_data import get_account, list_accounts


def _resolve_pm_account(account_id: str) -> tuple[str, str]:
    """Resolve account_id or display_name to (uuid, display_name)."""
    accounts = list_accounts()
    if not accounts:
        return account_id, ""
    if not account_id:
        a = accounts[0]
        return a["id"], a["display_name"]
    match = next((a for a in accounts if a["id"] == account_id), None)
    if match is None:
        match = next(
            (a for a in accounts if account_id.lower() in a["display_name"].lower()),
            None,
        )
    if match:
        return match["id"], match["display_name"]
    return account_id, ""


@tool
def get_pm_run_result(run_id: str) -> dict:
    """Retrieve a single PortfolioManagerAgent run by its ID.

    Use this when the user asks about a specific run, e.g.:
      - "Show me run abc-123"
      - "What happened in PM run abc-123?"

    Args:
        run_id: The UUID of the PM agent run.

    Returns:
        JSON with the full run summary including trades and research results.
    """
    run = get_pm_run(run_id)
    if run is None:
        return {"responseType": "PMAgentRun", "error": f"Run '{run_id}' not found."}
    account = get_account(run["account_id"])
    account_name = account["display_name"] if account else ""
    return {"responseType": "PMAgentRun", "account_name": account_name, "already_formatted": True, **run}


@tool
def list_pm_run_results(
    from_date: str = "",
    to_date: str = "",
    limit: int = 20,
    account_id: str = "",
) -> dict:
    """List PortfolioManagerAgent run results — buys, sells, and decisions made per day.

    Use this when the user asks about PM agent run history, daily run results,
    or what the agent bought/sold. Examples:
      - "List pm run results"
      - "Show me the PM runs for PaperAcct1"
      - "List pm run results from September"
      - "What did the agent do this week?"
      - "Show recent agent activity"

    Do NOT use this to list brokerage accounts — use list_portfolio_accounts for that.

    Args:
        from_date:  Optional start date filter (YYYY-MM-DD).
        to_date:    Optional end date filter (YYYY-MM-DD).
        limit:      Max number of runs to return (default 20).
        account_id: Optional account name or UUID. Defaults to the first account.

    Returns:
        JSON with a list of run summaries, newest first.
    """
    if not list_accounts():
        return {"responseType": "PMAgentRunList", "error": "No portfolio accounts found."}

    resolved, account_name = _resolve_pm_account(account_id)
    from_dt = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) if from_date else None
    to_dt   = datetime.strptime(to_date,   "%Y-%m-%d").replace(tzinfo=timezone.utc) if to_date   else None

    runs = list_pm_runs(resolved, from_date=from_dt, to_date=to_dt, limit=limit)
    return {
        "responseType":      "PMAgentRunList",
        "account_id":        resolved,
        "account_name":      account_name,
        "count":             len(runs),
        "runs":              runs,
        "already_formatted": True,
    }


PM_RUN_TOOLS = [get_pm_run_result, list_pm_run_results]
