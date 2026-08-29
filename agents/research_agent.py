"""LangGraph agent that uses RAG + price data to make BUY/SELL/HOLD decisions."""

import json
import re

import yfinance as yf
from typing import Annotated, TypedDict
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from config import ANTHROPIC_API_KEY, AGENT_MODEL, MODEL_PROVIDER
from tools.rag_yahoo import semantic_search


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
    try:
        info = yf.Ticker(ticker).fast_info
        hist = yf.Ticker(ticker).history(period="1d")
        current = hist["Close"].iloc[-1] if not hist.empty else "N/A"
        return (
            f"{ticker}: price=${current:.2f}, "
            f"52w_high=${info.year_high:.2f}, "
            f"52w_low=${info.year_low:.2f}, "
            f"market_cap=${info.market_cap/1e9:.1f}B"
        )
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
