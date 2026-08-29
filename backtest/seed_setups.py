"""Seed the setup store with the two built-in trading setups.

Run once (or any time you want to reset to defaults):
    python -m backtest.seed_setups
"""

from tools import SetupStore

SETUPS = [
    {
        "name": "RSI_MACD_TREND",
        "description": (
            "Enter when RSI is oversold and MACD crosses up above its signal line, "
            "confirming an uptrend via SMA-50 and a trending market via ADX > 20."
        ),
        "definition": {
            "entry_conditions": [
                {"label": "RSI(14) < 35 (oversold)",       "type": "rsi_below",         "params": {"value": 35}},
                {"label": "MACD crossover up",              "type": "macd_crossover_up", "params": {}},
                {"label": "Price above SMA(50)",            "type": "price_above_sma",   "params": {"period": 50}},
                {"label": "ADX(14) > 20 (trending market)", "type": "adx_above",         "params": {"value": 20}},
            ],
            "exit_conditions": [
                {"label": "RSI(14) > 70 (overbought)",  "type": "rsi_above",          "params": {"value": 70}},
                {"label": "MACD crossover down",         "type": "macd_crossover_down","params": {}},
            ],
            "stop_loss_pct":   0.05,
            "take_profit_pct": 0.15,
            "position_type":   "equity_pct",
            "position_value":  0.10,
        },
    },
    {
        "name": "EMA20_PB",
        "description": (
            "In a clear uptrend, wait for price to pull back and touch the rising "
            "20 EMA, then enter on a hammer or bullish engulfing candle at the line."
        ),
        "definition": {
            "entry_conditions": [
                {"label": "EMA-20 is rising",                  "type": "ema_rising",      "params": {"window": 20}},
                {"label": "Price above SMA-50 (uptrend)",      "type": "price_above_sma", "params": {"period": 50}},
                {"label": "Low touched EMA-20 (pullback)",     "type": "touched_ema",     "params": {"window": 20}},
                {"label": "Closed back above EMA-20",          "type": "closed_above_ema","params": {"window": 20}},
                {"label": "Reversal candle (hammer or engulf)","type": "hammer_or_engulf",  "params": {}},
            ],
            "exit_conditions": [
                {"label": "RSI overbought > 70",             "type": "rsi_above",      "params": {"value": 70}},
                {"label": "Price crosses back below EMA-20", "type": "price_below_ema", "params": {"period": 20}},
            ],
            "stop_loss_pct":   0.03,
            "take_profit_pct": 0.08,
            "position_type":   "equity_pct",
            "position_value":  0.10,
        },
    },
    {
        "name": "RSI14_Below30",
        "description": (
            "RSI_Below30"
        ),
        "definition": {
            "entry_conditions": [
                {"label": "RSI(14) < 35 (oversold)",       "type": "rsi_below",         "params": {"value": 35}},
            ],
            "exit_conditions": [
                {"label": "RSI overbought > 70",             "type": "rsi_above",      "params": {"value": 70}},
                {"label": "Price crosses back below EMA-20", "type": "price_below_ema", "params": {"period": 20}},
            ],
            "stop_loss_pct":   0.03,
            "take_profit_pct": 0.08,
            "position_type":   "equity_pct",
            "position_value":  0.10,
        },
    },
]


if __name__ == "__main__":
    store = SetupStore()
    for s in SETUPS:
        setup_id = store.save(
            name=s["name"],
            description=s["description"],
            definition=s["definition"],
        )
        print(f"  saved: {s['name']} (id={setup_id})")

    print("\nAll setups in store:")
    for row in store.list():
        print(f"  [{row['id'][:8]}...]  {row['name']}")
