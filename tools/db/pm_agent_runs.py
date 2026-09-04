"""Persistence for PortfolioManagerAgent run summaries."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from tools.db.session import get_session
from tools.db.models import PMAgentRun


def _to_dict(r: PMAgentRun) -> dict:
    return {
        "id":                   r.id,
        "account_id":           r.account_id,
        "run_at":               r.run_at.isoformat() if r.run_at else None,
        "sim_date":             r.sim_date,
        "elapsed_seconds":      r.elapsed_seconds,
        "holdings_evaluated":   r.holdings_evaluated,
        "sells_executed":       r.sells_executed,
        "buys_executed":        r.buys_executed,
        "open_holdings_count":  r.open_holdings_count,
        "summary_text":         r.summary_text,
        "summary_json":         r.summary_json,
        "errors":               r.errors,
        "created_at":           r.created_at.isoformat() if r.created_at else None,
    }


def _build_summary_text(summary: dict, sim_date: str | None) -> str:
    """Format a human-readable run summary for UI display."""
    run_at   = summary.get("run_at", "")[:19].replace("T", " ")
    account  = summary.get("account_id", "")[:8]
    elapsed  = summary.get("elapsed_seconds", 0)
    sim_line = f"  Simulation date  : {sim_date}\n" if sim_date else ""

    holdings_eval = summary.get("holdings_eval") or []
    sells = [h for h in holdings_eval if h.get("decision") == "SELL"]
    buys  = summary.get("buys_executed") or []
    open_h = summary.get("open_holdings") or []
    errors = summary.get("errors") or []

    sell_lines = "\n".join(
        f"    SELL {h['ticker']} {h['pending_qty']} shares @ ${h.get('current_price', 0):.2f}"
        f"  PnL: {h.get('pnl_pct', 0):+.1f}%  ({h.get('reason', '')[:60]})"
        for h in sells
    ) or "    (none)"

    buy_lines = "\n".join(
        f"    BUY  {b['ticker']} — setup: {b.get('setup_name', '')}  order: {b.get('order', {}).get('status', '')}"
        for b in buys
    ) or "    (none)"

    research = summary.get("research_results") or []
    rec_lines = "\n".join(
        f"    {r['ticker']:<8} {r.get('recommendation', 'WAIT'):<5}  {r.get('reason', '')[:70]}"
        for r in research
    ) or "    (none)"

    error_line = f"\n  Errors           : {errors}" if errors else ""

    return (
        f"PortfolioManagerAgent Run\n"
        f"  Run at           : {run_at} UTC  (account: ...{account})\n"
        f"{sim_line}"
        f"  Elapsed          : {elapsed:.1f}s\n"
        f"\nResearch\n{rec_lines}\n"
        f"\nSells executed ({len(sells)})\n{sell_lines}\n"
        f"\nBuys executed ({len(buys)})\n{buy_lines}\n"
        f"\nOpen holdings after run: {len(open_h)}"
        f"{error_line}"
    )


def save_pm_run(summary: dict, sim_date: str | None = None) -> dict:
    """Persist a PortfolioManagerAgent run summary.

    Args:
        summary:  The dict returned by PortfolioManagerAgent.run().
        sim_date: MOCK_SIMULATION_DATE string (YYYY-MM-DD) or None.

    Returns:
        The saved run as a dict.
    """
    holdings_eval = summary.get("holdings_eval") or []
    sells         = [h for h in holdings_eval if h.get("decision") == "SELL"]
    buys          = summary.get("buys_executed") or []
    open_h        = summary.get("open_holdings") or []

    run = PMAgentRun(
        id=str(uuid.uuid4()),
        account_id=summary["account_id"],
        run_at=datetime.fromisoformat(summary["run_at"]) if summary.get("run_at") else datetime.now(timezone.utc),
        sim_date=sim_date,
        elapsed_seconds=summary.get("elapsed_seconds"),
        holdings_evaluated=len(holdings_eval),
        sells_executed=len(sells),
        buys_executed=len(buys),
        open_holdings_count=len(open_h),
        summary_text=_build_summary_text(summary, sim_date),
        summary_json=summary,
        errors=summary.get("errors") or None,
    )

    with get_session() as session:
        session.add(run)
        session.flush()
        result = _to_dict(run)

    print(f"[pm_agent_runs] Run saved: id={result['id']}")
    return result


def get_pm_run(run_id: str) -> dict | None:
    """Return a single run by ID, or None if not found."""
    with get_session() as session:
        row = session.query(PMAgentRun).filter(PMAgentRun.id == run_id).first()
        return _to_dict(row) if row else None


def list_pm_runs(
    account_id: str,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    limit: int = 50,
) -> list[dict]:
    """Return run summaries for an account, newest first.

    Args:
        account_id: PortfolioAccount.id
        from_date:  Include only runs with run_at >= from_date
        to_date:    Include only runs with run_at <= to_date
        limit:      Max rows to return (default 50)
    """
    with get_session() as session:
        q = session.query(PMAgentRun).filter(PMAgentRun.account_id == account_id)
        if from_date:
            q = q.filter(PMAgentRun.run_at >= from_date)
        if to_date:
            q = q.filter(PMAgentRun.run_at <= to_date)
        rows = q.order_by(PMAgentRun.run_at.desc()).limit(limit).all()
        return [_to_dict(r) for r in rows]
