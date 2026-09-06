# Agent Dobby — System Design Document

## 1. Overview

Agent Dobby is an AI-powered automated trading pipeline built in Python. It combines large language model reasoning, technical indicator analysis, RAG-based news sentiment, and brokerage execution into a cohesive system that can:

- Monitor a watchlist of stocks and evaluate entry conditions using named trading setups
- Evaluate open holdings against exit conditions and execute sell orders when triggered
- Run historical backtests of any named setup against real market data
- Ingest and summarise financial news into a local vector database for semantic search
- Expose a conversational chat interface so a human can interrogate and control the system in natural language
- Support mock/simulation mode with synthetic tickers for testing without live API calls

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        External Services                            │
│   Alpha Vantage (OHLCV)   Alpaca (orders)   Yahoo Finance (news)   │
└──────────────┬────────────────────┬──────────────────┬─────────────┘
               │                    │                  │
┌──────────────▼────────────────────▼──────────────────▼─────────────┐
│                          Tools Layer                                │
│  alphavantage_data.py   trade_executor_tool.py   rag_yahoo/         │
│  condition_registry.py  setup_store.py           mock_executor.py   │
└──────────────┬────────────────────┬──────────────────┬─────────────┘
               │                    │                  │
┌──────────────▼────────────────────▼──────────────────▼─────────────┐
│                          Agents Layer                               │
│  ResearchAgent       BuyTechEvaluatorAgent                          │
│  CurrentHoldingsEvaluatorAgent                                      │
│  PortfolioManagerAgent (supervisor)                                 │
│  PortfolioManagerAgentV2 (no-research variant)                      │
└──────────────┬────────────────────┬────────────────────────────────┘
               │                    │
┌──────────────▼──────┐  ┌──────────▼──────────────────────────────┐
│   Scheduler (Jobs)  │  │          Chat Interface                  │
│  portfolio_manager  │  │  FastAPI  →  ChatAgent (LangGraph)       │
│  rag_data_ingester  │  │              18 LangChain tools          │
│  pm_simulation      │  └─────────────────────────────────────────┘
└─────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────────────┐
│                         Data Layer                                  │
│  PostgreSQL (accounts, holdings, transactions, backtest runs, ...)  │
│  SQLite SetupStore  (trading setup definitions)                     │
│  ChromaDB           (news embeddings / vector search)               │
│  Alpha Vantage CSV cache  (local OHLCV cache, refreshed daily)      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Component Breakdown

### 3.1 Tools Layer

#### `tools/alphavantage/alphavantage_data.py`

Single source of truth for market data. Fetches full daily OHLCV history from Alpha Vantage and caches it locally as CSV (refreshed after 23 hours). Computes a rich set of technical indicators using the `ta` library:

| Category | Indicators |
|---|---|
| Trend | SMA-20/50/200, EMA-8/12/20/21/26, ADX |
| Momentum | RSI-14, RSI-2, MACD/Signal/Hist, Stochastic K/D |
| Volatility | Bollinger Bands (upper/lower/mid/pct), ATR |
| Volume | OBV, Vol SMA-20 |
| Derived signals | MACD crossover up/down, golden/death cross, EMA crossovers (8×20, 8×21, 12×26), EMA pullback signals (touched/closed above/rising for windows 8/12/20/21/26), hammer candle, bullish engulfing |

**Mock ticker short-circuit:** When a ticker is in `MOCK_STOCKS`, data is always loaded from `tools/alphavantage/cache/<TICKER>_daily.csv` — the Alpha Vantage API is never called, even if the cache is stale.

#### `tools/alpaca/trade_executor_tool.py`

LangChain tools for Alpaca brokerage interaction. Supports paper and live trading via `ALPACA_PAPER` env flag. Uses `TradingClient` for order submission and account queries.

| Tool | Description |
|---|---|
| `buy_market_order` | Place a market BUY order |
| `sell_market_order` | Place a market SELL order |
| `get_order_status` | Poll order fill status by order ID |
| `get_positions` | List all open Alpaca positions |
| `get_account_info` | Return buying power, cash, portfolio value |
| `cancel_all_orders` | Cancel all open/pending orders |

**Price fetching** (outside of the LangChain tools) uses `StockHistoricalDataClient.get_stock_latest_trade()` — this is a separate Alpaca client from `TradingClient` and must be instantiated separately.

#### `tools/rag_yahoo/`

Yahoo Finance RSS ingestion, summarisation, and vector storage pipeline.

- **`ingestion.py`** — fetches RSS feeds per ticker, filters articles that mention the ticker, summarises with Claude Haiku (or local Ollama), and deduplicates by content hash
- **`vector_store.py`** — embeds article summaries using `all-MiniLM-L6-v2` (local, no API call) and stores in ChromaDB; exposes `semantic_search(query, ticker)` for retrieval
- **`pipeline.py`** — `run_pipeline(tickers, since)` orchestrates ingestion → embedding → storage

#### `tools/trade_setup/`

| File | Purpose |
|---|---|
| `setup_store.py` | SQLite-backed store for named setup definitions (JSON) |
| `setup_schema.py` | `Setup` dataclass; `setup_from_dict()` factory |
| `condition_registry.py` | Registry of 50+ condition factories |

The condition registry uses a `lambda p: (lambda r: ...)` factory pattern so each condition is parameterised at load time and evaluated row-by-row at backtest/evaluation time. Supported condition families:

- **RSI:** `rsi_below`, `rsi_above`, `rsi_2_below`, `rsi_2_above`
- **MACD:** `macd_crossover_up`, `macd_crossover_down`, `macd_hist_positive`, `macd_hist_negative`
- **Moving Averages:** `price_above_sma`, `price_below_sma`, `price_above_ema`, `price_below_ema`, `golden_cross`, `death_cross`
- **EMA Pullbacks:** `ema_rising`, `touched_ema`, `closed_above_ema`
- **EMA Crossovers:** `ema_cross_above`, `ema_cross_below`
- **Candlestick:** `hammer`, `bullish_engulfing`, `hammer_or_engulf`
- **ADX:** `adx_above`, `adx_below`
- **Bollinger Bands:** `bb_pct_below`, `bb_pct_above`, `price_below_bb_lower`, `price_above_bb_upper`
- **Stochastic:** `stoch_k_below`, `stoch_k_above`, `stoch_oversold`, `stoch_overbought`
- **Volume:** `volume_above_avg`
- **Formula escape hatch:** `type: "formula"` with `params: {"expr": "rsi < 40 and close > ema_20"}`

#### `tools/db/`

PostgreSQL data access layer using SQLAlchemy ORM. See [Section 4](#4-data-layer) for the full schema.

| Module | Key Functions |
|---|---|
| `portfolio_data.py` | `create_account`, `list_accounts`, `get_account`, `update_account_cash`, `set_account_cash` |
| `trade_data.py` | `save_trade`, `get_open_holdings`, `get_holdings`, `get_transactions` |
| `watchlist_data.py` | `add_watchlist_entry`, `list_watchlist`, `update_watchlist_entry`, `get_tickers` |
| `backtest_run_data.py` | `save_backtest_run`, `list_backtest_runs`, `get_backtest_run` |
| `pm_agent_runs.py` | `save_pm_run`, `list_pm_runs`, `get_pm_run` |

**Cash tracking:** `save_trade()` adjusts `portfolio_accounts.cash` within the same SQLAlchemy session — BUY Open decrements cash, SELL Close increments cash. This ensures cash balance is always consistent with trade history.

#### `tools/mock_data/`

| File | Purpose |
|---|---|
| `generate_mock_news.py` | Generate synthetic news articles for mock tickers (DOBBY, OWALA, MINI, LUCAS, PILLOW) |
| `mock_executor.py` | Simulate order fills for mock tickers without calling Alpaca. Uses `MOCK_SIMULATION_DATE` for `filled_at` timestamps. |

---

### 3.2 Agents Layer

All agents are Python classes. LangGraph is used for agents that need a tool-calling ReAct loop; plain Python is used where deterministic evaluation is sufficient.

#### `ResearchAgent` (`agents/research_agent.py`)

LangGraph ReAct agent. Given a question about a ticker:
1. Calls `search_news` tool → semantic search in ChromaDB
2. Calls `get_stock_price` tool → live price from yfinance
3. Synthesises a BUY/SELL/HOLD/WAIT recommendation with reasoning

**Graph is initialised lazily** — the LangGraph graph is built on the first call to `_get_graph()`, not at `__init__` time. This avoids Ollama connection attempts at import.

**Ollama concurrency:** Ollama handles one request at a time. When `MODEL_PROVIDER` is `ollama` or `qwen`, research runs sequentially (`max_workers=1`) to prevent deadlock.

**Per-ticker timeout:** Each research call is wrapped in a `ThreadPoolExecutor` with a 90-second timeout. If the LLM hangs, the ticker defaults to WAIT and the pipeline continues.

Used by `PortfolioManagerAgent` to filter the watchlist to tickers with a research-backed BUY signal before running technical evaluation.

**Mock mode:** When `MOCK_STOCKS_ENABLED=true` and the ticker is in `MOCK_STOCKS`, the LLM call is skipped entirely — the agent returns a hardcoded BUY recommendation.

#### `BuyTechEvaluatorAgent` (`agents/buy_tech_evaluator_agent.py`)

No LLM tool loop — purely deterministic indicator evaluation.
1. Loads a named setup from `SetupStore`
2. Fetches the latest OHLCV bar with indicators from the cached CSV
3. Evaluates all **entry conditions** (AND logic — all must be MET)
4. Returns `BUY` or `WAIT` with a per-condition breakdown

Supports `evaluate_many(pairs)` for batch evaluation of multiple `(ticker, setup)` pairs via `ThreadPoolExecutor`.

#### `CurrentHoldingsEvaluatorAgent` (`agents/current_holdings_evaluator_agent.py`)

Manages exit decisions for open BUY holdings.
1. Loads open holdings via `get_open_holdings(account_id, type="BUY")`
2. **Evaluates all holdings in parallel** (ThreadPoolExecutor)
   - Checks **exit conditions** (OR logic — any condition triggers exit)
   - Checks stop-loss and take-profit thresholds against open price
3. **Executes SELL orders sequentially** for safety
4. Polls each order for fill via `poll_order_status()`
5. Persists each close trade via `save_trade(open_close="Close")`
6. Returns refreshed open holdings

**Mock mode:** Sell orders for mock tickers are routed through `mock_executor.simulate_fill()` — Alpaca is not called.

#### `PortfolioManagerAgent` (`agents/portfolio_manager_agent.py`)

Supervisor agent — one instance per portfolio account.

```
Run flow:
  ┌─────────────────────────────────────────────────┐
  │ 1. Get open BUY holdings                        │
  │    └─ If any → launch CurrentHoldingsEvaluator  │ ◄── async (background thread)
  │                                                 │
  │ 2. If cash >= $100:                             │
  │    a. Get (ticker, setup) pairs from watchlist  │
  │       + inject mock tickers if MOCK_STOCKS_ENABLED│
  │    b. ResearchAgent.analyze_recommendation      │ ◄── sequential if Ollama, else parallel
  │       └─ Keep BUY recommendations only          │
  │    c. BuyTechEvaluatorAgent.evaluate_many       │
  │       └─ Keep BUY decisions only                │
  │    d. Execute buys sequentially                 │
  │       ├─ Size: risk_percent × available_cash / price│
  │       ├─ Place market order (or simulate if mock)│
  │       ├─ Poll for fill                          │
  │       └─ Persist via save_trade("Open")         │
  │                                                 │
  │ 3. Await holdings evaluator (timeout 5 min)     │
  │ 4. Persist run summary to pm_agent_runs table   │
  └─────────────────────────────────────────────────┘
```

**Cash sourcing:** In mock mode, available cash is read from `portfolio_accounts.cash` in PostgreSQL. In live/paper mode, it is fetched from the Alpaca account's `buying_power`.

Run summaries are persisted to the `pm_agent_runs` table including research results, buy candidates, executed buys, open holdings count, elapsed time, and any errors.

#### `PortfolioManagerAgentV2` (`agents/portfolio_manager_agent_v2.py`)

A lightweight variant that skips `ResearchAgent` entirely — goes straight from watchlist to `BuyTechEvaluatorAgent` and Alpaca order execution. Created to verify the Alpaca buy order pipeline independently of Ollama/LLM.

Flow: watchlist pairs → `BuyTechEvaluatorAgent.evaluate_many` → execute buys → persist trades.

Does **not** run holdings evaluation or persist a pm_agent_runs summary.

#### Shared helpers (`agents/evaluator_helpers.py`)

Used by both `BuyTechEvaluatorAgent` and `CurrentHoldingsEvaluatorAgent`:
- `load_setup(name)` — load from SetupStore
- `fetch_latest_row(ticker)` — fetch indicators, return most recent bar
- `evaluate_conditions(conditions, row, require_all)` — AND or OR evaluation
- `generate_reason(llm, ...)` — one-sentence LLM explanation
- `poll_order_status(client, order_id, ...)` — poll Alpaca until filled or timeout

---

### 3.3 Chat Interface

#### `chat_support/chat_api.py` — FastAPI server

```
POST /login     → { threadId }
POST /whatnext  → { threadId, response, trace? }
```

Sessions are stored in-memory keyed by `threadId`. Each `threadId` maps to a LangGraph conversation thread (persistent via `MemorySaver`).

#### `chat_support/chat_agent.py` — LangGraph ReAct agent

Uses a `MemorySaver` checkpointer so conversation history persists across calls within the same `thread_id`. Graph structure:

```
agent ──► should_continue ──► tools ──► after_tools ──► agent
                    │                         │
                   END                       END  (if already_formatted=True)
```

The `already_formatted` flag on any tool response short-circuits the second LLM pass, ensuring consistent raw JSON responses for all tools. When all tool results in a parallel batch are `already_formatted`, the graph routes directly to `END` without going back to the agent.

**Context trimming:** After each response, large array fields (`candle_data`, `bars`, `trades`, `entries`, `runs`, `accounts`, `holdings`) are replaced with `"[N items — omitted from context]"` counts in `MemorySaver`. This prevents the context window from growing unbounded across turns.

**Stale thread behaviour:** If a `MemorySaver` thread has accumulated prior tool results for a ticker (e.g. TSLA), the LLM may answer from that context instead of calling a tool again. Start a new thread for a clean state.

When `CHAT_AGENT_TRACE=true`, each response includes a `trace` array showing every tool call and result for that request.

#### Chat Agent Tools (18 tools across 5 files)

| File | Tools |
|---|---|
| `chat_agent_tools.py` | `get_candlebar_data`, `get_recommendation` |
| `backtest_tools.py` | `run_backtest`, `list_backtest_runs`, `get_backtest_result` |
| `setup_tools.py` | `save_trade_setup`, `list_trade_setups`, `get_trade_setup` |
| `watchlist_tools.py` | `add_watchlist_entry`, `update_watchlist_entry`, `list_watchlist` |
| `portfolio_tools.py` | `create_portfolio_account`, `list_portfolio_accounts`, `get_portfolio_holdings`, `get_open_portfolio_holdings`, `get_portfolio_trades` |
| `pm_run_tools.py` | `list_pm_run_results`, `get_pm_run_result` |

Each tool returns a JSON object with a `responseType` field and `already_formatted: true`. The `_priority` map in `chat_agent.py` ranks `BackTestResults` (10) → `Recommendation` (9) → `CandlebarData` (8) → ... → `HoldingList`/`TradeList` (3) so the most informative result wins when parallel tool calls return mixed types.

All account-related tools include an `account_name` field at the top level of their response for frontend display.

`save_trade_setup` uses Claude Haiku to parse a human-readable setup description into a structured JSON definition and validates all condition types against the registry before saving.

**System prompt** directs the LLM to always call a tool for trading-related questions, with an explicit intent → tool name mapping. This is especially important for local models (qwen, gemma) that rely on directive instructions rather than docstring reasoning.

---

### 3.4 Backtester (`backtest/`)

| File | Purpose |
|---|---|
| `backtester.py` | Core `Backtester` class — simulates trades over historical data |
| `backtest_runner.py` | CLI runner — backtests a ticker + setup combination |
| `example_setups.py` | Pre-built setup factories (`build_example_setup`, `build_ema_pullback_setup`) |
| `seed_setups.py` | Seeds initial setups into SetupStore |

**Backtester logic:**
1. Fetches OHLCV + indicators for the ticker (mock tickers load from cache, never call API)
2. Iterates each bar chronologically
3. If no open trade: evaluates entry conditions (all must be MET)
4. If open trade: evaluates exit conditions (any triggers exit), checks stop-loss and take-profit
5. Position sizing: `equity_pct` (risk % of current equity), `shares`, or `dollars`
6. Computes metrics: total return, win rate, avg win/loss, max drawdown, Sharpe ratio, number of trades
7. Persists run to `backtest_runs` table via `db/backtest_run_data.py`

---

### 3.5 Scheduled Jobs (`jobs/`)

#### `rag_data_ingester.py`

Runs `run_pipeline(since=last_run_at)` three times daily at **7AM, 12PM, 8PM ET** (Mon–Fri). Persists last successful run timestamp to `jobs/.rag_ingester_state.json` so each run only pulls articles newer than the previous one.

```bash
python -m jobs.rag_data_ingester          # start scheduler
python -m jobs.rag_data_ingester --now    # run once
python -m jobs.rag_data_ingester --reset  # clear state and re-ingest from scratch
```

#### `portfolio_manager_scheduler.py`

Fires at **9:30AM and every hour from 10AM–3PM ET** (Mon–Fri). Discovers all portfolio accounts from the DB and runs one `PortfolioManagerAgent` per account concurrently via `ThreadPoolExecutor`.

```bash
python -m jobs.portfolio_manager_scheduler        # start scheduler
python -m jobs.portfolio_manager_scheduler --now  # run once immediately
```

#### `pm_simulation_runner.py`

Runs `PortfolioManagerAgent` day-by-day over a historical date range with mock data enabled. Sets `MOCK_SIMULATION_DATE` before each daily run so all mock prices, fills, and timestamps are anchored to that date.

```bash
python3 -m jobs.pm_simulation_runner \
  --account <account-uuid> \
  --start 2026-09-04 \
  --end 2026-10-31
```

Each day's results are persisted to `pm_agent_runs`. Use `list_pm_run_results` via the chat agent to review simulation outcomes.

---

## 4. Data Layer

### 4.1 PostgreSQL Tables

#### `portfolio_accounts`

One row per brokerage account.

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| broker | String | e.g. "alpaca" |
| account_id | String | Broker-assigned ID |
| display_name | String | Friendly label |
| is_paper | Boolean | Paper vs live |
| cash | Float | Tracked balance — updated on every trade via `save_trade()` |
| equity | Float | Last synced equity |

#### `portfolio_holdings`

One row per **opening transaction** (not per ticker). A ticker can have multiple open rows if bought on separate occasions.

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| account_id | UUID FK | → portfolio_accounts |
| ticker | String | |
| setup_name | String | "Manual" for manual trades |
| opening_transaction_date | DateTime | |
| open_qty | Float | Original shares bought |
| opening_transaction_type | String | "BUY" or "SELL" |
| open_price | Float | Entry price |
| pending_qty | Float | Remaining unmatched shares |
| current_price | Float | Last known price |
| current_open_value | Float | pending_qty × current_price |
| closed_value | Float | Sum of matched close values |

#### `close_trade_references`

Links a closing transaction to one or more holding rows (FIFO matching).

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| holding_id | UUID FK | → portfolio_holdings |
| closing_transaction_id | UUID FK | → portfolio_transactions |
| closing_qty | Float | Shares matched to this holding |
| closing_price | Float | Fill price |
| closing_date | DateTime | |

#### `portfolio_transactions`

All buy and sell transactions.

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| account_id | UUID FK | → portfolio_accounts |
| broker_order_id | String | Alpaca order ID |
| ticker | String | |
| setup_name | String | "Manual" for manual trades |
| side | String | "BUY" or "SELL" |
| open_close | String | "Open" or "Close" |
| qty | Float | |
| price | Float | Fill price |
| status | String | "filled", "partially_filled", "cancelled", "pending" |
| filled_at | DateTime | |

#### `backtest_runs`

One row per backtest execution.

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| setup_id | String | SetupStore ID (not FK) |
| ticker | String | |
| start_date / end_date | DateTime | Period tested |
| initial_cash | Float | |
| final_value | Float | |
| total_return / sharpe_ratio / max_drawdown / total_trades | Float/Int | Key metrics |
| extra_stats | JSON | Full metrics + formatted trade log |

#### `watchlist`

| Column | Type | Notes |
|---|---|---|
| ticker | String PK | |
| industry | String | |
| category | String | |
| setups | JSON | List of setup names |
| is_active | Boolean | |

#### `pm_agent_runs`

One row per `PortfolioManagerAgent.run()` execution.

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| account_id | UUID FK | → portfolio_accounts |
| run_at | DateTime | UTC timestamp of run start |
| sim_date | Date | Set only for simulation runs; null for live/paper |
| buys_executed | Integer | Count of orders filled |
| sells_executed | Integer | Count of closes filled |
| open_holdings_count | Integer | Open positions at end of run |
| research_count | Integer | Tickers researched |
| buy_candidates_count | Integer | Tickers passing technical eval |
| elapsed_seconds | Float | Total run duration |
| summary_text | Text | Human-readable run summary |
| raw_summary | JSON | Full structured result dict |

#### Other tables

- `configs` — key/value application configuration
- `trade_setups` — legacy table (not actively used; SetupStore is the active setup store)
- `backtest_transactions` — individual trade records linked to a backtest run
- `agent_logs` — structured agent activity log

### 4.2 SQLite SetupStore

Stored at `backtest_cache/setups.db`. Holds JSON setup definitions keyed by name and UUID. Used by the backtester, evaluator agents, and chat tools. Separate from PostgreSQL to keep setup definitions portable and fast to read without database joins.

### 4.3 ChromaDB

Local vector database at `./chroma_db/`. Stores embedded news article chunks using `all-MiniLM-L6-v2` (384-dimensional embeddings). Each chunk carries metadata: `ticker`, `published`, `source`, `sentiment`. Used by `ResearchAgent` for semantic news retrieval via `semantic_search(query, ticker)`.

### 4.4 Alpha Vantage CSV Cache

Stored at `tools/alphavantage/cache/<TICKER>_daily.csv`. Refreshed if older than 23 hours for live tickers. Mock ticker files are pre-generated and never refreshed. Means indicator computation is free after the first daily fetch, and backtests never incur API calls.

---

## 5. Trade Lifecycle

### 5.1 Opening a Trade (BUY)

```
PortfolioManagerAgent
  → BuyTechEvaluatorAgent.evaluate() → decision: BUY
  → _get_current_price() (StockHistoricalDataClient or mock)
  → qty = available_cash × risk_percent / 100 / price
  → Alpaca: submit_order(BUY, qty)  [or mock_executor.simulate_fill()]
  → poll_order_status() until filled
  → save_trade(open_close="Open")
       → creates PortfolioTransaction (side=BUY, open_close=Open)
       → creates PortfolioHolding (pending_qty=qty, closed_value=0)
       → decrements portfolio_accounts.cash by (qty × price)
```

### 5.2 Closing a Trade (SELL)

```
CurrentHoldingsEvaluatorAgent
  → evaluate exit conditions / stop-loss / take-profit → decision: SELL
  → Alpaca: submit_order(SELL, pending_qty)  [or mock_executor.simulate_fill()]
  → poll_order_status() until filled
  → save_trade(open_close="Close")
       → creates PortfolioTransaction (side=SELL, open_close=Close)
       → FIFO matches against PortfolioHolding rows (pending_qty > 0)
       → creates CloseTradeReference rows
       → adjusts pending_qty and closed_value on each matched holding
       → increments portfolio_accounts.cash by (qty × fill_price)
```

---

## 6. Trading Setup Definition

Setups are stored as JSON in the SQLite SetupStore. Each setup has named entry and exit conditions, risk parameters, and position sizing.

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

**Entry logic:** ALL conditions must be MET (AND)  
**Exit logic:** ANY condition triggers (OR), plus stop-loss and take-profit thresholds

**Position types:**
- `equity_pct` — risk a percentage of current account equity
- `cash_pct` — risk a percentage of available cash
- `fixed_qty` — fixed number of shares

New setups can be created via:
- The chat interface: *"Save a setup called X with the following conditions..."*
- `save_trade_setup` tool: Claude Haiku parses plain-English descriptions into the JSON definition

---

## 7. Mock / Simulation Mode

When `MOCK_STOCKS_ENABLED=true`, the system substitutes live API calls with local synthetic data for five predefined tickers: `DOBBY`, `OWALA`, `MINI`, `LUCAS`, `PILLOW`.

| Behaviour | Mock mode |
|---|---|
| OHLCV / indicators | Load from `tools/alphavantage/cache/<TICKER>_daily.csv` — API never called |
| Order execution | `mock_executor.simulate_fill()` — Alpaca never called |
| `filled_at` timestamps | Pinned to `MOCK_SIMULATION_DATE` (or current date if unset) |
| ResearchAgent | Skips LLM call entirely — returns hardcoded BUY |
| Available cash | Read from `portfolio_accounts.cash` in PostgreSQL |
| News articles | Pre-generated synthetic articles in ChromaDB |

`MOCK_SIMULATION_DATE` pins the evaluation date for OHLCV lookups, so the agent sees exactly the data it would have seen on that date (no lookahead).

**pm_simulation_runner** automates multi-day simulation by advancing `MOCK_SIMULATION_DATE` one business day at a time and calling `PortfolioManagerAgent.run()` for each.

---

## 8. Configuration

All configuration is via environment variables (`.env` file), loaded through `config.py`.

| Variable | Description | Default |
|---|---|---|
| `MODEL_PROVIDER` | LLM provider: `anthropic`, `ollama`, `qwen`, `gemma` | `anthropic` |
| `ANTHROPIC_API_KEY` | Anthropic API key | — |
| `ALPHAVANTAGE_API_KEY` | Alpha Vantage API key | — |
| `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` | Alpaca credentials | — |
| `ALPACA_PAPER` | `true` for paper trading, `false` for live | `true` |
| `DATABASE_URL` | PostgreSQL connection URL | local default |
| `CHAT_AGENT_TRACE` | Include execution trace in `/whatnext` response | `false` |
| `CHROMA_DB_PATH` | ChromaDB storage path | `./chroma_db` |
| `MOCK_STOCKS_ENABLED` | Use synthetic mock tickers instead of live data | `false` |
| `MOCK_SIMULATION_DATE` | Pin the evaluation date for simulation runs | unset |
| `PYTHONUNBUFFERED` | Disable Python stdout buffering (important for log tailing) | `1` |

**Derived settings in `config.py`:**

| Setting | Value |
|---|---|
| `AGENT_MODEL` | `claude-sonnet-4-6` (anthropic) or `qwen3.5:9b` (ollama/qwen) or `gemma4` (gemma) |
| `SUMMARIZE_MODEL` | `claude-haiku-4-5-20251001` (anthropic) or `llama3.2` (ollama) |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` (local, always) |
| `MOCK_STOCKS` | `["DOBBY", "OWALA", "MINI", "LUCAS", "PILLOW"]` |
| `TOP_K_RESULTS` | `5` (ChromaDB semantic search top-K) |
| `WARMUP_DAYS` | `250` (minimum history for SMA-200 indicator warmup) |

---

## 9. Running the System

### Start the Chat API

```bash
uvicorn chat_support.chat_api:app --reload --port 8800
```

### Start the Portfolio Manager Scheduler

```bash
python -m jobs.portfolio_manager_scheduler        # market hours, Mon–Fri
python -m jobs.portfolio_manager_scheduler --now  # run once immediately

# Background
nohup python3 -m jobs.portfolio_manager_scheduler > logs/pm_scheduler.log 2>&1 &
```

### Start the News Ingestion Scheduler

```bash
python -m jobs.rag_data_ingester          # 7AM, 12PM, 8PM ET Mon–Fri
python -m jobs.rag_data_ingester --now    # run once
python -m jobs.rag_data_ingester --reset  # clear state and re-ingest

# Background
nohup python3 -m jobs.rag_data_ingester > logs/rag_ingester.log 2>&1 &
```

### Run the Portfolio Manager Agent Manually

```bash
# Full pipeline (research + technical eval + orders)
python3 -m agents.portfolio_manager_agent <account-uuid>

# Technical eval + orders only (no LLM/research)
python3 -m agents.portfolio_manager_agent_v2 <account-uuid>
```

### Run a Backtest from the Command Line

```bash
python -m backtest.backtest_runner NVDA RSI_MACD_TREND --days 365
```

### Run the Simulation Runner

```bash
nohup python3 -m jobs.pm_simulation_runner \
  --account <account-uuid> \
  --start 2026-09-04 \
  --end 2026-10-31 \
  > logs/pm_simulation.log 2>&1 &
```

### Initialise the Database

```bash
python -m tools.db.init_db
```

### Reset Account Cash

```bash
python3 -c "
from tools.db.portfolio_data import set_account_cash
set_account_cash('<account-uuid>', 100000.0)
"
```

---

## 10. Key Design Decisions

| Decision | Rationale |
|---|---|
| SetupStore (SQLite) separate from PostgreSQL | Setup definitions are portable, frequently read, and don't need relational joins. SQLite keeps them fast and self-contained. |
| `already_formatted` flag on tool responses | Prevents the chat agent's LLM from re-narrating structured data, ensuring consistent JSON output for the frontend. |
| FIFO matching for close trades | Industry-standard approach; simplest to reason about and audit. |
| `pending_qty` per holding row (not per ticker) | Allows tracking multiple opening lots separately — important for cost basis and P&L accuracy. |
| Cash adjustment inside `save_trade()` session | Ensures `portfolio_accounts.cash` is always consistent with trade history. BUY Open decrements, SELL Close increments, within the same SQLAlchemy session. |
| Parallel research, sequential order execution | Research is read-only and independent per ticker. Order execution modifies cash balance and must be sequential to avoid over-spending. |
| Holdings evaluation in background thread | The sell evaluation can be slow (indicator fetch + condition eval). Running it async lets the buy pipeline proceed concurrently. |
| Local indicator computation (`ta` library) | No additional Alpha Vantage API calls per evaluation — all indicators are derived from the cached daily OHLCV data. |
| `WARMUP_DAYS = 250` | SMA-200 requires 200 bars minimum; 250 days of calendar data gives enough trading days after weekends and holidays. |
| Lazy LangGraph initialisation in ResearchAgent | Graph is built on first use, not at `__init__` time. Prevents Ollama/Anthropic connection at module import and avoids latency when the agent is only sometimes needed. |
| Sequential Ollama research (`max_workers=1`) | Ollama handles one request at a time. Parallel calls saturate the local model, causing the calling thread and other processes (e.g. ChatAgent) to hang indefinitely. |
| Per-ticker 90-second research timeout | Individual Ollama calls can hang on slow hardware. Each ticker is wrapped in a `ThreadPoolExecutor.future.result(timeout=90)`. On timeout the ticker defaults to WAIT and the pipeline continues. |
| `StockHistoricalDataClient` for price fetching | `TradingClient` does not expose `get_latest_trade`. Price fetching in the PM agent requires a separate `StockHistoricalDataClient` from `alpaca-py`. |
| PortfolioManagerAgent as plain Python (not LangGraph) | The flow is deterministic and not LLM-driven at the supervisor level. LLM calls are delegated to sub-agents. The current structure is readable, testable, and avoids LangGraph overhead where it adds no value. |
| `PortfolioManagerAgentV2` as a no-research variant | Allows verifying the Alpaca order pipeline (price fetch → order → fill → persist) independently of the Ollama research pipeline, which can hang on limited hardware. |
