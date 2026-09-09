"""SPY/QQQ Positional Trader — EMA-50 state machine.

Manages a two-ticker portfolio (SPY and QQQ) through three states driven by
each ticker's position relative to its 50-day exponential moving average:

  ┌─────────┬────────────────────────┬────────────────────────────────────┬──────────────────────┐
  │ State   │ Name                   │ EMA-50 Condition                   │ Target Allocation    │
  ├─────────┼────────────────────────┼────────────────────────────────────┼──────────────────────┤
  │ A       │ Aggressive Growth      │ SPY above EMA-50 AND QQQ above     │ 50% SPY / 50% QQQ   │
  │ B       │ Defensive Value        │ SPY above EMA-50, QQQ below        │ 100% SPY             │
  │ C       │ Capital Preservation   │ SPY below EMA-50 (regardless QQQ)  │ 100% Cash            │
  └─────────┴────────────────────────┴────────────────────────────────────┴──────────────────────┘

EMA-50 is computed from the daily OHLCV history (Alpha Vantage, cached CSV).
During market hours the latest intraday price (Alpha Vantage 5-min feed) is
used as a live proxy for today's close; in simulation the daily close is used.

Live schedule (APScheduler, Mon–Fri US/Eastern):
  - Evaluate state every hour between 9:30 AM and 3:00 PM and log it.
  - Execute the rebalance at exactly 3:30 PM (30 min before market close).

Usage:
    python -m jobs.spyqqq_positional_trader               # live scheduler
    python -m jobs.spyqqq_positional_trader --now         # one evaluation + execute now
    python -m jobs.spyqqq_positional_trader --simulate    # 5-week sim ending 2026-09-01
    python -m jobs.spyqqq_positional_trader --simulate \\
        --start 2026-07-25 --end 2026-09-01               # custom date range
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.alphavantage.alphavantage_data import _fetch_daily_full
from tools.alphavantage.intraday_data import get_latest_price

# Alpaca client is imported lazily inside live-mode functions so that
# simulation runs do not require valid Alpaca credentials.

TICKERS          = ["SPY", "QQQ"]
EMA_PERIOD       = 50
MIN_TRADE_VALUE  = 1.0      # skip rebalance leg if notional < $1
SIM_INITIAL_CASH = 100_000.0


# ── EMA computation ───────────────────────────────────────────────────────────

def _compute_ema50_series(ticker: str) -> pd.Series:
    """Return a Series of daily EMA-50 values indexed by date for *ticker*."""
    df = _fetch_daily_full(ticker)
    return df["close"].ewm(span=EMA_PERIOD, adjust=False).mean().rename(f"ema50_{ticker}")


def _get_indicator_snapshot(
    sim_date: date | None = None,
    preloaded: dict[str, pd.DataFrame] | None = None,
) -> dict:
    """Return current prices and EMA-50 values for SPY and QQQ.

    In simulation mode (sim_date set) the data is sliced to that date so there
    is no lookahead.  In live mode the latest intraday price is used alongside
    the most recent daily EMA-50.

    Args:
        sim_date:   If set, slice history to this date (no lookahead).
        preloaded:  Optional pre-fetched {ticker: DataFrame} to avoid repeated
                    disk reads in the simulation loop.

    Returns:
        {
          "SPY": {"price": float, "ema50": float, "above_ema": bool},
          "QQQ": {"price": float, "ema50": float, "above_ema": bool},
        }
    """
    snapshot = {}
    for ticker in TICKERS:
        if preloaded and ticker in preloaded:
            daily_df = preloaded[ticker]
        else:
            daily_df = _fetch_daily_full(ticker)
        if sim_date is not None:
            daily_df = daily_df[daily_df.index.date <= sim_date]

        if daily_df.empty or len(daily_df) < EMA_PERIOD:
            raise ValueError(
                f"Not enough history for {ticker} "
                f"(need {EMA_PERIOD} bars, got {len(daily_df)})"
            )

        ema_series = daily_df["close"].ewm(span=EMA_PERIOD, adjust=False).mean()
        ema50      = float(ema_series.iloc[-1])

        # Price: for simulation use daily close; for live use intraday feed.
        price = get_latest_price(ticker, sim_date=sim_date)
        if price is None:
            raise ValueError(f"Could not get current price for {ticker}")

        snapshot[ticker] = {
            "price":     price,
            "ema50":     round(ema50, 4),
            "above_ema": price > ema50,
        }

    return snapshot


# ── State determination ───────────────────────────────────────────────────────

def determine_state(snapshot: dict) -> tuple[str, dict[str, float]]:
    """Return (state_label, target_allocation) from a price snapshot.

    state_label   : "A", "B-SPY", "B-QQQ", or "C"
    target_allocation: {"SPY": fraction, "QQQ": fraction}  (fractions sum to ≤1; rest is cash)
    """
    spy_above = snapshot["SPY"]["above_ema"]
    qqq_above = snapshot["QQQ"]["above_ema"]

    if spy_above and qqq_above:
        return "A", {"SPY": 0.50, "QQQ": 0.50}
    if spy_above and not qqq_above:
        return "B", {"SPY": 1.00, "QQQ": 0.00}
    # SPY below EMA-50 (whether QQQ is above or below) → preserve capital
    return     "C", {"SPY": 0.00, "QQQ": 0.00}


_STATE_NAMES = {
    "A": "Aggressive Growth",
    "B": "Defensive Value (100% SPY)",
    "C": "Capital Preservation (100% Cash)",
}


# ── Rebalance logic ───────────────────────────────────────────────────────────

def _compute_trades(
    current_positions: dict[str, float],   # {ticker: qty}
    cash: float,
    target_allocation: dict[str, float],   # {ticker: fraction}
    prices: dict[str, float],              # {ticker: price}
) -> list[dict]:
    """Return a list of trades needed to reach target_allocation.

    Sells are listed first so the cash freed up can fund subsequent buys.
    """
    total_value = cash + sum(
        current_positions.get(t, 0) * prices[t] for t in TICKERS
    )

    trades = []
    for ticker in TICKERS:
        target_value   = total_value * target_allocation.get(ticker, 0.0)
        current_value  = current_positions.get(ticker, 0.0) * prices[ticker]
        delta_value    = target_value - current_value

        if abs(delta_value) < MIN_TRADE_VALUE:
            continue

        side = "BUY" if delta_value > 0 else "SELL"
        qty  = abs(delta_value) / prices[ticker]
        trades.append({
            "ticker":        ticker,
            "side":          side,
            "qty":           round(qty, 6),
            "approx_value":  round(abs(delta_value), 2),
            "price":         prices[ticker],
        })

    # Execute sells before buys so cash is available for purchases.
    trades.sort(key=lambda t: 0 if t["side"] == "SELL" else 1)
    return trades


# ── Pretty log helpers ────────────────────────────────────────────────────────

def _log_separator(label: str = "") -> None:
    print(f"\n{'='*60}")
    if label:
        print(f"  {label}")
        print(f"{'='*60}")


def _log_snapshot(snapshot: dict, state: str, target: dict, as_of: str) -> None:
    print(f"\n  As of : {as_of}")
    for ticker, info in snapshot.items():
        arrow = "▲" if info["above_ema"] else "▼"
        print(
            f"  {ticker:4s}: price=${info['price']:>8.2f}  "
            f"EMA-50=${info['ema50']:>8.2f}  "
            f"{arrow} {'above' if info['above_ema'] else 'below'}"
        )
    print(f"\n  State : {state} — {_STATE_NAMES[state]}")
    alloc_str = " / ".join(
        f"{int(v*100)}% {t}" for t, v in target.items() if v > 0
    ) or "100% Cash"
    print(f"  Target: {alloc_str}")


# ── Live evaluation (hourly) ──────────────────────────────────────────────────

def evaluate_and_log() -> dict:
    """Compute current state and log it.  No trades are placed."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    _log_separator(f"SPY/QQQ Evaluation  {now}")

    snapshot = _get_indicator_snapshot()
    state, target = determine_state(snapshot)
    _log_snapshot(snapshot, state, target, as_of=now)
    print()
    return {"state": state, "target": target, "snapshot": snapshot}


# ── Live execution (3:30 PM ET) ───────────────────────────────────────────────

def execute_rebalance() -> dict:
    """Determine state, compute required trades, and execute them via Alpaca."""
    from tools.alpaca.spyqqq_client import (
        get_account, get_positions, place_order, poll_order, cancel_all_orders
    )

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    _log_separator(f"SPY/QQQ Rebalance Execution  {now}")

    snapshot = _get_indicator_snapshot()
    state, target = determine_state(snapshot)
    prices = {t: snapshot[t]["price"] for t in TICKERS}

    account  = get_account()
    cash     = account["cash"]
    raw_positions = get_positions()
    current_qtys  = {t: raw_positions.get(t, {}).get("qty", 0.0) for t in TICKERS}

    _log_snapshot(snapshot, state, target, as_of=now)
    print(f"\n  Cash          : ${cash:>12,.2f}")
    print(f"  Portfolio val : ${account['portfolio_value']:>12,.2f}")
    for t in TICKERS:
        print(f"  {t} qty         : {current_qtys[t]:>10.4f} shares")

    trades = _compute_trades(current_qtys, cash, target, prices)

    if not trades:
        print("\n  No rebalancing needed — portfolio already at target.")
        return {"state": state, "trades": [], "errors": []}

    # Cancel any open orders before placing new ones.
    cancelled = cancel_all_orders()
    if cancelled:
        print(f"\n  Cancelled {cancelled} existing open order(s).")

    print(f"\n  Trades to execute ({len(trades)}):")
    executed, errors = [], []
    for trade in trades:
        print(
            f"    {trade['side']:4s} {trade['qty']:.4f} x {trade['ticker']}"
            f"  @ ~${trade['price']:.2f}  (≈${trade['approx_value']:,.2f})"
        )
        try:
            order = place_order(trade["ticker"], trade["qty"], trade["side"])
            fill  = poll_order(order["order_id"])
            print(
                f"      → {fill['status']}  "
                f"qty={fill['filled_qty']}  "
                f"avg=${fill['filled_avg_price']:.2f}"
            )
            executed.append({**trade, "order": order, "fill": fill})
        except Exception as exc:
            msg = f"{trade['ticker']} {trade['side']}: {exc}"
            print(f"      → ERROR: {msg}")
            errors.append(msg)

    print()
    return {"state": state, "trades": executed, "errors": errors}


# ── Simulation (back-test over a date range) ──────────────────────────────────

def run_simulation(start: date, end: date) -> list[dict]:
    """Simulate the strategy day-by-day from *start* to *end*.

    No Alpaca API calls are made — all trades are applied to a virtual
    portfolio starting with SIM_INITIAL_CASH.
    """
    _log_separator(f"SPY/QQQ Simulation  {start} → {end}")

    # Pre-fetch full history once (avoids repeated API/cache reads).
    print("  Loading SPY and QQQ daily history...")
    daily = {t: _fetch_daily_full(t) for t in TICKERS}
    print(f"  SPY: {len(daily['SPY'])} bars   QQQ: {len(daily['QQQ'])} bars\n")

    business_days = [
        start + timedelta(days=d)
        for d in range((end - start).days + 1)
        if (start + timedelta(days=d)).weekday() < 5   # Mon–Fri only
    ]

    # Virtual portfolio state.
    portfolio = {"cash": SIM_INITIAL_CASH, "SPY": 0.0, "QQQ": 0.0}
    prev_state = None
    results    = []

    print(f"  {'Date':<12} {'State':<8} {'SPY Qty':>8} {'SPY Val':>10} {'QQQ Qty':>8} {'QQQ Val':>10} {'Cash':>11} {'Portfolio':>12}  Trades")
    print(f"  {'-'*12} {'-'*8} {'-'*8} {'-'*10} {'-'*8} {'-'*10} {'-'*11} {'-'*12}  ------")

    for sim_date in business_days:
        try:
            snapshot = _get_indicator_snapshot(sim_date=sim_date, preloaded=daily)
        except ValueError as exc:
            print(f"  {sim_date}  SKIP  ({exc})")
            continue

        state, target = determine_state(snapshot)
        prices = {t: snapshot[t]["price"] for t in TICKERS}

        # Rebalance only when state changes (or on the very first day).
        trades_today = []
        if state != prev_state:
            trades_today = _simulate_apply_trades(portfolio, target, prices)
            prev_state   = state

        # Portfolio value after any rebalancing.
        port_value = portfolio["cash"] + sum(
            portfolio[t] * prices[t] for t in TICKERS
        )

        spy_qty = portfolio["SPY"]
        qqq_qty = portfolio["QQQ"]
        spy_val = spy_qty * prices["SPY"]
        qqq_val = qqq_qty * prices["QQQ"]
        cash    = max(portfolio["cash"], 0.0)   # avoid -$0.00 from float drift

        trade_summary = ", ".join(
            f"{t['side']} {t['qty']:.2f} {t['ticker']}" for t in trades_today
        ) or "—"

        print(
            f"  {sim_date!s:<12} {state:<8} "
            f"{spy_qty:>8.2f} ${spy_val:>9,.2f} "
            f"{qqq_qty:>8.2f} ${qqq_val:>9,.2f} "
            f"${cash:>10,.2f} ${port_value:>11,.2f}  {trade_summary}"
        )

        results.append({
            "date":            str(sim_date),
            "state":           state,
            "spy_price":       prices["SPY"],
            "qqq_price":       prices["QQQ"],
            "spy_qty":         spy_qty,
            "spy_value":       round(spy_val, 2),
            "qqq_qty":         qqq_qty,
            "qqq_value":       round(qqq_val, 2),
            "cash":            round(cash, 2),
            "portfolio_value": round(port_value, 2),
            "trades":          trades_today,
        })

    # ── Summary ───────────────────────────────────────────────────────────────
    if results:
        first_val = results[0]["portfolio_value"]
        last_val  = results[-1]["portfolio_value"]
        ret_pct   = (last_val - first_val) / first_val * 100
        _log_separator("Simulation Summary")
        print(f"  Period          : {start} → {end}  ({len(results)} trading days)")
        print(f"  Starting value  : ${first_val:>12,.2f}")
        print(f"  Ending value    : ${last_val:>12,.2f}")
        print(f"  Total return    : {ret_pct:>+.2f}%")

        state_counts: dict[str, int] = {}
        for r in results:
            state_counts[r["state"]] = state_counts.get(r["state"], 0) + 1
        print("\n  Days per state:")
        for st, count in sorted(state_counts.items()):
            print(f"    {st:<8} {_STATE_NAMES[st]:<30} {count:>3} days")
        print()

    return results


def _simulate_apply_trades(
    portfolio: dict,
    target_allocation: dict[str, float],
    prices: dict[str, float],
) -> list[dict]:
    """Apply target_allocation to portfolio in-place and return the trade list.

    Sells are applied before buys to keep the cash balance valid.
    """
    total_value = portfolio["cash"] + sum(
        portfolio[t] * prices[t] for t in TICKERS
    )

    trades = _compute_trades(
        current_positions={t: portfolio[t] for t in TICKERS},
        cash=portfolio["cash"],
        target_allocation=target_allocation,
        prices=prices,
    )

    for trade in trades:
        t     = trade["ticker"]
        value = trade["qty"] * prices[t]
        if trade["side"] == "SELL":
            portfolio[t]      -= trade["qty"]
            portfolio["cash"] += value
        else:
            portfolio[t]      += trade["qty"]
            portfolio["cash"] -= value

    # Correct for floating-point drift.
    for t in TICKERS:
        if portfolio[t] < 1e-6:
            portfolio[t] = 0.0

    return trades


# ── APScheduler (live mode) ───────────────────────────────────────────────────

def start_scheduler() -> None:
    """Start the live APScheduler: hourly evaluation + 3:30 PM execution."""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = BlockingScheduler(timezone="US/Eastern")

    # Hourly evaluation: 9:30, 10:00, 11:00, 12:00, 13:00, 14:00, 15:00
    scheduler.add_job(
        evaluate_and_log,
        CronTrigger(
            day_of_week="mon-fri",
            hour="9,10,11,12,13,14,15",
            minute="30,0,0,0,0,0,0",
        ),
        id="spyqqq_evaluate",
        name="SPY/QQQ hourly evaluation",
        misfire_grace_time=900,   # 15 min — covers late startup without re-firing stale slots
    )

    # Single daily execution at 3:30 PM ET.
    scheduler.add_job(
        execute_rebalance,
        CronTrigger(day_of_week="mon-fri", hour=15, minute=30),
        id="spyqqq_execute",
        name="SPY/QQQ 3:30 PM rebalance",
        misfire_grace_time=120,
    )

    print("SPY/QQQ Positional Trader scheduler started.")
    print("  Hourly evaluation : 9:30, 10:00 … 15:00 ET (Mon–Fri)")
    print("  Trade execution   : 15:30 ET (Mon–Fri)\n")
    scheduler.start()


# ── CLI entry point ───────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="SPY/QQQ EMA-50 positional trader",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--now",
        action="store_true",
        help="Run one evaluation and execute immediately (live Alpaca account).",
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Run a simulation over a historical date range (no Alpaca calls).",
    )
    parser.add_argument(
        "--start",
        default="2026-07-25",
        help="Simulation start date YYYY-MM-DD (default: 5 weeks before --end).",
    )
    parser.add_argument(
        "--end",
        default="2026-09-01",
        help="Simulation end date YYYY-MM-DD (default: 2026-09-01).",
    )
    args = parser.parse_args()

    if args.simulate:
        start = date.fromisoformat(args.start)
        end   = date.fromisoformat(args.end)
        run_simulation(start, end)

    elif args.now:
        evaluate_and_log()
        print("\nExecuting rebalance now...\n")
        execute_rebalance()

    else:
        start_scheduler()


if __name__ == "__main__":
    main()
