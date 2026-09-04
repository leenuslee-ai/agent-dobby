"""Run PortfolioManagerAgent for every trading day in a date range.

Advances MOCK_SIMULATION_DATE one business day at a time, spawning a
subprocess per day so each run gets a clean import with the correct date.

Usage:
    python3 -m jobs.pm_simulation_runner --account <account_id>
    python3 -m jobs.pm_simulation_runner --account <account_id> --start 2026-09-04 --end 2026-09-30
    python3 -m jobs.pm_simulation_runner --account <account_id> --start 2026-09-04 --end 2026-10-31 --pause 2
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import date, timedelta


def _business_days(start: date, end: date) -> list[date]:
    days, cur = [], start
    while cur <= end:
        if cur.weekday() < 5:   # Mon–Fri
            days.append(cur)
        cur += timedelta(days=1)
    return days


def run_simulation(account_id: str, start: date, end: date, pause: float = 1.0):
    days = _business_days(start, end)
    print(f"\nSimulation: {start} → {end}  ({len(days)} trading days)")
    print(f"Account   : {account_id}\n{'='*60}\n")

    for i, sim_date in enumerate(days, 1):
        print(f"\n[{i}/{len(days)}] sim_date={sim_date}")
        env = {**os.environ, "MOCK_SIMULATION_DATE": str(sim_date), "MOCK_STOCKS_ENABLED": "true"}
        result = subprocess.run(
            [sys.executable, "-m", "agents.portfolio_manager_agent", account_id],
            env=env,
        )
        if result.returncode != 0:
            print(f"  [WARNING] Day {sim_date} exited with code {result.returncode}")

        if pause > 0 and i < len(days):
            time.sleep(pause)

    print(f"\n{'='*60}")
    print(f"Simulation complete. {len(days)} days processed.")


def main():
    parser = argparse.ArgumentParser(description="PM agent daily simulation runner")
    parser.add_argument("--account", required=True, help="Portfolio account UUID")
    parser.add_argument("--start",   default="2026-09-04", help="Start date YYYY-MM-DD")
    parser.add_argument("--end",     default="2026-09-30", help="End date YYYY-MM-DD")
    parser.add_argument("--pause",   type=float, default=1.0,
                        help="Seconds to pause between days (default 1.0)")
    args = parser.parse_args()

    run_simulation(
        account_id=args.account,
        start=date.fromisoformat(args.start),
        end=date.fromisoformat(args.end),
        pause=args.pause,
    )


if __name__ == "__main__":
    main()
