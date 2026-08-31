"""Custom backtester that evaluates your trading setup rules against historical data.

Supports:
  - Condition-by-condition setup evaluation (mirrors portfolio_manager_agent.py)
  - Position sizing: fixed shares, fixed dollar amount, or % of equity
  - Stop loss and take profit (% from entry)
  - Full trade log with entry/exit reasons
  - Performance metrics: total return, win rate, avg gain/loss, max drawdown, Sharpe

Usage:
    python backtester.py                        # runs built-in example setup on NVDA
    python backtester.py AAPL 2024-01-01        # backtest AAPL from a start date

Or import and define your own setup:
    from backtester import Backtester, Setup
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

import numpy as np
import pandas as pd

from tools.alphavantage.alphavantage_data import get_ohlcv_with_indicators
from tools import Setup, setup_from_dict


# ── Trade record ──────────────────────────────────────────────────────────────

@dataclass
class Trade:
    ticker: str
    entry_date: str
    entry_price: float
    exit_date: str | None = None
    exit_price: float | None = None
    shares: float = 0.0
    exit_reason: str = ""
    entry_conditions_met: list[str] = field(default_factory=list)

    @property
    def pnl(self) -> float:
        if self.exit_price is None:
            return 0.0
        return (self.exit_price - self.entry_price) * self.shares

    @property
    def pnl_pct(self) -> float:
        if self.exit_price is None or self.entry_price == 0:
            return 0.0
        return (self.exit_price - self.entry_price) / self.entry_price * 100


# ── Backtester ────────────────────────────────────────────────────────────────

class Backtester:
    def __init__(
        self,
        ticker: str,
        setup: Setup,
        start_date: str | None = None,
        end_date: str | None = None,
        initial_equity: float = 100_000.0,
        lookback_days: int = 730,
    ):
        self.ticker = ticker.upper()
        self.setup = setup
        self.initial_equity = initial_equity
        self.equity = initial_equity
        self.trades: list[Trade] = []
        self.equity_curve: list[float] = []

        df = get_ohlcv_with_indicators(self.ticker, lookback_days=lookback_days)

        if start_date:
            df = df[df.index >= pd.Timestamp(start_date)]
        if end_date:
            df = df[df.index <= pd.Timestamp(end_date)]
        self.df = df

    def _calc_shares(self, price: float) -> float:
        if self.setup.position_type == "shares":
            return self.setup.position_value
        elif self.setup.position_type == "dollars":
            return self.setup.position_value / price
        else:  # equity_pct
            return (self.equity * self.setup.position_value) / price

    def run(self) -> dict:
        position: Trade | None = None
        stop_price: float = 0.0
        tp_price: float | None = None

        for date, row in self.df.iterrows():
            price = row["close"]
            date_str = str(date.date())

            # ── Manage open position ──────────────────────────────────────────
            if position is not None:
                exit_reason = None

                # Stop loss
                if price <= stop_price:
                    exit_reason = f"stop_loss ({stop_price:.2f})"

                # Take profit
                elif tp_price and price >= tp_price:
                    exit_reason = f"take_profit ({tp_price:.2f})"

                # Setup exit conditions
                else:
                    for label, cond_fn in self.setup.exit_conditions:
                        try:
                            if cond_fn(row):
                                exit_reason = label
                                break
                        except Exception:
                            pass

                if exit_reason:
                    position.exit_date = date_str
                    position.exit_price = price
                    position.exit_reason = exit_reason
                    self.equity += position.pnl
                    self.trades.append(position)
                    position = None

            # ── Check entry conditions ────────────────────────────────────────
            if position is None:
                met = []
                all_met = True
                for label, cond_fn in self.setup.entry_conditions:
                    try:
                        result = bool(cond_fn(row))
                        print("Condition")
                        print(row.to_string())
                    except Exception:
                        result = False
                    if result:
                        met.append(f"✓ {label}")
                    else:
                        all_met = False
                        met.append(f"✗ {label}")

                if all_met:
                    shares = self._calc_shares(price)
                    stop_price = price * (1 - self.setup.stop_loss_pct)
                    tp_price = (price * (1 + self.setup.take_profit_pct)
                                if self.setup.take_profit_pct else None)
                    position = Trade(
                        ticker=self.ticker,
                        entry_date=date_str,
                        entry_price=price,
                        shares=shares,
                        entry_conditions_met=met,
                    )

            self.equity_curve.append(self.equity + (
                (price - position.entry_price) * position.shares if position else 0
            ))

        # Close any open position at last bar
        if position is not None:
            last_price = self.df["close"].iloc[-1]
            position.exit_date = str(self.df.index[-1].date())
            position.exit_price = last_price
            position.exit_reason = "end_of_data"
            self.equity += position.pnl
            self.trades.append(position)

        return self._metrics()

    def _metrics(self) -> dict:
        if not self.trades:
            return {"error": "No trades were triggered. Check your setup conditions."}

        pnls = [t.pnl_pct for t in self.trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        equity_arr = np.array(self.equity_curve)
        peak = np.maximum.accumulate(equity_arr)
        drawdown = (equity_arr - peak) / peak * 100
        max_drawdown = drawdown.min()

        returns = pd.Series(self.equity_curve).pct_change().dropna()
        sharpe = (returns.mean() / returns.std() * np.sqrt(252)) if returns.std() > 0 else 0.0

        return {
            "ticker": self.ticker,
            "setup": self.setup.name,
            "period": f"{self.df.index[0].date()} → {self.df.index[-1].date()}",
            "initial_equity": self.initial_equity,
            "final_equity": round(self.equity, 2),
            "total_return_pct": round((self.equity - self.initial_equity) / self.initial_equity * 100, 2),
            "total_trades": len(self.trades),
            "win_rate_pct": round(len(wins) / len(pnls) * 100, 1),
            "avg_win_pct": round(np.mean(wins), 2) if wins else 0,
            "avg_loss_pct": round(np.mean(losses), 2) if losses else 0,
            "best_trade_pct": round(max(pnls), 2),
            "worst_trade_pct": round(min(pnls), 2),
            "max_drawdown_pct": round(max_drawdown, 2),
            "sharpe_ratio": round(sharpe, 2),
        }

    def print_report(self, metrics: dict, show_trades: bool = True):
        print(f"\n{'='*65}")
        print(f"BACKTEST REPORT — {metrics.get('ticker')} — {metrics.get('setup')}")
        print(f"{'='*65}")
        if "error" in metrics:
            print(f"  {metrics['error']}")
            return

        print(f"  Period          : {metrics['period']}")
        print(f"  Initial equity  : ${metrics['initial_equity']:,.0f}")
        print(f"  Final equity    : ${metrics['final_equity']:,.0f}")
        print(f"  Total return    : {metrics['total_return_pct']:+.2f}%")
        print(f"  Total trades    : {metrics['total_trades']}")
        print(f"  Win rate        : {metrics['win_rate_pct']}%")
        print(f"  Avg win         : {metrics['avg_win_pct']:+.2f}%")
        print(f"  Avg loss        : {metrics['avg_loss_pct']:+.2f}%")
        print(f"  Best trade      : {metrics['best_trade_pct']:+.2f}%")
        print(f"  Worst trade     : {metrics['worst_trade_pct']:+.2f}%")
        print(f"  Max drawdown    : {metrics['max_drawdown_pct']:.2f}%")
        print(f"  Sharpe ratio    : {metrics['sharpe_ratio']:.2f}")

        if show_trades and self.trades:
            print(f"\n{'─'*65}")
            print("TRADE LOG:")
            print(f"{'─'*65}")
            for t in self.trades:
                print(
                    f"  {t.entry_date} → {t.exit_date} | "
                    f"entry=${t.entry_price:.2f} exit=${t.exit_price:.2f} | "
                    f"P&L={t.pnl_pct:+.2f}% | exit={t.exit_reason}"
                )
        print(f"{'='*65}\n")


# ── Example setup (mirrors the portfolio_manager_agent.py default setup) ──────

def build_example_setup() -> Setup:
    return Setup(
        name="RSI Oversold + MACD Crossover + Trend Filter",
        entry_conditions=[
            ("RSI(14) < 35 (oversold)",          lambda r: r["rsi"] < 35),
            ("MACD crossover up",                 lambda r: bool(r["macd_crossover_up"])),
            ("Price above SMA(50)",               lambda r: r["price_above_sma50"]),
            ("ADX(14) > 20 (trending market)",    lambda r: r["adx"] > 20),
        ],
        exit_conditions=[
            ("RSI(14) > 70 (overbought)",         lambda r: r["rsi"] > 70),
            ("MACD crossover down",               lambda r: bool(r["macd_crossover_down"])),
        ],
        stop_loss_pct=0.05,        # 5% stop loss
        take_profit_pct=0.15,      # 15% take profit
        position_type="equity_pct",
        position_value=0.10,       # risk 10% of equity per trade
    )


# ── 20 EMA Pullback setup ─────────────────────────────────────────────────────

def build_ema_pullback_setup() -> Setup:
    """20 EMA Pullback swing trade setup.

    Entry logic:
      1. EMA-20 is rising (uptrend confirmed)
      2. Price pulled back and touched or pierced the EMA-20 on the low
      3. Candle closed back above EMA-20 (recovery)
      4. Reversal candle: hammer OR bullish engulfing right at the line

    Stop loss: 3% below entry (approximates "just under the EMA / swing low")
    Target:    8% above entry (approximates "previous recent high")

    Tune stop_loss_pct and take_profit_pct to match the average swing size
    of the stocks you trade.
    """
    return Setup(
        name="20 EMA Pullback",
        entry_conditions=[
            ("EMA-20 is rising",               lambda r: bool(r["ema20_rising"])),
            ("Price above SMA-50 (uptrend)",   lambda r: bool(r["price_above_sma50"])),
            ("Low touched EMA-20 (pullback)",  lambda r: bool(r["touched_ema20"])),
            ("Closed back above EMA-20",       lambda r: bool(r["closed_above_ema20"])),
            ("Reversal candle (hammer or engulf)",
             lambda r: bool(r["hammer"]) or bool(r["bullish_engulfing"])),
        ],
        exit_conditions=[
            ("RSI overbought > 70",            lambda r: r["rsi"] > 70),
            ("Price crosses back below EMA-20",lambda r: r["close"] < r["ema_20"]),
        ],
        stop_loss_pct=0.03,        # 3% — just under the EMA / swing low
        take_profit_pct=0.08,      # 8% — approximate previous high
        position_type="equity_pct",
        position_value=0.10,
    )


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ticker     = sys.argv[1] if len(sys.argv) > 1 else "NVDA"
    start_date = sys.argv[2] if len(sys.argv) > 2 else "2023-01-01"

    setup = build_example_setup()

    bt = Backtester(
        ticker=ticker,
        setup=setup,
        start_date=start_date,
        initial_equity=100_000,
        lookback_days=200,
    )

    metrics = bt.run()
    bt.print_report(metrics, show_trades=True)
