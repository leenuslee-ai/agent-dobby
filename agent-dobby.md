# Agent Dobby — System Design Document

## 1. Overview

Agent Dobby is an AI-powered automated trading pipeline built in Python. It combines large language model reasoning, technical indicator analysis, RAG-based news sentiment, and brokerage execution into a cohesive system that can:

- Monitor a watchlist of stocks and evaluate entry conditions using named trading setups
- Evaluate open holdings against exit conditions and execute sell orders when triggered
- Run historical backtests of any named setup against real market data
- Ingest and summarise financial news into a local vector database for semantic search
- Expose a conversational chat interface so a human can interrogate and control the system in natural language

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
└──────────────┬────────────────────┬──────────────────┬─────────────┘
               │                    │                  │
┌──────────────▼────────────────────▼──────────────────▼─────────────┐
│                          Agents Layer                               │
│  ResearchAgent  BuyTechEvaluatorAgent  CurrentHoldingsEvaluatorAgent│
│                    PortfolioManagerAgent (supervisor)               │
└──────────────┬────────────────────┬────────────────────────────────┘
               │                    │
┌──────────────▼──────┐  ┌──────────▼──────────────────────────────┐
│   Scheduler (Jobs)  │  │          Chat Interface                  │
│  portfolio_manager  │  │  FastAPI  →  ChatAgent (LangGraph)       │
│  rag_data_ingester  │  │              13 LangChain tools          │
└─────────────────────┘  └─────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────────────┐
│                         Data Layer                                  │
│  PostgreSQL (accounts, holdings, transactions, backtest runs, ...)  │
│  SQLite SetupStore  (trading setup definitions)                     │
│  ChromaDB           (news embeddings / vector search)              │
│  Alpha Vantage CSV cache  (local OHLCV cache, refreshed daily)     │
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

#### `tools/alpaca/trade_executor_tool.py`
LangChain tools for Alpaca brokerage interaction. Supports paper and live trading via `ALPACA_PAPER` env flag.

| Tool | Description |
|---|---|
| `buy_market_order` | Place a market BUY order |
| `sell_market_order` | Place a market SELL order |
| `get_order_status` | Poll order fill status by order ID |
| `get_positions` | List all open Alpaca positions |
| `get_account_info` | Return buying power, cash, portfolio value |
| `cancel_all_orders` | Cancel all open/pending orders |

#### `tools/rag_yahoo/`
Yahoo Finance RSS ingestion, summarisation, and vector storage pipeline.
- **`ingestion.py`** — fetches RSS feeds per ticker, filters articles that mention the ticker, summarises with Claude Haiku (or local Ollama), and deduplicates by content hash
- **`vector_store.py`** — embeds articles using `all-MiniLM-L6-v2` and stores in ChromaDB
- **`pipeline.py`** — `run_pipeline(tickers, since)` orchestrates ingestion → embedding → storage

#### `tools/trade_setup/`
| File | Purpose |
|---|---|
| `setup_store.py` | SQLite-backed store for named setup definitions (JSON) |
| `setup_schema.py` | `Setup` dataclass; `setup_from_dict()` factory |
| `condition_registry.py` | Registry of condition factories: `rsi_below`, `ema_cross_above`, `volume_above_avg`, `formula`, etc. |

The condition registry uses a `lambda p: (lambda r: ...)` factory pattern so each condition is parameterised at load time and evaluated row-by-row at backtest/evaluation time.

---

### 3.2 Agents Layer

All agents are Python classes. LangGraph is used for agents that need a tool-calling ReAct loop; pure Python is used where deterministic evaluation is sufficient.

#### `ResearchAgent` (`agents/research_agent.py`)
LangGraph ReAct agent. Given a question about a ticker:
1. Calls `search_news` tool → semantic search in ChromaDB
2. Calls `get_stock_price` tool → live price from yfinance
3. Synthesises a BUY/SELL/HOLD/WAIT recommendation with reasoning

Used by `PortfolioManagerAgent` to filter the watchlist to tickers with a research-backed BUY signal before running technical evaluation.

#### `BuyTechEvaluatorAgent` (`agents/buy_tech_evaluator_agent.py`)
No LLM tool loop — purely deterministic indicator evaluation.
1. Loads a named setup from `SetupStore`
2. Fetches the latest OHLCV bar with indicators
3. Evaluates all **entry conditions** (AND logic — all must be MET)
4. Returns `BUY` or `WAIT` with a per-condition breakdown
5. Optionally generates a one-sentence reason via local Ollama

Supports `evaluate_many(pairs)` for batch evaluation of multiple `(ticker, setup)` pairs.

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
  │    b. ResearchAgent.analyze_recommendation      │ ◄── parallel (ThreadPoolExecutor)
  │       └─ Keep BUY recommendations only          │
  │    c. BuyTechEvaluatorAgent.evaluate_many       │
  │       └─ Keep BUY decisions only               │
  │    d. Execute buys sequentially                 │
  │       ├─ Size by setup's risk_percent × cash    │
  │       ├─ Place market order                     │
  │       ├─ Poll for fill                          │
  │       └─ Persist via save_trade("Open")         │
  │                                                 │
  │ 3. Await holdings evaluator (timeout 5 min)     │
  │ 4. Log run summary                              │
  └─────────────────────────────────────────────────┘
```

#### Shared helpers (`agents/evaluator_helpers.py`)
Used by both `BuyTechEvaluatorAgent` and `CurrentHoldingsEvaluatorAgent`:
- `load_setup(name)` — load from SetupStore
- `fetch_latest_row(ticker)` — fetch indicators, return most recent bar
- `evaluate_conditions(conditions, row, require_all)` — AND or OR evaluation
- `generate_reason(llm, ...)` — one-sentence LLM explanation
- `poll_order_status(client, order_id, ...)` — poll Alpaca until filled

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

The `already_formatted` flag on any tool response short-circuits the second LLM pass, ensuring consistent raw JSON responses for all 13 tools.

When `CHAT_AGENT_TRACE=true`, each response includes a `trace` array showing every tool call and result for that request.

#### Chat Agent Tools (13 tools across 4 files)

| File | Tools |
|---|---|
| `chat_agent_tools.py` | `get_candlebar_data`, `get_recommendation` |
| `backtest_tools.py` | `run_backtest`, `list_backtest_runs`, `get_backtest_result` |
| `setup_tools.py` | `save_trade_setup`, `list_trade_setups`, `get_trade_setup` |
| `watchlist_tools.py` | `add_watchlist_entry`, `update_watchlist_entry`, `list_watchlist` |
| `portfolio_tools.py` | `create_portfolio_account`, `list_portfolio_accounts` |

`save_trade_setup` uses Claude Haiku to parse a human-readable setup description into a structured JSON definition and validates all condition types against the registry before saving.

---

### 3.4 Backtester (`backtest/`)

| File | Purpose |
|---|---|
| `backtester.py` | Core `Backtester` class — simulates trades over historical data |
| `backtest_runner.py` | CLI runner — backtests all watchlist tickers against all setups |
| `example_setups.py` | Pre-built setup factories (`build_example_setup`, `build_ema_pullback_setup`) |
| `seed_setups.py` | Seeds initial setups into SetupStore |

**Backtester logic:**
1. Fetches OHLCV + indicators for the ticker
2. Iterates each bar chronologically
3. If no open trade: evaluates entry conditions (all must be MET)
4. If open trade: evaluates exit conditions (any triggers exit), checks stop-loss and take-profit
5. Position sizing: `equity_pct` (risk % of current equity), `shares`, or `dollars`
6. Computes metrics: total return, win rate, avg win/loss, max drawdown, Sharpe ratio
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
| cash | Float | Last synced cash balance |
| equity | Float | Last synced equity |

#### `portfolio_holdings`
One row per **opening transaction** (not per ticker). A ticker can have multiple open rows if bought multiple times.

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
| status | String | "filled", "cancelled", "pending" |
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

#### Other tables
- `configs` — key/value application configuration
- `trade_setups` — legacy table (not actively used; SetupStore is the active setup store)
- `backtest_transactions` — individual trade records linked to a backtest run
- `agent_logs` — structured agent activity log

### 4.2 SQLite SetupStore
Stored at `backtest_cache/setups.db`. Holds JSON setup definitions keyed by name and UUID. Used by the backtester, evaluator agents, and chat tools. Separate from PostgreSQL to keep setup definitions portable and fast to read.

### 4.3 ChromaDB
Local vector database at `./chroma_db/`. Stores embedded news article chunks. Each chunk carries metadata: `ticker`, `published`, `source`. Used by `ResearchAgent` for semantic news retrieval.

### 4.4 Alpha Vantage CSV Cache
Stored at `tools/alphavantage/cache/<TICKER>_daily.csv`. Refreshed if older than 23 hours. Means indicator computation is free after the first daily fetch.

---

## 5. Trade Lifecycle

### 5.1 Opening a Trade (BUY)
```
PortfolioManagerAgent
  → BuyTechEvaluatorAgent.evaluate() → decision: BUY
  → Alpaca: submit_order(BUY, qty)
  → poll_order_status() until filled
  → save_trade(open_close="Open")
       → creates PortfolioTransaction (side=BUY, open_close=Open)
       → creates PortfolioHolding (pending_qty=qty, closed_value=0)
```

### 5.2 Closing a Trade (SELL)
```
CurrentHoldingsEvaluatorAgent
  → evaluate exit conditions / stop-loss / take-profit
  → decision: SELL
  → Alpaca: submit_order(SELL, pending_qty)
  → poll_order_status() until filled
  → save_trade(open_close="Close")
       → creates PortfolioTransaction (side=SELL, open_close=Close)
       → FIFO matches against PortfolioHolding rows (pending_qty > 0)
       → creates CloseTradeReference rows
       → adjusts pending_qty and closed_value on each matched holding
```

---

## 6. Trading Setup Definition

Setups are stored as JSON in SQLite SetupStore. Each setup has:

```json
{
  "name": "EMA20_PB",
  "description": "EMA-20 pullback with reversal candle",
  "definition": {
    "entry_conditions": [
      { "label": "EMA-20 rising", "type": "ema_rising", "params": { "window": 20 } },
      { "label": "Touched EMA-20", "type": "touched_ema", "params": { "window": 20 } },
      { "label": "Closed above EMA-20", "type": "closed_above_ema", "params": { "window": 20 } },
      { "label": "Reversal candle", "type": "hammer_or_engulf", "params": {} }
    ],
    "exit_conditions": [
      { "label": "Price below EMA-20", "type": "price_below_ema", "params": { "period": 20 } }
    ],
    "stop_loss_pct": 0.05,
    "take_profit_pct": null,
    "position_type": "equity_pct",
    "position_value": 0.02
  }
}
```

**Entry logic:** ALL conditions must be MET (AND)
**Exit logic:** ANY condition triggers (OR), plus stop-loss and take-profit thresholds

New setups can be created via:
- The chat interface: *"Save a new setup called X with the following conditions..."*
- `save_trade_setup` tool: Claude Haiku parses plain-English descriptions into JSON

---

## 7. Configuration

All configuration is via environment variables (`.env` file):

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

---

## 8. Running the System

### Start the chat API
```bash
uvicorn chat_support.chat_api:app --reload --port 8800
```

### Start the portfolio manager scheduler
```bash
python -m jobs.portfolio_manager_scheduler        # market hours, Mon–Fri
python -m jobs.portfolio_manager_scheduler --now  # run once immediately
```

### Start the news ingestion scheduler
```bash
python -m jobs.rag_data_ingester          # 7AM, 12PM, 8PM ET Mon–Fri
python -m jobs.rag_data_ingester --now    # run once
```

### Run a backtest from the command line
```bash
python -m backtest.backtest_runner NVDA RSI_MACD_TREND --days 365
```

### Initialise the database
```bash
python -m db.init_db
```

---

## 9. Key Design Decisions

| Decision | Rationale |
|---|---|
| SetupStore (SQLite) separate from PostgreSQL | Setup definitions are portable, frequently read, and don't need relational joins. SQLite keeps them fast and self-contained. |
| `already_formatted` flag on tool responses | Prevents the chat agent's LLM from re-narrating structured data, ensuring consistent JSON output for the frontend. |
| FIFO matching for close trades | Industry-standard approach; simplest to reason about and audit. |
| `pending_qty` per holding row (not per ticker) | Allows tracking multiple opening lots separately — important for cost basis and P&L accuracy. |
| Parallel research, sequential order execution | Research is read-only and independent per ticker. Order execution modifies cash balance and must be sequential to avoid over-spending. |
| Holdings evaluation in background thread | The sell evaluation can be slow (indicator fetch + LLM reason). Running it async lets the buy pipeline proceed concurrently. |
| Local indicator computation (ta library) | No additional Alpha Vantage API calls per evaluation — all indicators are derived from the cached daily OHLCV data. |
| `WARMUP_DAYS = 250` | SMA-200 requires 200 bars minimum; 250 days of calendar data gives enough trading days after weekends and holidays. |
