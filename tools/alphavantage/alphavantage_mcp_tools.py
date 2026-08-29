"""Alpha Vantage MCP tools — reusable across agents.

Provides:
    get_mcp_tools()      — async: connect to MCP server, return (tools, tool_map)
    build_tool_node()    — returns an async LangGraph-compatible call_tools function
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from langchain_core.messages import ToolMessage
from langchain_mcp_adapters.client import MultiServerMCPClient

from config import (
    ALPHAVANTAGE_API_KEY,
    ALPHAVANTAGE_MCP_TRANSPORT,
    ALPHAVANTAGE_MCP_SSE_URL,
    ALPHAVANTAGE_MCP_COMMAND,
    ALPHAVANTAGE_MCP_ARGS,
)


def build_mcp_server_config() -> dict:
    """Build the MultiServerMCPClient server config from .env settings."""
    if ALPHAVANTAGE_MCP_TRANSPORT in ("sse", "streamable_http"):
        url = ALPHAVANTAGE_MCP_SSE_URL
        if ALPHAVANTAGE_API_KEY and "apikey=" not in url:
            url = f"{url}?apikey={ALPHAVANTAGE_API_KEY}"
        return {
            "alphavantage": {
                "transport": "streamable_http",
                "url": url,
            }
        }
    return {
        "alphavantage": {
            "transport": "stdio",
            "command": ALPHAVANTAGE_MCP_COMMAND,
            "args": ALPHAVANTAGE_MCP_ARGS.split(),
            "env": {"ALPHAVANTAGE_API_KEY": ALPHAVANTAGE_API_KEY},
        }
    }


async def get_mcp_tools(tool_names: list[str] | None = None) -> tuple[list, dict]:
    """Connect to the Alpha Vantage MCP server and return (tools, tool_map).

    Args:
        tool_names: Optional allowlist of tool names to keep. If None, all tools
                    are returned. Pass a list to reduce the tool definitions sent
                    to the LLM on every call.

    tools    — list of LangChain-compatible tool objects to bind to an LLM
    tool_map — dict[name -> tool] for use inside a tool node
    """
    server_config = build_mcp_server_config()
    mcp_client = MultiServerMCPClient(server_config)
    all_tools = await mcp_client.get_tools()

    if tool_names:
        allowed = {n.upper() for n in tool_names}
        tools = [t for t in all_tools if t.name.upper() in allowed]
    else:
        tools = all_tools

    tool_map = {t.name: t for t in tools}
    print(f"MCP tools available: {len(all_tools)} | using: {len(tools)} {[t.name for t in tools]}")
    return tools, tool_map


def _truncate_timeseries(output, max_data_points: int) -> str:
    """Keep only the latest max_data_points entries from time series responses."""
    if not isinstance(output, dict):
        return str(output)

    truncated = {}
    for key, value in output.items():
        if isinstance(value, dict) and value:
            # Sort by date key descending and keep latest N entries
            sorted_items = sorted(value.items(), reverse=True)[:max_data_points]
            truncated[key] = dict(sorted_items)
        else:
            truncated[key] = value

    return str(truncated)


def build_tool_node(tool_map: dict, max_data_points: int = 3):
    """Return an async LangGraph tool node that logs each MCP call.

    Args:
        tool_map:        dict[name -> tool] returned by get_mcp_tools()
        max_data_points: Number of most recent time series entries to keep per
                         tool response. Reduces tokens significantly for indicator
                         calls that return 100+ historical rows.

    Returns:
        An async function compatible with StateGraph.add_node()
    """
    async def call_tools(state) -> dict:
        last = state["messages"][-1]
        results = []
        for tc in last.tool_calls:
            tool = tool_map.get(tc["name"])
            print(f"\n[MCP TOOL CALL] {tc['name']}")
            print(f"  args : {tc['args']}")
            if tool is None:
                output = f"Tool '{tc['name']}' not found."
                print(f"  error: {output}")
            else:
                try:
                    raw = await tool.ainvoke(tc["args"])
                    output = _truncate_timeseries(raw, max_data_points)
                    print(f"  result: {str(output)[:500]}{'...' if len(str(output)) > 500 else ''}")
                except Exception as e:
                    output = f"Error calling {tc['name']}: {e}"
                    print(f"  error: {output}")
            results.append(ToolMessage(content=str(output), tool_call_id=tc["id"]))
        return {"messages": results}

    return call_tools
