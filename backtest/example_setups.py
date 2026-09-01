"""Pre-built example trading setups for testing and reference."""

from tools import Setup


def build_example_setup() -> Setup:
    """RSI oversold + MACD crossover + trend filter setup."""
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
        stop_loss_pct=0.05,
        take_profit_pct=0.15,
        position_type="equity_pct",
        position_value=0.10,
    )


def build_ema_pullback_setup() -> Setup:
    """20 EMA Pullback swing trade setup.

    Entry logic:
      1. EMA-20 is rising (uptrend confirmed)
      2. Price pulled back and touched or pierced the EMA-20 on the low
      3. Candle closed back above EMA-20 (recovery)
      4. Reversal candle: hammer OR bullish engulfing right at the line

    Stop loss: 3% below entry (approximates "just under the EMA / swing low")
    Target:    8% above entry (approximates "previous recent high")
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
            ("RSI overbought > 70",             lambda r: r["rsi"] > 70),
            ("Price crosses back below EMA-20", lambda r: r["close"] < r["ema_20"]),
        ],
        stop_loss_pct=0.03,
        take_profit_pct=0.08,
        position_type="equity_pct",
        position_value=0.10,
    )
