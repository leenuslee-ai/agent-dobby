1. Add setup
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

2. View / Show setup RSI_MACD_TREND
3. Run a backtest for AAPL over the last 300 days using the 'RSI14_Below30' setup and show me the results.
