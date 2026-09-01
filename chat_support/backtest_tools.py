"""LangChain tools for running and retrieving backtests."""

from __future__ import annotations

from datetime import datetime, timedelta

from langchain_core.tools import tool

from backtest import Backtester, SetupStore, get_ohlcv_with_indicators, setup_from_dict
from db.backtest_run_data import get_backtest_run, list_backtest_runs as _list_backtest_runs

_store = SetupStore()


def _candle_bars(ticker: str, days: int) -> list[dict]:
    """Return OHLCV bars for the last N days (no volume — used for chart overlays)."""
    df = get_ohlcv_with_indicators(ticker, lookback_days=days)
    return [
        {
            "date":  str(idx.date()),
            "open":  round(row["open"],  2),
            "high":  round(row["high"],  2),
            "low":   round(row["low"],   2),
            "close": round(row["close"], 2),
        }
        for idx, row in df.iterrows()
    ]


@tool
def run_backtest(ticker: str, days: int, setup_name: str) -> dict:
    """Run a backtest of a named trading setup against real historical data.

    Args:
        ticker:     Stock symbol (e.g. "AAPL")
        days:       Number of calendar days of history to test against
        setup_name: Name of a setup stored in the setup database

    Returns:
        JSON with summary metrics, trade log, and the underlying candle data.
    """
    record = _store.get(setup_name)
    if record is None:
        available = [s["name"] for s in _store.list()]
        return {
            "error":     f"Setup '{setup_name}' not found in the database.",
            "available": available,
        }

    definition = record["definition"]
    definition.setdefault("name", record["name"])
    setup = setup_from_dict(definition)
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    bt = Backtester(
        ticker=ticker,
        setup=setup,
        setup_id=record["id"],
        start_date=start_date,
        lookback_days=days + 300,   # extra history for indicator warmup
    )
    metrics = bt.run()

    if "error" in metrics:
        return {"responseType": "BackTestResults", "error": metrics["error"]}

    trades = [
        {
            "entry_date":  t.entry_date,
            "entry_price": round(t.entry_price, 2),
            "exit_date":   t.exit_date,
            "exit_price":  round(t.exit_price, 2),
            "pnl_pct":     round(t.pnl_pct, 2),
            "exit_reason": t.exit_reason,
            "result":      "win" if t.pnl_pct > 0 else "loss",
        }
        for t in bt.trades
    ]

    return {
        "responseType":      "BackTestResults",
        "run_id":            metrics.get("run_id"),
        "summary":           metrics,
        "trades":            trades,
        "candle_data":       _candle_bars(ticker, days),
        "already_formatted": True,
    }


@tool
def list_backtest_runs(ticker: str = "") -> dict:
    """List saved backtest runs, optionally filtered by ticker.

    Use this tool when the user wants to see past backtest runs.
    Examples:
      - "Show me all backtest runs"
      - "List backtests for NVDA"
      - "What runs do I have for AAPL?"

    Args:
        ticker: Stock symbol to filter by (leave empty to return all runs).

    Returns:
        JSON with a list of backtest run summaries.
    """
    runs = _list_backtest_runs(ticker=ticker or None)
    return {
        "responseType":      "BacktestRunList",
        "count":             len(runs),
        "ticker":            ticker.upper() if ticker else "ALL",
        "runs":              runs,
        "already_formatted": True,
    }


@tool
def get_backtest_result(run_id: str) -> dict:
    """Retrieve a previously saved backtest run by its run ID, including trades
    and the candle bar data for the ticker over the backtest period.

    Use this tool when the user wants to review or revisit a past backtest run.
    Examples:
      - "Show me the results for run abc-123"
      - "Get backtest run abc-123"

    Args:
        run_id: The UUID of the backtest run (returned by run_backtest).

    Returns:
        JSON with the run summary, trade transactions, and candle bar data.
    """
    data = get_backtest_run(run_id)
    if data is None:
        return {"responseType": "BackTestResults", "error": f"Run '{run_id}' not found."}

    summary = data["summary"]
    period  = summary.get("period", "")
    # Derive day count from stored period string "YYYY-MM-DD → YYYY-MM-DD"
    try:
        parts = period.split("→")
        start = datetime.fromisoformat(parts[0].strip())
        end   = datetime.fromisoformat(parts[1].strip())
        days  = max((end - start).days, 1)
    except Exception:
        days = 365

    return {
        "responseType":      "BackTestResults",
        "run_id":            run_id,
        "summary":           summary,
        "trades":            data["trades"],
        "candle_data":       _candle_bars(summary["ticker"], days),
        "already_formatted": True,
    }


BACKTEST_TOOLS = [run_backtest, list_backtest_runs, get_backtest_result]
