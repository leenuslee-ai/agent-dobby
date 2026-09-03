"""Persistence and retrieval functions for BacktestRun and BacktestTransaction."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from tools.db.session import get_session
from tools.db.models import BacktestRun, BacktestTransaction


def _f(v) -> float | None:
    """Cast numpy or other numeric types to plain Python float for SQLAlchemy."""
    return float(v) if v is not None else None


def _sanitize(d: dict) -> dict:
    """Convert numpy scalars to native Python types for JSON storage."""
    result = {}
    for k, v in d.items():
        try:
            result[k] = float(v) if hasattr(v, "__float__") and not isinstance(v, (str, bool)) else v
        except (TypeError, ValueError):
            result[k] = v
    return result


def save_backtest_run(
    setup_id: str,
    ticker: str,
    metrics: dict,
    trades: list,
    start_date: datetime,
    end_date: datetime,
    initial_cash: float = 100_000.0,
) -> str:
    """Persist a completed backtest run and its trade transactions.

    Args:
        setup_id:     ID of the setup used for this run.
        ticker:       Stock symbol the backtest was run against.
        metrics:      Summary metrics dict returned by Backtester._metrics().
        trades:       List of Trade objects from Backtester.trades.
        start_date:   First bar date of the backtest window.
        end_date:     Last bar date of the backtest window.
        initial_cash: Starting equity value.

    Returns:
        The UUID string of the newly created BacktestRun row.
    """
    run_id = str(uuid.uuid4())

    # Format trades in the same shape run_backtest returns — stored for later retrieval
    formatted_trades = [
        {
            "entry_date":  t.entry_date,
            "entry_price": round(float(t.entry_price), 2),
            "exit_date":   t.exit_date,
            "exit_price":  round(float(t.exit_price), 2),
            "pnl_pct":     round(float(t.pnl_pct), 2),
            "exit_reason": t.exit_reason,
            "result":      "win" if t.pnl_pct > 0 else "loss",
        }
        for t in trades
    ]

    # Store everything needed to reconstruct the run_backtest response shape
    extra_stats = _sanitize({
        k: v for k, v in metrics.items()
        if k not in {"final_equity", "total_return_pct", "sharpe_ratio", "max_drawdown_pct", "total_trades"}
    })
    extra_stats["trades"] = formatted_trades

    with get_session() as session:
        run = BacktestRun(
            id=run_id,
            setup_id=setup_id,
            ticker=ticker.upper(),
            start_date=start_date,
            end_date=end_date,
            initial_cash=_f(initial_cash),
            final_value=_f(metrics.get("final_equity")),
            total_return=_f(metrics.get("total_return_pct")),
            sharpe_ratio=_f(metrics.get("sharpe_ratio")),
            max_drawdown=_f(metrics.get("max_drawdown_pct")),
            total_trades=metrics.get("total_trades"),
            extra_stats=extra_stats,
        )
        session.add(run)

        for t in trades:
            session.add(BacktestTransaction(
                id=str(uuid.uuid4()),
                run_id=run_id,
                ticker=ticker.upper(),
                side="BUY",
                qty=round(float(t.shares), 6),
                price=round(float(t.entry_price), 4),
                pnl=round(float(t.pnl), 4),
                timestamp=datetime.strptime(t.entry_date, "%Y-%m-%d").replace(tzinfo=timezone.utc),
            ))

    return run_id


def get_backtest_run(run_id: str) -> dict | None:
    """Retrieve a BacktestRun by ID and reconstruct the run_backtest response shape.

    Returns:
        A dict with "summary" and "trades" matching the run_backtest tool output,
        or None if not found.
    """
    with get_session() as session:
        run = session.get(BacktestRun, run_id)
        if run is None:
            return None

        extra = run.extra_stats or {}

        # Reconstruct summary in the same shape as Backtester._metrics()
        summary = {
            "ticker":           run.ticker,
            "setup":            extra.get("setup", ""),
            "period":           extra.get("period", ""),
            "initial_equity":   run.initial_cash,
            "final_equity":     run.final_value,
            "total_return_pct": run.total_return,
            "total_trades":     run.total_trades,
            "win_rate_pct":     extra.get("win_rate_pct"),
            "avg_win_pct":      extra.get("avg_win_pct"),
            "avg_loss_pct":     extra.get("avg_loss_pct"),
            "best_trade_pct":   extra.get("best_trade_pct"),
            "worst_trade_pct":  extra.get("worst_trade_pct"),
            "max_drawdown_pct": run.max_drawdown,
            "sharpe_ratio":     run.sharpe_ratio,
            # DB-only fields the UI may find useful
            "run_id":           run.id,
            "setup_id":         run.setup_id,
            "created_at":       str(run.created_at),
        }

        return {
            "summary": summary,
            "trades":  extra.get("trades", []),
        }


def list_backtest_runs(ticker: str | None = None) -> list[dict]:
    """Return a summary list of backtest runs, optionally filtered by ticker.

    Returns:
        List of dicts with key run attributes, ordered most recent first.
    """
    from sqlalchemy import select
    with get_session() as session:
        stmt = select(BacktestRun).order_by(BacktestRun.created_at.desc())
        if ticker:
            stmt = stmt.where(BacktestRun.ticker == ticker.upper())
        runs = session.execute(stmt).scalars().all()
        return [
            {
                "run_id":           r.id,
                "ticker":           r.ticker,
                "setup_id":         r.setup_id,
                "setup":            (r.extra_stats or {}).get("setup", ""),
                "period":           (r.extra_stats or {}).get("period", ""),
                "total_trades":     r.total_trades,
                "total_return_pct": r.total_return,
                "sharpe_ratio":     r.sharpe_ratio,
                "max_drawdown_pct": r.max_drawdown,
                "created_at":       str(r.created_at),
            }
            for r in runs
        ]
