"""LangChain tools available to the ChatAgent LLM via tool calling.

Tools
-----
get_candlebar_data   — real OHLCV history from Alpha Vantage (cached locally)
run_backtest         — runs a named setup from the DB against real historical data
get_recommendation   — returns BUY/SELL/HOLD/WAIT + one-line reason for a ticker
"""

from __future__ import annotations

from datetime import datetime, timedelta

import uuid

from langchain_core.tools import tool

from backtest import Backtester, SetupStore, get_ohlcv_with_indicators, setup_from_dict
from db.session import get_session
from db.models import PortfolioAccount

_store = SetupStore()


# ── Tool 1: Candlebar data ────────────────────────────────────────────────────

@tool
def get_candlebar_data(ticker: str, days: int, time_interval: str) -> dict:
    """Return historical OHLCV candlebar data for a stock ticker.

    Args:
        ticker:        Stock symbol (e.g. "NVDA")
        days:          Number of trading days of history to return
        time_interval: Bar interval — only "1d" (daily) is currently supported

    Returns:
        JSON with ticker, time_interval, and a list of OHLCV bars.
    """
    df = get_ohlcv_with_indicators(ticker, lookback_days=days)

    bars = [
        {
            "date":   str(idx.date()),
            "open":   round(row["open"],   2),
            "high":   round(row["high"],   2),
            "low":    round(row["low"],    2),
            "close":  round(row["close"],  2),
            "volume": int(row["volume"]),
        }
        for idx, row in df.iterrows()
    ]

    return {
        "responseType":  "CandlebarData",
        "ticker":        ticker.upper(),
        "time_interval": time_interval,
        "days":          days,
        "bars":          bars,
    }


# ── Tool 2: Backtest ──────────────────────────────────────────────────────────

@tool
def run_backtest(ticker: str, days: int, setup_name: str) -> dict:
    """Run a backtest of a named trading setup against real historical data.

    Args:
        ticker:     Stock symbol (e.g. "AAPL")
        days:       Number of calendar days of history to test against
        setup_name: Name of a setup stored in the setup database

    Returns:
        JSON with summary metrics, trade log, and the underlying candle data.
    """
    definition = _store.get_definition(setup_name)
    if definition is None:
        available = [s["name"] for s in _store.list()]
        return {
            "error":     f"Setup '{setup_name}' not found in the database.",
            "available": available,
        }

    setup = setup_from_dict(definition)
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    bt = Backtester(
        ticker=ticker,
        setup=setup,
        start_date=start_date,
        lookback_days=days + 300,   # extra history for indicator warmup
    )
    metrics = bt.run()

    if "error" in metrics:
        return {"responseType": "BackTestResults", "error": metrics["error"]}

    trades = [
        {
            "entry_date":  t.entry_date,
            "entry_price": round(t.entry_price, 2),
            "exit_date":   t.exit_date,
            "exit_price":  round(t.exit_price, 2),
            "pnl_pct":     round(t.pnl_pct, 2),
            "exit_reason": t.exit_reason,
            "result":      "win" if t.pnl_pct > 0 else "loss",
        }
        for t in bt.trades
    ]

    candle_bars = [
        {
            "date":  str(idx.date()),
            "open":  round(row["open"],  2),
            "high":  round(row["high"],  2),
            "low":   round(row["low"],   2),
            "close": round(row["close"], 2),
        }
        for idx, row in bt.df.iterrows()
    ]

    return {
        "responseType": "BackTestResults",
        "summary":      metrics,
        "trades":       trades,
        "candle_data":  candle_bars,
    }


# ── Tool 3: Recommendation ───────────────────────────────────────────────────

@tool
def get_recommendation(ticker: str) -> dict:
    """Analyse the latest technical indicators for a stock and return a trading
    recommendation of BUY, SELL, HOLD, or WAIT with a brief reason.

    Use this tool when the user asks questions like:
      - "Should I buy NVDA?"
      - "What do you think about AAPL?"
      - "Is TSLA a good trade right now?"
      - "Give me a recommendation on MSFT"
      - "What's your call on AMD?"

    Args:
        ticker: Stock symbol (e.g. "NVDA")

    Returns:
        JSON with "recommendation" (BUY/SELL/HOLD/WAIT) and "reason" (1-2 sentences).
    """
    df = get_ohlcv_with_indicators(ticker, lookback_days=60)
    row = df.iloc[-1]   # most recent bar

    rsi          = row["rsi"]
    macd_up      = bool(row["macd_crossover_up"])
    macd_down    = bool(row["macd_crossover_down"])
    above_sma50  = bool(row["price_above_sma50"])
    above_sma200 = bool(row["price_above_sma200"])
    adx          = row["adx"]
    bb_pct       = row["bb_pct"]
    ema20_rising = bool(row["ema20_rising"])

    recommendation = "WAIT"
    reason = ""

    # ── BUY signals ──────────────────────────────────────────────────────────
    if (rsi < 35 and macd_up and above_sma50 and adx > 20):
        recommendation = "BUY"
        reason = (
            f"{ticker.upper()} is oversold (RSI {rsi:.1f}) with a fresh MACD crossover up "
            f"and is trading above its 50-day SMA in a trending market (ADX {adx:.1f}). "
            "Conditions align with a high-probability long entry."
        )
    elif (ema20_rising and above_sma50 and bool(row["touched_ema20"])
          and bool(row["closed_above_ema20"])
          and (bool(row["hammer"]) or bool(row["bullish_engulfing"]))):
        recommendation = "BUY"
        reason = (
            f"{ticker.upper()} pulled back to its rising 20 EMA and printed a reversal candle "
            f"(RSI {rsi:.1f}, price above SMA-50). Classic 20 EMA pullback entry."
        )

    # ── SELL signals ─────────────────────────────────────────────────────────
    elif (rsi > 70 and macd_down):
        recommendation = "SELL"
        reason = (
            f"{ticker.upper()} is overbought (RSI {rsi:.1f}) and MACD has crossed down, "
            "signalling momentum is fading. Consider reducing or exiting long positions."
        )
    elif (bb_pct > 0.95 and rsi > 65 and not above_sma200):
        recommendation = "SELL"
        reason = (
            f"{ticker.upper()} is stretched near the top of its Bollinger Band (BB% {bb_pct:.2f}) "
            f"with elevated RSI ({rsi:.1f}) and trading below its 200-day SMA. Risk/reward favours caution."
        )

    # ── HOLD signals ─────────────────────────────────────────────────────────
    elif (above_sma50 and above_sma200 and 40 < rsi < 65):
        recommendation = "HOLD"
        reason = (
            f"{ticker.upper()} is in a healthy uptrend (above SMA-50 and SMA-200) "
            f"with RSI at a neutral {rsi:.1f}. No clear entry or exit signal — hold existing positions."
        )

    # ── WAIT — no clear signal ────────────────────────────────────────────────
    else:
        recommendation = "WAIT"
        reason = (
            f"{ticker.upper()} does not show a clear setup at this time "
            f"(RSI {rsi:.1f}, ADX {adx:.1f}, {'above' if above_sma50 else 'below'} SMA-50). "
            "Wait for a more defined signal before acting."
        )

    return {
        "responseType":    "Recommendation",
        "ticker":          ticker.upper(),
        "recommendation":  recommendation,
        "reason":          reason,
        "indicators": {
            "rsi":           round(rsi, 1),
            "adx":           round(adx, 1),
            "bb_pct":        round(bb_pct, 2),
            "above_sma50":   above_sma50,
            "above_sma200":  above_sma200,
            "ema20_rising":  ema20_rising,
            "macd_cross_up": macd_up,
        },
    }


# ── Tool 4: Create portfolio account ─────────────────────────────────────────

@tool
def create_portfolio_account(
    broker: str,
    account_id: str,
    display_name: str = "",
    is_paper: bool = True,
    cash: float = 0.0,
    equity: float = 0.0,
) -> dict:
    """Create and persist a new portfolio account in the database.

    Use this tool when the user asks to add, create, or register a new
    portfolio account or brokerage account. Examples:
      - "Add a new Alpaca paper account with account ID ABC123"
      - "Create a portfolio account for my live Alpaca account"
      - "Register my TD Ameritrade account"

    Args:
        broker:       Broker name (e.g. "alpaca", "td_ameritrade")
        account_id:   The broker-assigned account identifier
        display_name: Optional friendly label for this account
        is_paper:     True for paper/simulated trading, False for live (default True)
        cash:         Starting cash balance (default 0.0)
        equity:       Starting equity value (default 0.0)

    Returns:
        JSON with the created account details or an error message.
    """
    try:
        with get_session() as session:
            existing = (
                session.query(PortfolioAccount)
                .filter_by(broker=broker.lower(), account_id=account_id)
                .first()
            )
            if existing:
                return {
                    "responseType": "PortfolioAccount",
                    "status": "already_exists",
                    "id": existing.id,
                    "broker": existing.broker,
                    "account_id": existing.account_id,
                    "display_name": existing.display_name,
                    "is_paper": existing.is_paper,
                }

            account = PortfolioAccount(
                id=str(uuid.uuid4()),
                broker=broker.lower(),
                account_id=account_id,
                display_name=display_name or f"{broker} {account_id}",
                is_paper=is_paper,
                cash=cash,
                equity=equity,
            )
            session.add(account)
            session.flush()
            result = {
                "responseType": "PortfolioAccount",
                "status": "created",
                "id": account.id,
                "broker": account.broker,
                "account_id": account.account_id,
                "display_name": account.display_name,
                "is_paper": account.is_paper,
                "cash": account.cash,
                "equity": account.equity,
            }

        return result
    except Exception as e:
        return {"responseType": "PortfolioAccount", "status": "error", "error": str(e)}


# ── Tool 5: List portfolio accounts ──────────────────────────────────────────

@tool
def list_portfolio_accounts() -> dict:
    """List all portfolio accounts stored in the database.

    Use this tool when the user asks to see, list, or show their accounts.
    Examples:
      - "Show me my accounts"
      - "List all portfolio accounts"
      - "What accounts do I have?"

    Returns:
        JSON with a list of portfolio accounts.
    """
    try:
        with get_session() as session:
            accounts = session.query(PortfolioAccount).order_by(PortfolioAccount.created_at).all()
            result = [
                {
                    "id":           a.id,
                    "broker":       a.broker,
                    "account_id":   a.account_id,
                    "display_name": a.display_name,
                    "is_paper":     a.is_paper,
                    "cash":         a.cash,
                    "equity":       a.equity,
                    "created_at":   a.created_at.isoformat() if a.created_at else None,
                }
                for a in accounts
            ]
        return {"responseType": "PortfolioAccountList", "accounts": result, "total": len(result)}
    except Exception as e:
        return {"responseType": "PortfolioAccountList", "status": "error", "error": str(e)}


# ── Exports ───────────────────────────────────────────────────────────────────

CHAT_AGENT_TOOLS = [get_candlebar_data, run_backtest, get_recommendation, create_portfolio_account, list_portfolio_accounts]
