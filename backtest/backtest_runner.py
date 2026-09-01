"""Run a setup across multiple tickers and compare results side-by-side.

Usage:
    python backtest_runner.py                    # runs example setup on all default tickers
    python backtest_runner.py AAPL NVDA TSLA     # run on specific tickers

Outputs:
    - Summary comparison table
    - Per-ticker trade logs
    - Results saved to ./backtest_cache/results_<timestamp>.csv
"""

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from .backtester import Backtester, Setup
from .example_setups import build_example_setup, build_ema_pullback_setup
from config import get_tickers


def run_multi(
    tickers: list[str],
    setup: Setup,
    start_date: str = "2023-01-01",
    initial_equity: float = 100_000.0,
    show_trades: bool = False,
) -> pd.DataFrame:

    print(f"\n{'='*65}")
    print(f"MULTI-TICKER BACKTEST — {setup.name}")
    print(f"Period: {start_date} → today | Initial equity: ${initial_equity:,.0f}")
    print(f"{'='*65}\n")

    rows = []
    for ticker in tickers:
        print(f"Running {ticker}...")
        try:
            bt = Backtester(
                ticker=ticker,
                setup=setup,
                start_date=start_date,
                initial_equity=initial_equity,
                lookback_days=900,
            )
            metrics = bt.run()
            if show_trades:
                bt.print_report(metrics, show_trades=True)
            rows.append(metrics)
        except Exception as e:
            print(f"  ✗ {ticker} failed: {e}")
            rows.append({"ticker": ticker, "error": str(e)})

    df = pd.DataFrame(rows)

    # Print comparison table
    cols = [
        "ticker", "total_trades", "win_rate_pct", "total_return_pct",
        "avg_win_pct", "avg_loss_pct", "max_drawdown_pct", "sharpe_ratio",
    ]
    display_cols = [c for c in cols if c in df.columns]
    print(f"\n{'='*65}")
    print("COMPARISON TABLE")
    print(f"{'='*65}")
    print(df[display_cols].to_string(index=False))
    print(f"{'='*65}\n")

    # Save to CSV
    out_dir = Path("./backtest_cache")
    out_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"results_{ts}.csv"
    df.to_csv(out_file, index=False)
    print(f"Results saved to {out_file}")

    return df


if __name__ == "__main__":
    tickers = sys.argv[1:] if len(sys.argv) > 1 else get_tickers()

    # Switch setup here — e.g. build_ema_pullback_setup() or build_example_setup()
    setup = build_ema_pullback_setup()

    run_multi(tickers, setup, start_date="2023-01-01", show_trades=False)
