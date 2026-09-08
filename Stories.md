# Stories & Reference

## Typical Chat Requests

### Setup Management

- **Add a setup** (e.g. `RSI_MACD_TREND`):
  ```json
  {
    "name": "RSI_MACD_TREND",
    "description": "Enter when RSI is oversold and MACD crosses up above its signal line, confirming an uptrend via SMA-50 and a trending market via ADX > 20.",
    "definition": {
      "entry_conditions": [
        {"label": "RSI(14) < 35 (oversold)",       "type": "rsi_below",         "params": {"value": 35}},
        {"label": "MACD crossover up",              "type": "macd_crossover_up", "params": {}},
        {"label": "Price above SMA(50)",            "type": "price_above_sma",   "params": {"period": 50}},
        {"label": "ADX(14) > 20 (trending market)", "type": "adx_above",         "params": {"value": 20}}
      ],
      "exit_conditions": [
        {"label": "RSI(14) > 70 (overbought)", "type": "rsi_above",          "params": {"value": 70}},
        {"label": "MACD crossover down",        "type": "macd_crossover_down","params": {}}
      ],
      "stop_loss_pct":   0.05,
      "take_profit_pct": 0.15,
      "position_type":   "equity_pct",
      "position_value":  0.10
    }
  }
  ```

- Save a setup called `EMA8_21_PB`: entry when price above SMA-50, EMA-8 above EMA-21, touched EMA-8, closed above EMA-8, ADX above 20. Exit when price below EMA-21 or RSI above 75. Stop loss 4%, take profit 10%, risk 2% of equity.

- List setups 

- View / Show setup `RSI_MACD_TREND`

### Backtests

- Run a backtest for AAPL over the last 300 days using the `RSI14_Below30` setup and show me the results.
- Run a backtest on NVDA using `RSI_MACD_TREND` setup 100 days
- List the backtest runs
- Show the backtest result id = `<id>`

### Watchlist

- Add stock to watchlist
- Add setup to watchlist for stock
- Show the watchlist

### Accounts

- **Add account**:
  - `broker`: Broker name (e.g. `"alpaca"`, `"td_ameritrade"`)
  - `account_id`: The broker-assigned account identifier
  - `display_name`: Optional friendly label for this account
  - `is_paper`: `true` for paper/simulated trading, `false` for live (default `true`)
  - `cash`: Starting cash balance (default `0.0`)
  - `equity`: Starting equity value (default `0.0`)
- List accounts

---

## Account-Specific Queries

- Portfolio details / view (current holdings / historical)
- What is happening — PortfolioManagerAgent logs
- News about current holdings
- `"List PM runs for account PaperAcct1 from September"`
- `"Show me run xyz-456"`
- Show account holdings
- `"How is it going with PaperAcct1 account"`
- `"What is happening with my portfolio"`
- `"Give me an update on PaperAcct1"`
- `"PaperAcct1 account holdings"`

---

## General Recommendation Queries

- `"Should I buy NVDA?"`
- `"What do you think about AAPL?"`
- `"Is TSLA a good trade right now?"`
- `"Give me a recommendation on MSFT"`
- `"What's your call on AMD?"`

---

## Mock Data & Testing

- Run backtest for DOBBY using `Daily-RSI-14` setup over 300 days

---

## Useful Commands

### SPY/QQQ Positional Trader

```bash
# Run once immediately (evaluate + execute now)
python -m jobs.spyqqq_positional_trader --now

# Run simulation (last 5 weeks ending 2026-09-01)
python -m jobs.spyqqq_positional_trader --simulate

# Run simulation with custom date range
python -m jobs.spyqqq_positional_trader --simulate --start 2026-07-25 --end 2026-09-01

# Start live scheduler in background (survives terminal close)
nohup python3 -m jobs.spyqqq_positional_trader > logs/spyqqq.log 2>&1 &
echo "PID: $!"

# Tail the log
tail -f logs/spyqqq.log

# Stop the scheduler
pkill -f spyqqq_positional_trader

# Check if running
pgrep -fl spyqqq_positional_trader
```

### RAG Data Ingester

```bash
# Start the scheduler (runs at 7AM, 12PM, 8PM ET Mon–Fri)
python -m jobs.rag_data_ingester

# Run once immediately (uses saved 'since' state)
python -m jobs.rag_data_ingester --now

# Clear saved state and re-ingest from scratch
python -m jobs.rag_data_ingester --reset

# Run in background
nohup python3 -m jobs.rag_data_ingester > logs/rag_ingester.log 2>&1 &
echo $!
```

### Portfolio Manager Scheduler

```bash
python -m jobs.portfolio_manager_scheduler          # start scheduler
python -m jobs.portfolio_manager_scheduler --now    # run once immediately

python3 -m jobs.portfolio_manager_scheduler --now
```

### PM Simulation Runner

```bash
# Run simulation for September
nohup python3 -m jobs.pm_simulation_runner \
  --account ed36fd4a-b742-46c4-9733-b6b8f99f96db \
  --start 2026-09-04 --end 2026-09-30 \
  > logs/pm_simulation_sep.log 2>&1 &

# Run simulation for October
nohup python3 -m jobs.pm_simulation_runner \
  --account ed36fd4a-b742-46c4-9733-b6b8f99f96db \
  --start 2026-10-01 --end 2026-10-31 \
  > logs/pm_simulation_oct.log 2>&1 &

echo "PID: $!"
tail -f logs/pm_simulation_sep.log

# Kill running simulation
pkill -f pm_simulation_runner
```

### Inspect PM Runs

```bash
python3 -c "
from tools.db.pm_agent_runs import list_pm_runs
runs = list_pm_runs('ed36fd4a-b742-46c4-9733-b6b8f99f96db', limit=30)
print(f'{len(runs)} runs saved')
for r in runs:
    print(f\"  {r['sim_date']}  buys={r['buys_executed']}  sells={r['sells_executed']}  open={r['open_holdings_count']}\")
"
```

### Reset Account Cash

```bash
python3 -c "
from tools.db.portfolio_data import set_account_cash
set_account_cash('ed36fd4a-b742-46c4-9733-b6b8f99f96db', 100000.0)
"
```

### Run Portfolio Manager Agent (Live / Paper)

```bash
MOCK_STOCKS_ENABLED=false python3 -m agents.portfolio_manager_agent ed36fd4a-b742-46c4-9733-b6b8f99f96db
```

### Start Dev Servers

```bash
uvicorn chat_support.chat_api:app --reload --port 8800
npm run dev
```

---

## Notes

### Should PortfolioManagerAgent use LangGraph?

`PortfolioManagerAgent` is currently plain Python — it orchestrates everything manually with `ThreadPoolExecutor`, direct method calls, and sequential loops. No LangGraph state machine, no LangChain tool binding.

**Arguments for LangGraph:**
- The current flow (evaluate holdings → research → tech eval → execute buys) is already a fixed pipeline — LangGraph's state graph would make that structure explicit and inspectable
- Built-in state persistence (checkpointing mid-run) would help if a long simulation day crashes partway through
- Easier to add conditional branching later (e.g. skip buys if market is down >2%)
- Consistent with how `ChatAgent` is built

**Arguments against:**
- The current code is already well-structured and readable — `run()` is clean and sub-steps are clear methods
- The parallelism (holdings eval in background while buy pipeline runs) would be awkward to express in LangGraph
- `PortfolioManagerAgent` does no LLM reasoning at the supervisor level — it's pure orchestration, where LangGraph adds the least value
- Refactoring introduces risk with no functional gain for the simulation

**Conclusion:** Not worth it right now. LangGraph shines when an agent needs to reason about what to do next using an LLM. Here the flow is deterministic and LLM calls are delegated to sub-agents (`ResearchAgent`, evaluators). The current structure is a better fit.

### Docker

Dockerizing the whole application — deferred for later.
