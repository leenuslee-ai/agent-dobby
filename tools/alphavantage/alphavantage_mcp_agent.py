"""Alpha Vantage MCP Agent

Connects to an Alpha Vantage MCP server (stdio subprocess or SSE remote),
loads its tools dynamically, then runs a LangGraph ReAct agent against them.

Supported MCP server transports
────────────────────────────────
stdio (default) — spawns the MCP server as a local subprocess:
    ALPHAVANTAGE_MCP_TRANSPORT=stdio
    ALPHAVANTAGE_MCP_COMMAND=uvx          # or: npx, python, etc.
    ALPHAVANTAGE_MCP_ARGS=alphavantage-mcp

    The server is started with your API key passed as an env var:
        ALPHAVANTAGE_API_KEY=<your key>   (already in .env)

SSE (remote) — connects to an already-running MCP server over HTTP:
    ALPHAVANTAGE_MCP_TRANSPORT=sse
    ALPHAVANTAGE_MCP_SSE_URL=http://localhost:8000/sse

Usage
─────
    python alphavantage_mcp_agent.py
    python alphavantage_mcp_agent.py "What is the RSI for NVDA?"
"""

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated, TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

from config import ANTHROPIC_API_KEY, AGENT_MODEL, MODEL_PROVIDER
from tools.alphavantage.alphavantage_mcp_tools import (
    get_mcp_tools,
    build_tool_node,
    build_mcp_server_config,
)

# MCP tool calling requires reliable structured output.
# Override to Anthropic for this agent; Llama models frequently produce
# text descriptions instead of proper tool call payloads.
_MCP_PROVIDER = os.getenv("MCP_AGENT_PROVIDER", "anthropic").lower()
_MCP_MODEL    = os.getenv("MCP_AGENT_MODEL", AGENT_MODEL if MODEL_PROVIDER == "anthropic" else "claude-sonnet-4-6")


# ── LLM factory ───────────────────────────────────────────────────────────────

def _build_llm(tools: list):
    if _MCP_PROVIDER == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(model=_MCP_MODEL, temperature=0).bind_tools(tools)
    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(
        model=_MCP_MODEL,
        api_key=ANTHROPIC_API_KEY,
        max_tokens=2048,
        temperature=0,
    ).bind_tools(tools)


# ── LangGraph state ───────────────────────────────────────────────────────────

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]


SYSTEM_PROMPT = """\
You are a financial analysis agent with access to Alpha Vantage market data tools.

When answering questions about stocks:
1. Use price tools (quote, daily, intraday) for current and historical prices.
2. Use technical indicator tools (RSI, MACD, Bollinger Bands, SMA, EMA, ADX, Stochastic, VWAP)
   to assess momentum, trend strength, and overbought/oversold conditions.
3. Use fundamental tools (overview, earnings) for company context.
4. Synthesize the data and give a clear, reasoned answer.

Always state which tools you called and what values you observed.
Format your final answer with clear sections: Price, Technicals, Fundamentals (if relevant), Summary."""


# ── Agent runner ──────────────────────────────────────────────────────────────

async def run_agent(question: str) -> str:
    """Connect to the Alpha Vantage MCP server, build the agent, run it, return the answer."""

    server_config = build_mcp_server_config()
    transport = os.getenv("ALPHAVANTAGE_MCP_TRANSPORT", "streamable_http").upper()

    print(f"\n{'='*70}")
    print(f"Alpha Vantage MCP Agent | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Transport : {transport}")
    print(f"LLM       : {_MCP_PROVIDER.upper()} / {_MCP_MODEL}")
    print(f"{'='*70}")
    print(f"Question  : {question}\n")

    tools, tool_map = await get_mcp_tools()
    print(f"Tools loaded from MCP server ({len(tools)}): {[t.name for t in tools]}\n")

    llm = _build_llm(tools)
    call_tools = build_tool_node(tool_map)

    async def call_model(state: AgentState) -> AgentState:
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
        response = await llm.ainvoke(messages)
        return {"messages": [response]}

    def should_continue(state: AgentState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
            return "tools"
        return END

    graph = StateGraph(AgentState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", call_tools)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    app = graph.compile()

    result = await app.ainvoke({"messages": [HumanMessage(content=question)]})
    answer = result["messages"][-1].content
    print(answer)
    return answer


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    question = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else (
        "Give me a technical analysis of AAPL: check the quote, RSI(14)"
    )
    asyncio.run(run_agent(question))
