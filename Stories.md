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
-- "List PM runs for account PaperAcct1 from September"
-- "Show me run xyz-456"
-- Show account holdings
-- 'How is it going with PaperAcct1 account'
-- 'What is happening with my portfolio'
-- 'Give me an update on PaperAcct1'
-- 'PaperAcct1 account holdings'


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

python3 -m jobs.portfolio_manager_scheduler --now

python3 -c "
from tools.db.pm_agent_runs import list_pm_runs
runs = list_pm_runs('<account_id>', limit=5)
for r in runs:
    print(r['id'], r['sim_date'], r['buys_executed'], 'buys', r['sells_executed'], 'sells')
    print(r['summary_text'])
"

python3 -m jobs.pm_simulation_runner \
  --account ed36fd4a-b742-46c4-9733-b6b8f99f96db \
  --start 2026-09-04 \
  --end 2026-09-30

python3 -c "
from tools.db.pm_agent_runs import list_pm_runs
runs = list_pm_runs('ed36fd4a-b742-46c4-9733-b6b8f99f96db', limit=30)
print(f'{len(runs)} runs saved')
for r in runs:
    print(f\"  {r['sim_date']}  buys={r['buys_executed']}  sells={r['sells_executed']}  open={r['open_holdings_count']}\")
"

pkill -f pm_simulation_runner
nohup python3 -m jobs.pm_simulation_runner --account ed36fd4a-b742-46c4-9733-b6b8f99f96db --start 2026-09-04 --end 2026-09-30 > logs/pm_simulation_sep.log 2>&1 &
nohup python3 -m jobs.pm_simulation_runner --account ed36fd4a-b742-46c4-9733-b6b8f99f96db --start 2026-10-01 --end 2026-10-31 > logs/pm_simulation_oct.log 2>&1 & 

echo "PID: $!"

tail -f logs/pm_simulation_sep.log

MOCK_STOCKS_ENABLED=false python3 -m agents.portfolio_manager_agent ed36fd4a-b742-46c4-9733-b6b8f99f96db

python3 -c "from tools.db.portfolio_data import set_account_cash; set_account_cash('ed36fd4a-b742-46c4-9733-b6b8f99f96db', 10000.0)"


uvicorn chat_support.chat_api:app --reload --port 8800
npm run dev





PortfolioManagerAgent is currently plain Python — it orchestrates everything manually with ThreadPoolExecutor, direct method calls, and sequential loops. No LangGraph state machine, no LangChain tool binding.
Whether to refactor depends on what you'd gain:

Arguments for LangGraph:

The current flow (evaluate holdings → research → tech eval → execute buys) is already a fixed pipeline with clear steps — LangGraph's state graph would make that structure explicit and inspectable
You'd get built-in state persistence (checkpointing mid-run), which would help if a long simulation day crashes partway through
Easier to add conditional branching later (e.g. "if market is down >2%, skip buys entirely")
Consistent with how ChatAgent is built

Arguments against:

The current code is already well-structured and readable — run() is clean and the sub-steps are clear methods
The parallelism (holdings eval in background while buy pipeline runs) would be awkward to express in LangGraph since it's inherently sequential node-to-node
PortfolioManagerAgent doesn't do any LLM reasoning at the supervisor level — it's pure orchestration logic, which is where LangGraph adds the least value
Refactoring introduces risk with no functional gain for the simulation

My take: it's not worth it right now. LangGraph shines when an agent needs to reason about what to do next using an LLM. Here the flow is deterministic and the LLM calls are delegated to sub-agents (ResearchAgent, evaluators). The current structure is a better fit for the problem.