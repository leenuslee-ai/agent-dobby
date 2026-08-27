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
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

from config import (
    ANTHROPIC_API_KEY,
    AGENT_MODEL,
    MODEL_PROVIDER,
    ALPHAVANTAGE_API_KEY,
    ALPHAVANTAGE_MCP_TRANSPORT,
    ALPHAVANTAGE_MCP_SSE_URL,
    ALPHAVANTAGE_MCP_COMMAND,
    ALPHAVANTAGE_MCP_ARGS,
)

# MCP tool calling requires reliable structured output.
# Override to Anthropic for this agent; Llama models frequently produce
# text descriptions instead of proper tool call payloads.
_MCP_PROVIDER = os.getenv("MCP_AGENT_PROVIDER", "anthropic").lower()
_MCP_MODEL    = os.getenv("MCP_AGENT_MODEL", AGENT_MODEL if MODEL_PROVIDER == "anthropic" else "claude-sonnet-4-6")


# ── MCP server config ─────────────────────────────────────────────────────────

def _build_mcp_server_config() -> dict:
    """Build the MultiServerMCPClient server config from .env settings."""
    if ALPHAVANTAGE_MCP_TRANSPORT in ("sse", "streamable_http"):
        # Alpha Vantage hosted MCP server uses Streamable HTTP (MCP spec 2025-03-26).
        # The API key is passed as a query param: https://mcp.alphavantage.co/mcp?apikey=KEY
        url = ALPHAVANTAGE_MCP_SSE_URL
        if ALPHAVANTAGE_API_KEY and "apikey=" not in url:
            url = f"{url}?apikey={ALPHAVANTAGE_API_KEY}"
        return {
            "alphavantage": {
                "transport": "streamable_http",
                "url": url,
            }
        }
    # stdio: spawn a local subprocess
    return {
        "alphavantage": {
            "transport": "stdio",
            "command": ALPHAVANTAGE_MCP_COMMAND,
            "args": ALPHAVANTAGE_MCP_ARGS.split(),
            "env": {"ALPHAVANTAGE_API_KEY": ALPHAVANTAGE_API_KEY},
        }
    }


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


# ── Graph builder (async — required by MCP client) ────────────────────────────

async def run_agent(question: str) -> str:
    """Connect to the Alpha Vantage MCP server, build the agent, run it, return the answer."""

    server_config = _build_mcp_server_config()
    transport = ALPHAVANTAGE_MCP_TRANSPORT.upper()

    print(f"\n{'='*70}")
    print(f"Alpha Vantage MCP Agent | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Transport : {transport}")
    if transport in ("SSE", "STREAMABLE_HTTP"):
        print(f"Server URL: {ALPHAVANTAGE_MCP_SSE_URL}")
    else:
        print(f"Command   : {ALPHAVANTAGE_MCP_COMMAND} {ALPHAVANTAGE_MCP_ARGS}")
    print(f"LLM       : {_MCP_PROVIDER.upper()} / {_MCP_MODEL}")
    print(f"{'='*70}")
    print(f"Question  : {question}\n")

    mcp_client = MultiServerMCPClient(server_config)
    tools = await mcp_client.get_tools()
    print(f"Tools loaded from MCP server ({len(tools)}): {[t.name for t in tools]}\n")

    llm = _build_llm(tools)
    tool_map = {t.name: t for t in tools}

    # ── Graph (fully async — MCP tools only support ainvoke) ───────────────

    async def call_model(state: AgentState) -> AgentState:
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
        response = await llm.ainvoke(messages)
        return {"messages": [response]}

    async def call_tools(state: AgentState) -> AgentState:
        """Async tool node — required because MCP tools only support ainvoke."""
        last = state["messages"][-1]
        results = []
        for tc in last.tool_calls:
            tool = tool_map.get(tc["name"])
            if tool is None:
                output = f"Tool '{tc['name']}' not found."
            else:
                try:
                    output = await tool.ainvoke(tc["args"])
                except Exception as e:
                    output = f"Error calling {tc['name']}: {e}"
            results.append(ToolMessage(content=str(output), tool_call_id=tc["id"]))
        return {"messages": results}

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
