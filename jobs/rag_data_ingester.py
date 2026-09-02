"""Scheduled job: ingest RAG news data 3x daily (7AM, 12PM, 8PM).

Tracks the last successful run timestamp in a state file so each run only
pulls articles newer than the previous run.

Usage:
    python -m jobs.rag_data_ingester          # run once now
    python -m jobs.rag_data_ingester --reset  # clear saved state and run from scratch
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from tools.rag_yahoo.pipeline import run_pipeline

STATE_FILE = Path(__file__).parent / ".rag_ingester_state.json"


def _load_since() -> datetime | None:
    if STATE_FILE.exists():
        data = json.loads(STATE_FILE.read_text())
        ts = data.get("last_run_at")
        if ts:
            return datetime.fromisoformat(ts)
    return None


def _save_since(ts: datetime):
    STATE_FILE.write_text(json.dumps({"last_run_at": ts.isoformat()}))


def ingest():
    since = _load_since()
    now = datetime.now(timezone.utc)
    label = since.strftime("%Y-%m-%d %H:%M UTC") if since else "beginning"
    print(f"\n[rag_data_ingester] {now.strftime('%Y-%m-%d %H:%M UTC')} — ingesting since {label}")
    try:
        run_pipeline(since=since)
        _save_since(now)
        print(f"[rag_data_ingester] Done. Next run will pull articles after {now.strftime('%Y-%m-%d %H:%M UTC')}")
    except Exception as e:
        print(f"[rag_data_ingester] ERROR: {e}", file=sys.stderr)
        raise


def main():
    parser = argparse.ArgumentParser(description="RAG news ingestion scheduler")
    parser.add_argument("--reset", action="store_true", help="Clear saved state and run once from scratch")
    parser.add_argument("--now", action="store_true", help="Run once immediately then exit")
    args = parser.parse_args()

    if args.reset and STATE_FILE.exists():
        STATE_FILE.unlink()
        print("[rag_data_ingester] State cleared.")

    if args.now or args.reset:
        ingest()
        return

    scheduler = BlockingScheduler(timezone="US/Eastern")
    for hour in (7, 12, 20):
        scheduler.add_job(
            ingest,
            CronTrigger(hour=hour, minute=0, day_of_week="mon-fri"),
            id=f"rag_ingest_{hour:02d}00",
            name=f"RAG ingest {hour:02d}:00 ET",
            misfire_grace_time=300,
        )

    print("[rag_data_ingester] Scheduler started — running at 7AM, 12PM, 8PM ET (Mon–Fri)")
    print(f"[rag_data_ingester] Current state: since = {_load_since() or 'beginning'}")
    try:
        scheduler.start()
    except KeyboardInterrupt:
        print("\n[rag_data_ingester] Stopped.")


if __name__ == "__main__":
    main()
