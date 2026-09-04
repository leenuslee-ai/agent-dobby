- Add setup
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

- Save a setup called EMA8_21_PB: entry when price above SMA-50, EMA-8 above EMA-21, touched EMA-8, closed above EMA-8, ADX above 20. Exit when price below EMA-21 or RSI above 75. Stop loss 4%, take profit 10%, risk 2% of equity.


- View / Show setup RSI_MACD_TREND
- Run a backtest for AAPL over the last 300 days using the 'RSI14_Below30' setup and show me the results.
- Run a back test on NVDA using RSI_MACD_TREND setup 100 days -- not working -- 
- list the backtest runs
- show the back test result id = 
- add stock to watch list
- add setup to watch list for stock
- add account 
        broker:       Broker name (e.g. "alpaca", "td_ameritrade")
        account_id:   The broker-assigned account identifier
        display_name: Optional friendly label for this account
        is_paper:     True for paper/simulated trading, False for live (default True)
        cash:         Starting cash balance (default 0.0)
        equity:       Starting equity value (default 0.0)
-- list accounts

Accounts Specific
=================
-- Portfolio details / view (Current Holdings / Historical )
-- What is happening -- PM logs 
-- News about current holdings
-- 

General Questions
-------------------

- "Should I buy NVDA?"
- "What do you think about AAPL?"
- "Is TSLA a good trade right now?"
- "Give me a recommendation on MSFT"
- "What's your call on AMD?"

Mock Data Preparations and Mock Runs For Testing Purposes
========================================================
- run backtest for DOBBY using Daily-RSI-14 setup over 300 days

Some notes 
==========
Need to take care of dockerizing the whole applciation.. Later

# Start the scheduler (runs at 7AM, 12PM, 8PM ET Mon–Fri)
python -m jobs.rag_data_ingester
# Run once immediately (uses saved 'since' state)
python -m jobs.rag_data_ingester --now
# Clear saved state and re-ingest from scratch
python -m jobs.rag_data_ingester --reset

nohup python3 -m jobs.rag_data_ingester > logs/rag_ingester.log 2>&1 &
echo $!

nohup keeps it running after you close the terminal
> logs/rag_ingester.log 2>&1 sends both stdout and stderr to a log file
& backgrounds it
echo $! prints the PID so you can kill it later with kill

Usage:
    python -m jobs.portfolio_manager_scheduler          # start scheduler
    python -m jobs.portfolio_manager_scheduler --now    # run once immediately

uvicorn chat_support.chat_api:app --reload --port 8800
npm run dev




    