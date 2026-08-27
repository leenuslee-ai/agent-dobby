"""LangGraph agent that uses RAG + price data to make BUY/SELL/HOLD decisions."""

import yfinance as yf
from typing import Annotated, TypedDict
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from config import ANTHROPIC_API_KEY, AGENT_MODEL, MODEL_PROVIDER
from tools.rag_yahoo import semantic_search
from tools.alpaca import TRADING_TOOLS


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


# ── Graph setup ──────────────────────────────────────────────────────────────

tools = [search_news, get_stock_price] + TRADING_TOOLS
tool_node = ToolNode(tools)
llm = _build_llm(tools)

SYSTEM_PROMPT = """You are a financial analysis and trading agent. When given a ticker or question:
1. Use search_news to retrieve relevant recent news from the vector database.
2. Use get_stock_price to get current market data.
3. Use get_account_info and get_positions to understand current portfolio state.
4. Synthesize the information and provide a clear BUY / SELL / HOLD recommendation with reasoning.
5. Only execute buy_market_order or sell_market_order if the user explicitly asks you to place a trade.
Always cite the news sources you used. Be concise but thorough.
IMPORTANT: Never place a real trade unless the user explicitly confirms they want to execute an order."""


def call_model(state: AgentState) -> AgentState:
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
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

app = graph.compile()


# ── Public API ───────────────────────────────────────────────────────────────

def analyze(question: str) -> str:
    """Run the agent on a question and return the final text response."""
    result = app.invoke({"messages": [HumanMessage(content=question)]})
    return result["messages"][-1].content


RECOMMENDATION_PROMPT = """You are a financial analysis agent. Analyse the ticker in the user's question using
the available tools (news search + price data), then respond with ONLY a JSON object in this exact format:
{{
  "recommendation": "<BUY|SELL|HOLD|WAIT>",
  "reason": "<one or two sentence summary>"
}}
No prose, no markdown, no explanation outside the JSON."""


def analyze_recommendation(question: str) -> dict:
    """Run the agent and return a structured BUY/SELL/HOLD/WAIT recommendation.

    The agent uses news from the vector DB and live price data to make its
    decision, then returns a plain dict with 'recommendation' and 'reason'.

    Prompts that trigger this method:
      - "Should I buy NVDA?"
      - "Give me a recommendation on AAPL"
      - "Is TSLA worth buying right now?"
      - "What's your call on AMD — buy, sell, or hold?"
      - "Rate MSFT: buy or sell?"
    """
    import json, re

    result = app.invoke({
        "messages": [
            SystemMessage(content=RECOMMENDATION_PROMPT),
            HumanMessage(content=question),
        ]
    })
    content = result["messages"][-1].content

    # Extract JSON even if the LLM wrapped it in markdown fences
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # Fallback if parsing fails
    return {"recommendation": "WAIT", "reason": content.strip()}


if __name__ == "__main__":
    import json
    print("=== analyze ===")
    print(analyze("Should I buy NVDA right now? Check the latest news and price."))

    print("\n=== analyze_recommendation ===")
    print(json.dumps(analyze_recommendation("Should I buy NVDA?"), indent=2))
