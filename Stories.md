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
4. Run a back test on NVDA using RSI_MACD_TREND setup 100 days -- not working -- 
5. list the backtest runs
6. show the back test result id = 
7. add stock to watch list
8. add setup to watch list for stock
9.  



- "Should I buy NVDA?"
- "What do you think about AAPL?"
- "Is TSLA a good trade right now?"
- "Give me a recommendation on MSFT"
- "What's your call on AMD?"

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

---
Let's add two more functions to trade_data.py 
    get_open_holdings(account_id, opening_transaction_type='Buy' if not specified)
    get_holdings(account_id, opening_transaction_type (can be 'Buy', 'Sell' or None ), opening_transaction_date)
        when it is None return all 


Alright! Let's add the new version of the portfolio_manager_agent.py in the agents folder with the following characteristics.
It should define a new agent class. I am going to invoke this agent thru a scheduler that will run at certain frequency. For the start I may run every hour during market hours starting 9:30AM EST. That sheduler job needs to be added to the jobs folder. The scheduler will use a separate instance of the agent and it needs to invoke them to run asynchronously. So
for every run it will kick off multiple agents one for each account. 

The agent will be using LangGraph & LangChain capabilities.
Each agent instance will be managing one portfolio account. So the account_id needs to be initialized. 
It can use the chat_support/portfolio_tools.list_portfolio_accounts tool to find the list of accounts