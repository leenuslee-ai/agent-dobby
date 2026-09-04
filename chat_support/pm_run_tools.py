"""LangChain tools for retrieving PortfolioManagerAgent run summaries."""

from __future__ import annotations

from datetime import datetime, timezone

from langchain_core.tools import tool

from tools.db.pm_agent_runs import get_pm_run, list_pm_runs


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
    return {"responseType": "PMAgentRun", "already_formatted": True, **run}


@tool
def list_pm_run_results(
    account_id: str,
    from_date: str = "",
    to_date: str = "",
    limit: int = 20,
) -> dict:
    """List PortfolioManagerAgent run summaries for an account.

    Use this when the user asks to review recent PM agent activity, e.g.:
      - "Show me the last PM runs for account xyz"
      - "List portfolio manager runs from September"
      - "What did the agent do this week?"

    Args:
        account_id: The portfolio account UUID.
        from_date:  Optional start date filter (YYYY-MM-DD).
        to_date:    Optional end date filter (YYYY-MM-DD).
        limit:      Max number of runs to return (default 20).

    Returns:
        JSON with a list of run summaries, newest first.
    """
    from_dt = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) if from_date else None
    to_dt   = datetime.strptime(to_date,   "%Y-%m-%d").replace(tzinfo=timezone.utc) if to_date   else None

    runs = list_pm_runs(account_id, from_date=from_dt, to_date=to_dt, limit=limit)
    return {
        "responseType":    "PMAgentRunList",
        "account_id":      account_id,
        "count":           len(runs),
        "runs":            runs,
        "already_formatted": True,
    }


PM_RUN_TOOLS = [get_pm_run_result, list_pm_run_results]
