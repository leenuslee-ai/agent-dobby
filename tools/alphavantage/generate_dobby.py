"""Generate realistic synthetic OHLCV data for all mock demo tickers.

Strategy:
  - Alternating down/flat/up/flat cycles drive RSI(14) through oversold (<30)
    and overbought (>70) extremes, targeting 6-10 trades/year on Daily-RSI-14.
  - Noise (Student-t) + occasional event spikes add realism.
  - The cumulative drift is corrected to exactly match a target end-price,
    giving each ticker a plausible and controllable price trajectory.
  - Scaling log-returns by a constant doesn't change RSI (avg_gain/avg_loss
    ratio is preserved), so this correction is safe.

Data runs 2021-09-01 → 2026-11-30 (includes 3 future months for
PortfolioManagerAgent forward-simulation).

Run:
    python3 -m tools.alphavantage.generate_dobby
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)

START = "2021-09-01"
END   = "2026-11-30"


# ── Ticker personalities ───────────────────────────────────────────────────────
# target_end: price at 2026-11-30. Sets the long-run trend direction.
# down_amp / up_amp: log-scale magnitude of each oscillation phase.
#   Must be ~0.12–0.17 to reliably push RSI(14) past 30/70 thresholds.
# miss_prob: fraction of cycles that are shallow (amplitude halved) so not
#   every cycle triggers RSI extremes — adds irregularity.
TICKERS: dict[str, dict] = {
    "DOBBY": {
        "start_price": 100.0,
        "target_end":  125.0,   # mild uptrend ~4%/yr
        "daily_vol":   0.010,
        "down_bars":   (10, 16),
        "down_amp":    (0.13, 0.17),
        "up_bars":     (12, 20),
        "up_amp":      (0.13, 0.17),
        "flat_bars":   (3, 8),
        "miss_prob":   0.15,
        "seed": 42,
    },
    "OWALA": {
        "start_price": 55.0,
        "target_end":  95.0,    # growth stock ~10%/yr
        "daily_vol":   0.011,
        "down_bars":   (10, 15),
        "down_amp":    (0.14, 0.18),
        "up_bars":     (12, 20),
        "up_amp":      (0.14, 0.18),
        "flat_bars":   (2, 6),
        "miss_prob":   0.05,
        "seed": 7,
    },
    "MINI": {
        "start_price": 30.0,
        "target_end":  32.0,    # near-flat ~1%/yr
        "daily_vol":   0.008,
        "down_bars":   (12, 18),
        "down_amp":    (0.12, 0.16),
        "up_bars":     (14, 22),
        "up_amp":      (0.12, 0.16),
        "flat_bars":   (4, 10),
        "miss_prob":   0.20,
        "seed": 13,
    },
    "LUCAS": {
        "start_price": 180.0,
        "target_end":  130.0,   # downtrend ~-5%/yr
        "daily_vol":   0.014,   # reduce noise so stop-loss isn't triggered as often
        "down_bars":   (10, 15),
        "down_amp":    (0.14, 0.18),
        "up_bars":     (12, 18),
        "up_amp":      (0.12, 0.16),
        "flat_bars":   (2, 5),
        "miss_prob":   0.05,
        "seed": 99,
    },
    "PILLOW": {
        "start_price": 75.0,
        "target_end":  105.0,   # moderate uptrend ~6%/yr
        "daily_vol":   0.011,
        "down_bars":   (11, 17),
        "down_amp":    (0.14, 0.17),
        "up_bars":     (13, 20),
        "up_amp":      (0.14, 0.17),
        "flat_bars":   (3, 7),
        "miss_prob":   0.08,
        "seed": 55,
    },
}


def _generate_returns(cfg: dict, n: int) -> np.ndarray:
    rng     = np.random.default_rng(cfg["seed"])
    returns = np.zeros(n)
    i       = 0
    phase   = rng.choice(["down", "flat_bottom", "up", "flat_top"])

    while i < n:
        rem = n - i

        if phase == "down":
            bars = min(int(rng.uniform(*cfg["down_bars"])), rem)
            amp  = rng.uniform(*cfg["down_amp"])
            if rng.random() < cfg["miss_prob"]:
                amp *= 0.40
            w = np.abs(rng.normal(1.0, 0.25, bars)).clip(0.2, 2.5)
            returns[i:i + bars] -= amp * w / w.sum()
            i += bars; phase = "flat_bottom"

        elif phase == "flat_bottom":
            bars = min(int(rng.uniform(*cfg["flat_bars"])), rem)
            returns[i:i + bars] += rng.normal(0, cfg["daily_vol"] * 0.3, bars)
            i += bars; phase = "up"

        elif phase == "up":
            bars = min(int(rng.uniform(*cfg["up_bars"])), rem)
            amp  = rng.uniform(*cfg["up_amp"])
            if rng.random() < cfg["miss_prob"]:
                amp *= 0.40
            w = np.abs(rng.normal(1.0, 0.25, bars)).clip(0.2, 2.5)
            returns[i:i + bars] += amp * w / w.sum()
            i += bars; phase = "flat_top"

        elif phase == "flat_top":
            bars = min(int(rng.uniform(*cfg["flat_bars"])), rem)
            returns[i:i + bars] += rng.normal(0, cfg["daily_vol"] * 0.3, bars)
            i += bars; phase = "down"

    # Add noise + occasional event spikes
    noise  = rng.standard_t(df=5, size=n) * cfg["daily_vol"]
    spikes = rng.random(n) < (5 / 252)
    noise += spikes * rng.choice([-1, 1], size=n) * rng.uniform(0.02, 0.06, size=n)
    returns += np.clip(noise, -0.10, 0.10)

    # Correct cumulative drift so price lands exactly at target_end.
    # Adding a constant to every return shifts both gains and losses equally,
    # preserving the avg_gain/avg_loss ratio and therefore RSI values.
    target_log = np.log(cfg["target_end"] / cfg["start_price"])
    actual_log = returns.sum()
    returns   += (target_log - actual_log) / n

    return np.clip(returns, -0.15, 0.15)


def _build_ohlcv(returns: np.ndarray, start_price: float,
                 dates: pd.DatetimeIndex, seed: int) -> pd.DataFrame:
    rng   = np.random.default_rng(seed + 9999)
    n     = len(returns)
    close = np.round(start_price * np.exp(np.cumsum(returns)), 2)

    rng_pct = np.abs(rng.normal(0.015, 0.006, n)).clip(0.003, 0.065)
    opens   = np.zeros(n)
    highs   = np.zeros(n)
    lows    = np.zeros(n)
    volumes = np.zeros(n, dtype=np.int64)

    opens[0] = start_price
    for k in range(n):
        if k > 0:
            opens[k] = round(close[k - 1] * (1 + rng.normal(0, 0.003)), 2)
        half     = close[k] * rng_pct[k] / 2
        highs[k] = round(max(opens[k], close[k]) + abs(rng.normal(0, half * 0.5)), 2)
        lows[k]  = round(min(opens[k], close[k]) - abs(rng.normal(0, half * 0.5)), 2)
        base_v   = int(rng.lognormal(13.5, 0.45))
        volumes[k] = int(base_v * (1 + 2.5 * abs(returns[k]) / 0.04))

    df = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": close, "volume": volumes},
        index=dates,
    )
    df.index.name = "date"
    return df


def _count_trades(ticker: str) -> tuple[int, float, float]:
    """Return (n_trades, win_rate_pct, total_return_pct)."""
    try:
        from backtest import Backtester, SetupStore, setup_from_dict
        store  = SetupStore()
        record = store.get("Daily-RSI-14")
        if record is None:
            return -1, 0, 0
        setup = setup_from_dict({**record["definition"], "name": record["name"]})
        bt = Backtester(
            ticker=ticker, setup=setup, setup_id=record["id"],
            start_date=START, lookback_days=2300,
        )
        m = bt.run()
        return m.get("total_trades", 0), m.get("win_rate_pct", 0), m.get("total_return_pct", 0)
    except Exception:
        return -1, 0, 0


def main():
    dates = pd.bdate_range(START, END)
    n     = len(dates)
    years = n / 252
    print(f"Generating {n} trading days ({START} → {END})  [{years:.1f} yrs]\n")

    for ticker, cfg in TICKERS.items():
        returns       = _generate_returns(cfg, n)
        df            = _build_ohlcv(returns, cfg["start_price"], dates, cfg["seed"])
        out           = CACHE_DIR / f"{ticker}_daily.csv"
        df.to_csv(out)

        n_trades, win_pct, ret_pct = _count_trades(ticker)
        per_year = n_trades / years

        print(
            f"  {ticker:<8}  ${df['close'].iloc[0]:.2f} → ${df['close'].iloc[-1]:.2f}"
            f"  trades={n_trades} ({per_year:.1f}/yr)"
            f"  win={win_pct:.0f}%  strat_return={ret_pct:.1f}%"
            f"  → {out.name}"
        )

    print("\nDone.")


if __name__ == "__main__":
    main()
