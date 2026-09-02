"""Portfolio Manager Agent

A LangGraph agent that manages your portfolio by:
  - Reading your current positions and account balance (Alpaca)
  - Pulling price data and technical indicators (Alpha Vantage)
  - Searching market sentiment (ChromaDB RAG)
  - Reasoning against your trading setup instructions
  - Optionally executing trades (Alpaca)
  - Logging every reasoning step so you can audit and refine your setups

Usage:
    python portfolio_manager_test_agent.py

Or import and call:
    from .portfolio_manager_test_agent import run
    result = run("NVDA is showing RSI < 30 on the daily and MACD crossover — is this a buy?")
"""

import json
import textwrap
from datetime import datetime
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from config import ANTHROPIC_API_KEY, AGENT_MODEL, MODEL_PROVIDER
from tools.rag_yahoo import semantic_search
from tools.alpaca import TRADING_TOOLS
from tools.alphavantage import ALPHAVANTAGE_TOOLS


# ── RAG sentiment tool ────────────────────────────────────────────────────────

@tool
def search_market_sentiment(ticker: str) -> str:
    """Search the local news vector DB for market sentiment on a ticker.
    Returns recent news summaries with sentiment ratings (-5 to +5)."""
    hits = semantic_search(ticker, ticker=ticker)
    if not hits:
        hits = semantic_search(f"{ticker} stock news outlook")
    if not hits:
        return f"No sentiment data found for {ticker}."
    lines = []
    for h in hits:
        meta = h["metadata"]
        rating = meta.get("rating", "?")
        lines.append(
            f"  [sentiment={rating:+}] [{meta.get('published', '')}] {h['content']}"
        )
    return f"{ticker} market sentiment (from local news DB):\n" + "\n".join(lines)


# ── All tools ─────────────────────────────────────────────────────────────────

ALL_TOOLS = [search_market_sentiment] + ALPHAVANTAGE_TOOLS + TRADING_TOOLS


# ── LLM factory ──────────────────────────────────────────────────────────────

def _build_llm(tools: list):
    if MODEL_PROVIDER in ("ollama", "qwen"):
        from langchain_ollama import ChatOllama
        return ChatOllama(model=AGENT_MODEL, temperature=0).bind_tools(tools)
    
    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(
        model=AGENT_MODEL,
        api_key=ANTHROPIC_API_KEY,
        max_tokens=2048,
        temperature=0,
    ).bind_tools(tools)


# ── State ─────────────────────────────────────────────────────────────────────

class PortfolioState(TypedDict):
    messages: Annotated[list, add_messages]
    setup: str           # the user's trading setup rules (injected once at start)
    reasoning_log: list  # accumulated reasoning steps for audit


# ── System prompt ─────────────────────────────────────────────────────────────

_BASE_SYSTEM = """\
You are a disciplined portfolio manager agent. Your job is to evaluate trading opportunities \
strictly against the user's defined setup rules, then make a clear decision.

WORKFLOW — always follow this order:
1. PORTFOLIO CHECK  : Call get_account_info and get_positions to understand current state.
2. PRICE & TECHNICALS: Use Alpha Vantage tools (av_quote, av_daily, av_rsi, av_macd, av_bbands,
   av_sma, av_ema, av_adx, av_stoch) to gather the data your setup requires.
3. SENTIMENT CHECK  : Call search_market_sentiment for the ticker in question.
4. SETUP EVALUATION : Compare observed data against the user's setup rules below.
   State clearly which conditions are MET and which are NOT MET.
5. DECISION         : Output one of BUY / SELL / HOLD with position sizing if applicable.
6. EXECUTION        : Only call buy_market_order or sell_market_order if the user explicitly \
says "execute" or "place the trade". Otherwise just state the recommendation.

REASONING FORMAT — structure your final answer as:
  ## Portfolio State
  ## Technical Analysis
  ## Sentiment
  ## Setup Evaluation  (condition-by-condition checklist)
  ## Decision & Rationale
  ## Execution (if applicable)

USER'S TRADING SETUP RULES:
{setup}

IMPORTANT: Never skip the Setup Evaluation section. \
This is what allows the user to improve their setups over time."""


# ── Graph nodes ───────────────────────────────────────────────────────────────

llm = _build_llm(ALL_TOOLS)
tool_node = ToolNode(ALL_TOOLS)


def agent_node(state: PortfolioState) -> PortfolioState:
    system = _BASE_SYSTEM.format(setup=state["setup"] or "No specific setup provided — use your best judgment.")
    messages = [SystemMessage(content=system)] + state["messages"]
    response = llm.invoke(messages)
    return {"messages": [response]}


def tool_node_with_log(state: PortfolioState) -> PortfolioState:
    """Run tools and append a reasoning log entry for each call."""
    last = state["messages"][-1]
    log = list(state.get("reasoning_log", []))

    if hasattr(last, "tool_calls") and last.tool_calls:
        for tc in last.tool_calls:
            log.append({
                "timestamp": datetime.now().isoformat(),
                "step": "tool_call",
                "tool": tc["name"],
                "args": tc["args"],
            })

    # Run the actual tools via ToolNode
    result = tool_node.invoke(state)

    # Log the tool outputs
    for msg in result.get("messages", []):
        if isinstance(msg, ToolMessage):
            log.append({
                "timestamp": datetime.now().isoformat(),
                "step": "tool_result",
                "tool": msg.name,
                "output": msg.content[:500],  # cap log size
            })

    return {**result, "reasoning_log": log}


def should_continue(state: PortfolioState) -> str:
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and hasattr(last, "tool_calls") and last.tool_calls:
        return "tools"
    return END


# ── Graph ─────────────────────────────────────────────────────────────────────

graph = StateGraph(PortfolioState)
graph.add_node("agent", agent_node)
graph.add_node("tools", tool_node_with_log)
graph.set_entry_point("agent")
graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
graph.add_edge("tools", "agent")

app = graph.compile()


# ── Public API ────────────────────────────────────────────────────────────────

def run(
    instruction: str,
    setup: str = "",
    print_log: bool = True,
) -> dict:
    """Run the portfolio manager agent.

    Args:
        instruction: Your chat message, e.g. "Evaluate NVDA for a buy based on my setup"
        setup:       Your trading setup rules as plain text (injected into system prompt).
                     Leave empty to use the agent's judgment.
        print_log:   If True, print the step-by-step reasoning log after the answer.

    Returns:
        dict with keys: answer (str), reasoning_log (list)
    """
    initial_state: PortfolioState = {
        "messages": [HumanMessage(content=instruction)],
        "setup": setup,
        "reasoning_log": [],
    }

    print(f"\n{'='*70}")
    print(f"Portfolio Manager Agent | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Model: {MODEL_PROVIDER.upper()} / {AGENT_MODEL}")
    print(f"{'='*70}")
    print(f"Instruction: {instruction}\n")

    result = app.invoke(initial_state)
    answer = result["messages"][-1].content
    log = result.get("reasoning_log", [])

    print(answer)

    if print_log and log:
        print(f"\n{'─'*70}")
        print("REASONING LOG (for setup refinement):")
        print(f"{'─'*70}")
        for entry in log:
            ts = entry["timestamp"][11:19]
            if entry["step"] == "tool_call":
                args_str = json.dumps(entry["args"], ensure_ascii=False)
                print(f"[{ts}] CALL  {entry['tool']}({args_str})")
            else:
                output_preview = entry["output"].replace("\n", " ")[:120]
                print(f"[{ts}] RESULT {entry['tool']} → {output_preview}")
        print(f"{'─'*70}\n")

    return {"answer": answer, "reasoning_log": log}


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    # Example setup — replace with your own rules when running
    MY_SETUP = textwrap.dedent("""\
        ENTRY CONDITIONS (ALL must be met to BUY):
          1. RSI(14, daily) is below 35 (oversold)
          2. MACD line has crossed above the signal line in the last 3 days
          3. Price is above the 50-day SMA
          4. Market sentiment score average >= 0 (neutral or positive)
          5. ADX(14) > 20 (trend has strength)

        POSITION SIZING:
          - Risk 2% of portfolio per trade
          - Use account buying_power to calculate share count

        EXIT CONDITIONS (SELL when):
          - RSI(14) crosses above 70 (overbought)
          - MACD line crosses below signal line
          - Stop loss: -5% from entry price

        HOLD if conditions are mixed or unclear.
    """)

    instruction = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else (
        "Evaluate AAPL using my setup rules. "
        "Check technicals, sentiment, and my portfolio. "
        "Give me a BUY, SELL, or HOLD with full reasoning."
    )

    run(instruction=instruction, setup=MY_SETUP)
