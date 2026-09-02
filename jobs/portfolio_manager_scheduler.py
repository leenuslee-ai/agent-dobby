"""Scheduler: run PortfolioManagerAgent for every account every hour during market hours.

Schedule: Mon–Fri, 9:30AM–4:00PM US/Eastern, on the hour (first fire at 9:30).
Each run spawns one PortfolioManagerAgent per active portfolio account and
executes them concurrently via asyncio.

Usage:
    python -m jobs.portfolio_manager_scheduler          # start scheduler
    python -m jobs.portfolio_manager_scheduler --now    # run once immediately
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from db.session import get_session
from db.models import PortfolioAccount


# ── Account discovery ─────────────────────────────────────────────────────────

def _get_accounts() -> list[dict]:
    """Return all portfolio accounts from the DB."""
    with get_session() as session:
        accounts = session.query(PortfolioAccount).order_by(PortfolioAccount.created_at).all()
        return [
            {
                "id":           a.id,
                "broker":       a.broker,
                "display_name": a.display_name,
                "is_paper":     a.is_paper,
            }
            for a in accounts
        ]


# ── Per-account runner (called in thread pool) ────────────────────────────────

def _run_account(account: dict) -> dict:
    from agents.portfolio_manager_agent import PortfolioManagerAgent
    label = account.get("display_name") or account["id"]
    print(f"\n[scheduler] Starting PortfolioManagerAgent for account: {label}")
    try:
        agent = PortfolioManagerAgent(account_id=account["id"])
        summary = agent.run()
        print(f"[scheduler] Finished account: {label} | buys={len(summary.get('buys_executed', []))} "
              f"sells={len([h for h in (summary.get('holdings_eval') or []) if h.get('decision') == 'SELL'])}")
        return {"account": label, "status": "ok", "summary": summary}
    except Exception as e:
        print(f"[scheduler] ERROR for account {label}: {e}")
        return {"account": label, "status": "error", "error": str(e)}


# ── Main job (fired by scheduler) ─────────────────────────────────────────────

def run_all_accounts():
    now = datetime.now(timezone.utc)
    print(f"\n{'='*60}")
    print(f"[scheduler] Portfolio Manager Run | {now.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}")

    accounts = _get_accounts()
    if not accounts:
        print("[scheduler] No portfolio accounts found — nothing to do.")
        return

    print(f"[scheduler] Accounts to manage: {len(accounts)}")

    # Run one agent per account concurrently
    results = []
    with ThreadPoolExecutor(max_workers=len(accounts)) as pool:
        futures = [pool.submit(_run_account, acct) for acct in accounts]
        for f in futures:
            try:
                results.append(f.result(timeout=600))
            except Exception as e:
                results.append({"status": "error", "error": str(e)})

    ok    = sum(1 for r in results if r["status"] == "ok")
    errs  = sum(1 for r in results if r["status"] == "error")
    print(f"\n[scheduler] All accounts done | ok={ok} errors={errs}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Portfolio Manager scheduler")
    parser.add_argument("--now", action="store_true", help="Run once immediately then exit")
    args = parser.parse_args()

    if args.now:
        run_all_accounts()
        return

    scheduler = BlockingScheduler(timezone="US/Eastern")

    # 9:30 AM fire (market open)
    scheduler.add_job(
        run_all_accounts,
        CronTrigger(hour=9, minute=30, day_of_week="mon-fri"),
        id="pm_0930",
        name="Portfolio Manager 09:30 ET",
        misfire_grace_time=300,
    )

    # 10:00 AM – 3:00 PM, on the hour
    for hour in range(10, 16):
        scheduler.add_job(
            run_all_accounts,
            CronTrigger(hour=hour, minute=0, day_of_week="mon-fri"),
            id=f"pm_{hour:02d}00",
            name=f"Portfolio Manager {hour:02d}:00 ET",
            misfire_grace_time=300,
        )

    print("[scheduler] Portfolio Manager scheduler started")
    print("[scheduler] Fires at: 9:30, 10:00, 11:00, 12:00, 13:00, 14:00, 15:00 ET (Mon–Fri)")
    try:
        scheduler.start()
    except KeyboardInterrupt:
        print("\n[scheduler] Stopped.")


if __name__ == "__main__":
    main()
