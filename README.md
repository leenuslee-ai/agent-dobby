# Agent Dobby — AI-Powered Automated Trading Pipeline

An AI-powered autonomous trading system that combines LLM reasoning, technical indicator analysis, RAG-based news sentiment, and brokerage execution. It monitors a watchlist of stocks, evaluates entry and exit conditions using named trading setups, executes orders via Alpaca, and exposes a conversational chat interface for natural language control and oversight.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Project Structure](#project-structure)
- [Agents](#agents)
- [Tools](#tools)
- [Chat Interface](#chat-interface)
- [Jobs & Schedulers](#jobs--schedulers)
- [Trading Setups](#trading-setups)
- [Backtesting](#backtesting)
- [Database Schema](#database-schema)
- [Configuration & Environment Variables](#configuration--environment-variables)
- [Setup & Installation](#setup--installation)
- [Running the System](#running-the-system)
- [Mock Data & Simulation](#mock-data--simulation)
- [Tech Stack](#tech-stack)

---

## Architecture Overview

```
External Services          Tools Layer               Agents Layer
─────────────────    ─────────────────────────    ──────────────────────────
Alpha Vantage API  → alphavantage_data.py       → BuyTechEvaluatorAgent
Alpaca Broker API  → trade_executor_tool.py     → CurrentHoldingsEvaluatorAgent
Yahoo Finance RSS  → rag_yahoo/pipeline.py      → ResearchAgent (LangGraph)
ChromaDB (local)   → rag_yahoo/vector_store.py  → PortfolioManagerAgent
PostgreSQL (local) → tools/db/                  → ChatAgent (LangGraph)
                                                     ↑
                              Schedulers     Chat REST API (FastAPI)
                   ────────────────────────  ──────────────────────
                   portfolio_manager_scheduler  POST /login
                   rag_data_ingester            POST /whatnext
                   pm_simulation_runner
```

---

## Project Structure

```
agent-dobby/
├── agents/                        # Decision-making agents
│   ├── portfolio_manager_agent.py     # Supervisor agent (per account)
│   ├── portfolio_manager_agent_v2.py  # V2: skips research, direct technical eval
│   ├── buy_tech_evaluator_agent.py    # Evaluates buy entry conditions
│   ├── current_holdings_evaluator_agent.py  # Evaluates exit/sell conditions
│   ├── research_agent.py              # LangGraph RAG + price research agent
│   └── evaluator_helpers.py           # Shared condition eval + order polling
│
├── chat_support/                  # Conversational interface
│   ├── chat_api.py                    # FastAPI REST endpoints (/login, /whatnext)
│   ├── chat_agent.py                  # LangGraph ReAct agent with MemorySaver
│   ├── chat_agent_tools.py            # Tool registry (18 tools)
│   ├── backtest_tools.py              # Backtest LangChain tools
│   ├── portfolio_tools.py             # Account + holdings tools
│   ├── pm_run_tools.py                # PM scheduler run tools
│   ├── setup_tools.py                 # Trade setup CRUD tools
│   └── watchlist_tools.py             # Watchlist CRUD tools
│
├── tools/
│   ├── alphavantage/
│   │   ├── alphavantage_data.py       # OHLCV fetch + 40+ indicator computation
│   │   └── cache/                     # CSV cache (1 file per ticker)
│   ├── alpaca/
│   │   └── trade_executor_tool.py     # Alpaca order execution + account info
│   ├── rag_yahoo/
│   │   ├── ingestion.py               # RSS fetch + LLM summarization
│   │   ├── vector_store.py            # ChromaDB embed + semantic search
│   │   └── pipeline.py                # Orchestrate ingest → embed → store
│   ├── trade_setup/
│   │   ├── setup_store.py             # SQLite-backed setup storage
│   │   ├── setup_schema.py            # Setup dataclass + factory
│   │   └── condition_registry.py      # Named conditions + formula engine
│   ├── db/
│   │   ├── models.py                  # SQLAlchemy ORM models
│   │   ├── session.py                 # Connection pooling
│   │   ├── portfolio_data.py          # Account CRUD + cash management
│   │   ├── trade_data.py              # Trade CRUD + FIFO close matching
│   │   ├── watchlist_data.py          # Watchlist CRUD
│   │   ├── backtest_run_data.py       # Backtest run persistence
│   │   └── pm_agent_runs.py           # PM scheduler run logging
│   └── mock_data/
│       ├── generate_mock_news.py      # Synthetic news for test tickers
│       └── mock_executor.py           # Simulated order fills
│
├── backtest/
│   ├── backtester.py                  # Core simulation engine
│   ├── backtest_runner.py             # Multi-ticker comparison CLI
│   └── example_setups.py             # Pre-built setup templates
│
├── jobs/
│   ├── portfolio_manager_scheduler.py # Hourly market-hours scheduler
│   ├── rag_data_ingester.py           # 3x daily news ingestion
│   └── pm_simulation_runner.py        # Date-range simulation runner
│
├── chroma_db/                     # ChromaDB vector store (local, persistent)
├── logs/                          # Agent run and simulation logs
├── config.py                      # Environment-driven settings
├── .env                           # Credentials and feature flags
└── requirements.txt
```

---

## Agents

### ResearchAgent (`agents/research_agent.py`)

A LangGraph ReAct agent that decides BUY/SELL/HOLD/WAIT on a ticker by combining RAG news retrieval with live price data.

**Tools used:** `search_news` (ChromaDB semantic search), `get_stock_price` (yfinance)  
**Output:** `{"recommendation": "BUY|SELL|HOLD|WAIT", "reason": "..."}`  
**Used by:** `PortfolioManagerAgent` to filter the watchlist to BUY candidates  
**Graph:** `agent → tools → agent → ... → END`

### BuyTechEvaluatorAgent (`agents/buy_tech_evaluator_agent.py`)

Deterministic agent that evaluates whether the latest price bar meets all entry conditions defined in a named trading setup.

**Output:** `{"decision": "BUY|WAIT", "conditions": {"label": "MET|NOT MET"}, "reason": "..."}`  
**Methods:** `evaluate(ticker, setup_name)`, `evaluate_many(pairs)` (parallel via ThreadPoolExecutor)  
**Used by:** `PortfolioManagerAgent` after research filter

### CurrentHoldingsEvaluatorAgent (`agents/current_holdings_evaluator_agent.py`)

Evaluates all open holdings for exit conditions (exit rules, stop-loss, take-profit) and executes SELL orders for triggered positions.

**Process:** Load open holdings → parallel exit evaluation → sequential SELL execution → persist closes  
**Used by:** `PortfolioManagerAgent` (runs in background thread concurrently with buy pipeline)

### PortfolioManagerAgent (`agents/portfolio_manager_agent.py`)

Supervisor agent that orchestrates one complete trading cycle per account.

**Per-run flow:**
1. Launch `CurrentHoldingsEvaluatorAgent` in a background thread
2. Build `(ticker, setup)` pairs from watchlist
3. Filter via `ResearchAgent` → keep BUY recommendations only
4. Filter via `BuyTechEvaluatorAgent.evaluate_many()` → keep technical BUYs only
5. Execute buy orders sequentially (checks cash balance before each order)
6. Await holdings evaluator (5-minute timeout)
7. Persist run summary to DB

**Called by:** `portfolio_manager_scheduler` (hourly during market hours)

### PortfolioManagerAgentV2 (`agents/portfolio_manager_agent_v2.py`)

Lightweight version that skips `ResearchAgent` entirely — goes straight from watchlist to technical evaluation and Alpaca order execution. Used to verify the Alpaca buy pipeline independently of the LLM.

### ChatAgent (`chat_support/chat_agent.py`)

LangGraph ReAct agent with per-thread conversation memory (`MemorySaver`). Provides a conversational interface for all system operations.

**18 tools bound:** candlebar data, recommendations, backtests, setups, watchlist, accounts, holdings, trades, PM runs  
**Special behavior:** Tool responses with `already_formatted=True` bypass LLM re-narration for clean frontend output

---

## Tools

### Alpha Vantage (`tools/alphavantage/alphavantage_data.py`)

Fetches and caches full daily OHLCV history from Alpha Vantage, then computes 40+ technical indicators locally using the `ta` library.

**Indicators computed:**

| Category | Indicators |
|----------|-----------|
| Trend | SMA-20/50/200, EMA-8/12/20/21/26, ADX |
| Momentum | RSI-14, RSI-2, MACD, MACD signal/hist, Stochastic K/D |
| Volatility | Bollinger Bands (upper/lower/mid/pct), ATR |
| Volume | OBV, Volume SMA-20 |
| Derived | MACD crossovers, golden/death cross, EMA crossovers/pullbacks, hammer candle, bullish engulfing |

**Cache strategy:** CSV files in `tools/alphavantage/cache/`, refreshed after 23 hours.

### Alpaca Order Execution (`tools/alpaca/trade_executor_tool.py`)

LangChain tools for placing market orders and querying account state via the Alpaca REST API.

| Tool | Purpose |
|------|---------|
| `buy_market_order(ticker, qty)` | Place a market BUY order |
| `sell_market_order(ticker, qty)` | Place a market SELL order |
| `get_positions()` | List all open Alpaca positions |
| `get_account_info()` | Buying power, cash, portfolio value |
| `get_order_status(order_id)` | Check fill status of an order |
| `cancel_all_orders()` | Cancel all open/pending orders |

Switches between paper and live trading via `ALPACA_PAPER` env var.

### RAG News Pipeline (`tools/rag_yahoo/`)

Ingests financial news from Yahoo Finance RSS feeds, summarizes with an LLM, embeds with `all-MiniLM-L6-v2`, and stores in a local ChromaDB vector database for semantic search.

| Module | Purpose |
|--------|---------|
| `ingestion.py` | Fetch RSS, filter by ticker, summarize with Claude Haiku or Ollama |
| `vector_store.py` | Embed summaries, upsert to ChromaDB, semantic search |
| `pipeline.py` | Orchestrate ingest → embed → store |

### Condition Registry (`tools/trade_setup/condition_registry.py`)

Maps named condition types to callable functions that operate on indicator DataFrames. Supports 50+ conditions across RSI, MACD, moving averages, Bollinger Bands, Stochastic, ADX, volume, and candlestick patterns. Also supports a `"formula"` escape hatch for custom expressions:

```json
{"type": "formula", "params": {"expr": "rsi < 40 and close > ema_20"}}
```

---

## Chat Interface

### REST API (`chat_support/chat_api.py`)

```
POST /login      {"username": "lee", "password": "lee"}  →  {"threadId": "..."}
POST /whatnext   {"threadId": "...", "message": "..."}   →  {"response": {...}, "trace": [...]}
```

### Chat Agent Tools (18 total)

| Tool | Intent |
|------|--------|
| `get_candlebar_data` | OHLCV price history |
| `get_recommendation` | BUY/SELL/HOLD/WAIT on a ticker |
| `run_backtest` | Run a backtest for ticker + setup |
| `list_backtest_runs` | List saved backtest runs |
| `get_backtest_result` | Retrieve backtest by ID |
| `save_trade_setup` | Create or update a trading setup |
| `list_trade_setups` | List all saved setups |
| `get_trade_setup` | Get one setup by name |
| `add_watchlist_entry` | Add a ticker to the watchlist |
| `update_watchlist_entry` | Update an existing watchlist entry |
| `list_watchlist` | Show the active watchlist |
| `create_portfolio_account` | Register a new brokerage account |
| `list_portfolio_accounts` | List all accounts |
| `get_portfolio_holdings` | All holdings (open + closed) |
| `get_open_portfolio_holdings` | Open positions only |
| `get_portfolio_trades` | All trade transactions |
| `list_pm_run_results` | List PM scheduler run summaries |
| `get_pm_run_result` | Get one PM run by ID |

### Example Queries

```
"Should I buy NVDA?"
"How is it going with PaperAcct1?"
"List PM runs for account PaperAcct1 from September"
"Run a backtest for AAPL over the last 300 days using the RSI14_Below30 setup"
"Add MSFT to the watchlist with setup RSI_MACD_TREND"
"Show me the watchlist"
"What did the agent buy this week?"
```

---

## Jobs & Schedulers

### Portfolio Manager Scheduler (`jobs/portfolio_manager_scheduler.py`)

Runs `PortfolioManagerAgent` for every registered account, hourly during market hours.

- **Schedule:** Mon–Fri, 9:30AM–4:00PM US/Eastern
- **Parallelism:** One agent per account via `ThreadPoolExecutor`

```bash
python -m jobs.portfolio_manager_scheduler        # start scheduler
python -m jobs.portfolio_manager_scheduler --now  # run once immediately
```

### RAG Data Ingester (`jobs/rag_data_ingester.py`)

Fetches fresh financial news, summarizes, embeds, and stores to ChromaDB.

- **Schedule:** 7AM, 12PM, 8PM US/Eastern, Mon–Fri
- **State:** Tracks last run time in `jobs/.rag_ingester_state.json`

```bash
python -m jobs.rag_data_ingester          # start scheduler
python -m jobs.rag_data_ingester --now    # run once immediately
python -m jobs.rag_data_ingester --reset  # clear state and re-ingest
```

### PM Simulation Runner (`jobs/pm_simulation_runner.py`)

Runs the portfolio manager agent day-by-day over a historical date range using mock data.

```bash
python3 -m jobs.pm_simulation_runner \
  --account <account-uuid> \
  --start 2026-09-04 \
  --end 2026-09-30
```

---

## Trading Setups

A trading setup defines named entry and exit conditions, risk parameters, and position sizing. Setups are stored in a local SQLite database and referenced by name throughout the system.

```json
{
  "name": "RSI_MACD_TREND",
  "description": "Enter when RSI is oversold and MACD crosses up, confirming trend via SMA-50 and ADX.",
  "definition": {
    "entry_conditions": [
      {"label": "RSI(14) < 35",          "type": "rsi_below",         "params": {"value": 35}},
      {"label": "MACD crossover up",      "type": "macd_crossover_up", "params": {}},
      {"label": "Price above SMA(50)",    "type": "price_above_sma",   "params": {"period": 50}},
      {"label": "ADX > 20",              "type": "adx_above",         "params": {"value": 20}}
    ],
    "exit_conditions": [
      {"label": "RSI(14) > 70",          "type": "rsi_above",          "params": {"value": 70}},
      {"label": "MACD crossover down",   "type": "macd_crossover_down","params": {}}
    ],
    "stop_loss_pct":   0.05,
    "take_profit_pct": 0.15,
    "position_type":   "equity_pct",
    "position_value":  0.10
  }
}
```

**Position types:** `equity_pct` (% of account equity), `cash_pct` (% of available cash), `fixed_qty` (fixed number of shares)

---

## Backtesting

The backtester replays a setup against historical OHLCV + indicator data to measure performance.

```bash
# Single ticker
python -m backtest.backtest_runner AAPL RSI_MACD_TREND --days 365

# Multiple tickers (comparison)
python -m backtest.backtest_runner AAPL NVDA TSLA
```

**Metrics returned:** total return, win rate, max drawdown, Sharpe ratio, number of trades, average hold time

---

## Database Schema

Uses **PostgreSQL** for trade and account data, **SQLite** for setup definitions, and **ChromaDB** for the news vector store.

### PostgreSQL Tables

| Table | Purpose |
|-------|---------|
| `portfolio_accounts` | Registered brokerage accounts (broker, display name, cash, equity, paper/live) |
| `portfolio_holdings` | Individual open lots (ticker, qty, avg cost, setup, status) |
| `close_trade_references` | FIFO links between open lots and close transactions |
| `trade_transactions` | All buy/sell trades (side, qty, price, filled_at, broker order ID) |
| `watchlist_entries` | Tickers + associated setup names |
| `backtest_runs` | Saved backtest results (ticker, setup, metrics, trades) |
| `pm_agent_runs` | PortfolioManagerAgent run summaries (buys, sells, research results, elapsed) |

**Cash tracking:** `portfolio_accounts.cash` is decremented on BUY Open and incremented on SELL Close within the same DB transaction as `save_trade()`.

**FIFO matching:** When a SELL close is recorded, open lots are matched oldest-first via `close_trade_references`.

---

## Configuration & Environment Variables

All values are loaded from `.env` via `config.py`.

| Variable | Description | Example |
|----------|-------------|---------|
| `ANTHROPIC_API_KEY` | Anthropic API key for Claude models | `sk-ant-...` |
| `MODEL_PROVIDER` | LLM provider: `anthropic`, `ollama`, `qwen`, `gemma` | `anthropic` |
| `ALPHAVANTAGE_API_KEY` | Alpha Vantage API key | `96L69W08H5N5RBZU` |
| `ALPACA_API_KEY` | Alpaca brokerage API key | `PK75HRHLO...` |
| `ALPACA_SECRET_KEY` | Alpaca brokerage secret | `3dD5o17S...` |
| `ALPACA_PAPER` | `true` for paper trading, `false` for live | `true` |
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://dobby:pass@localhost:5432/agent_dobby` |
| `CHAT_AGENT_TRACE` | Include step-by-step trace in chat API response | `false` |
| `MOCK_STOCKS_ENABLED` | Use synthetic mock tickers instead of live data | `false` |
| `MOCK_SIMULATION_DATE` | Pin the simulation date (for backtests) | `2026-09-04` |
| `PYTHONUNBUFFERED` | Disable Python stdout buffering | `1` |

**Mock tickers** (when `MOCK_STOCKS_ENABLED=true`): `DOBBY`, `OWALA`, `MINI`, `LUCAS`, `PILLOW`

---

## Setup & Installation

### Prerequisites

- Python 3.11+
- PostgreSQL 14+
- [Ollama](https://ollama.ai) (optional, for local LLM)
- Alpaca account (paper trading is free at [alpaca.markets](https://alpaca.markets))
- Alpha Vantage API key (free tier available)

### Install

```bash
git clone <repo-url>
cd agent-dobby
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Configure

```bash
cp .env.example .env
# Edit .env with your API keys and database URL
```

### Database

```bash
# Create PostgreSQL user and database
createuser dobby -P
createdb -O dobby agent_dobby

# Run migrations / create tables
python -m tools.db.init_db
```

### Generate Mock Data (optional)

```bash
python -m tools.mock_data.generate_mock_news
```

---

## Running the System

### Chat API

```bash
uvicorn chat_support.chat_api:app --reload --port 8800
```

### Portfolio Manager Scheduler

```bash
# Foreground
python -m jobs.portfolio_manager_scheduler

# Background
nohup python3 -m jobs.portfolio_manager_scheduler > logs/pm_scheduler.log 2>&1 &
```

### RAG News Ingester

```bash
# Foreground
python -m jobs.rag_data_ingester

# Background
nohup python3 -m jobs.rag_data_ingester > logs/rag_ingester.log 2>&1 &
```

### Run PM Agent Manually

```bash
# With research (full pipeline)
python3 -m agents.portfolio_manager_agent <account-uuid>

# Without research (technical eval + Alpaca only)
python3 -m agents.portfolio_manager_agent_v2 <account-uuid>
```

### Reset Account Cash

```bash
python3 -c "
from tools.db.portfolio_data import set_account_cash
set_account_cash('<account-uuid>', 100000.0)
"
```

---

## Mock Data & Simulation

The system includes five synthetic tickers (`DOBBY`, `OWALA`, `MINI`, `LUCAS`, `PILLOW`) with pre-generated OHLCV data and news articles for local testing without live API calls.

```bash
# Enable in .env
MOCK_STOCKS_ENABLED=true
MOCK_SIMULATION_DATE=2026-09-04

# Run simulation over a date range
nohup python3 -m jobs.pm_simulation_runner \
  --account <uuid> \
  --start 2026-09-04 \
  --end 2026-10-31 \
  > logs/pm_simulation.log 2>&1 &
```

In mock mode:
- OHLCV data is loaded from `tools/alphavantage/cache/` (never calls Alpha Vantage API)
- Orders are simulated via `mock_executor.py` (never calls Alpaca)
- `ResearchAgent` skips the LLM and returns BUY for all mock tickers
- `filled_at` timestamps use `MOCK_SIMULATION_DATE`

---

## Tech Stack

| Category | Libraries |
|----------|-----------|
| **LLM / Agents** | `langchain`, `langchain-anthropic`, `langchain-ollama`, `langgraph`, `anthropic` |
| **Brokerage** | `alpaca-py` |
| **Market Data** | `yfinance`, `requests` (Alpha Vantage) |
| **Technical Analysis** | `ta`, `pandas`, `numpy` |
| **Vector DB / Embeddings** | `chromadb`, `sentence-transformers` (all-MiniLM-L6-v2) |
| **Web API** | `fastapi`, `uvicorn`, `pydantic` |
| **Database** | `sqlalchemy`, `psycopg2-binary` |
| **Scheduling** | `apscheduler`, `pytz` |
| **RSS Parsing** | `feedparser` |
| **Backtesting** | `backtesting` |

https://youtu.be/D3oHm8Lo7_E
