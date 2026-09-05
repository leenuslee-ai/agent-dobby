"""LangGraph agent that uses RAG + price data to make BUY/SELL/HOLD decisions."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import yfinance as yf
from typing import Annotated, TypedDict
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from config import ANTHROPIC_API_KEY, AGENT_MODEL, MODEL_PROVIDER, MOCK_STOCKS, MOCK_STOCKS_ENABLED, MOCK_SIMULATION_DATE
from tools.rag_yahoo import semantic_search

_MOCK_CACHE_DIR = Path(__file__).parent.parent / "tools" / "alphavantage" / "cache"


def _get_mock_price(ticker: str) -> str:
    """Return price info for a mock ticker from the local CSV cache, up to today."""
    cache_file = _MOCK_CACHE_DIR / f"{ticker}_daily.csv"
    if not cache_file.exists():
        return f"No mock price data found for {ticker}."
    try:
        import pandas as pd
        df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
        today = MOCK_SIMULATION_DATE or datetime.now(timezone.utc).date()
        df = df[df.index.date <= today]
        if df.empty:
            return f"No price data available for {ticker} up to {today}."
        latest = df.iloc[-1]
        prev   = df.iloc[-2] if len(df) > 1 else latest
        change_pct = (latest["close"] - prev["close"]) / prev["close"] * 100
        week_ago   = df.iloc[-6]["close"] if len(df) >= 6 else df.iloc[0]["close"]
        year_high  = df["high"].max()
        year_low   = df["low"].min()
        return (
            f"{ticker} [MOCK]: price=${latest['close']:.2f} ({change_pct:+.2f}% today), "
            f"week_ago=${week_ago:.2f}, "
            f"52w_high=${year_high:.2f}, 52w_low=${year_low:.2f}, "
            f"as_of={df.index[-1].date()}"
        )
    except Exception as e:
        return f"Could not load mock price for {ticker}: {e}"


# ── Tools ────────────────────────────────────────────────────────────────────

@tool
def search_news(query: str, ticker: str = "") -> str:
    """Search the local vector DB for relevant financial news.
    Pass ticker to filter by symbol, leave empty to search all news."""
    hits = semantic_search(query, ticker=ticker if ticker else None)
    if not hits:
        return "No relevant news found."
    lines = []
    for h in hits:
        meta = h["metadata"]
        lines.append(f"[{meta['ticker']} | {meta['published']}] {h['content']}")
    return "\n\n".join(lines)


@tool
def get_stock_price(ticker: str) -> str:
    """Get current price, 52-week high/low, and market cap for a ticker."""
    if MOCK_STOCKS_ENABLED and ticker.upper() in MOCK_STOCKS:
        return _get_mock_price(ticker.upper())
    try:
        import signal

        def _timeout(signum, frame):
            raise TimeoutError("yfinance timed out")

        signal.signal(signal.SIGALRM, _timeout)
        signal.alarm(10)
        try:
            info = yf.Ticker(ticker).fast_info
            hist = yf.Ticker(ticker).history(period="1d")
            current = hist["Close"].iloc[-1] if not hist.empty else "N/A"
            result = (
                f"{ticker}: price=${current:.2f}, "
                f"52w_high=${info.year_high:.2f}, "
                f"52w_low=${info.year_low:.2f}, "
                f"market_cap=${info.market_cap/1e9:.1f}B"
            )
        finally:
            signal.alarm(0)
        return result
    except Exception as e:
        return f"Could not fetch price for {ticker}: {e}"


RESEARCH_TOOLS = [search_news, get_stock_price]

# ── LLM factory ──────────────────────────────────────────────────────────────

def _build_llm(tools: list):
    print(f"Using provider: {MODEL_PROVIDER} | agent model: {AGENT_MODEL}")
    if MODEL_PROVIDER in ("ollama", "qwen"):
        from langchain_ollama import ChatOllama
        return ChatOllama(model=AGENT_MODEL).bind_tools(tools)
    else:
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=AGENT_MODEL,
            api_key=ANTHROPIC_API_KEY,
            max_tokens=1024,
        ).bind_tools(tools)


# ── LangGraph state ──────────────────────────────────────────────────────────

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]


# ── System prompts ───────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are a financial research agent. When given a ticker or question:
1. Use search_news to retrieve relevant recent news from the vector database.
2. Use get_stock_price to get current market data.
3. Synthesize the information and provide a clear BUY / SELL / HOLD recommendation with reasoning.
Always cite the news sources you used. Be concise but thorough."""

_RECOMMENDATION_PROMPT = """You are a financial analysis agent. Analyse the ticker in the user's question using
the available tools (news search + price data), then respond with ONLY a JSON object in this exact format:
{{
  "recommendation": "<BUY|SELL|HOLD|WAIT>",
  "reason": "<one or two sentence summary>"
}}
No prose, no markdown, no explanation outside the JSON."""


# ── Graph builder ────────────────────────────────────────────────────────────

def _build_graph():
    llm = _build_llm(RESEARCH_TOOLS)
    tool_node = ToolNode(RESEARCH_TOOLS)

    def call_model(state: AgentState) -> AgentState:
        messages = [SystemMessage(content=_SYSTEM_PROMPT)] + state["messages"]
        response = llm.invoke(messages)
        return {"messages": [response]}

    def should_continue(state: AgentState) -> str:
        last = state["messages"][-1]
        if hasattr(last, "tool_calls") and last.tool_calls:
            return "tools"
        return END

    graph = StateGraph(AgentState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", tool_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    return graph.compile()


# ── Public class ─────────────────────────────────────────────────────────────

class ResearchAgent:
    def __init__(self):
        self._graph = _build_graph()

    def analyze(self, question: str) -> str:
        """Run the agent on a question and return the final text response."""
        result = self._graph.invoke({"messages": [HumanMessage(content=question)]})
        return result["messages"][-1].content

    def analyze_recommendation(self, question: str) -> dict:
        """Run the agent and return a structured BUY/SELL/HOLD/WAIT recommendation.

        Prompts that trigger this method:
          - "Should I buy NVDA?"
          - "Give me a recommendation on AAPL"
          - "Is TSLA worth buying right now?"
          - "What's your call on AMD — buy, sell, or hold?"
          - "Rate MSFT: buy or sell?"
        """
        result = self._graph.invoke({
            "messages": [
                SystemMessage(content=_RECOMMENDATION_PROMPT),
                HumanMessage(content=question),
            ]
        })
        content = result["messages"][-1].content

        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        return {"recommendation": "WAIT", "reason": content.strip()}


if __name__ == "__main__":
    agent = ResearchAgent()

    print("=== analyze ===")
    print(agent.analyze("Should I buy NVDA right now? Check the latest news and price."))

    print("\n=== analyze_recommendation ===")
    print(json.dumps(agent.analyze_recommendation("Should I buy NVDA?"), indent=2))
