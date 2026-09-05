"""ChatAgent — LangGraph ReAct agent with tool calling.

The agent uses the LLM configured in config.py and has access to
CHAT_AGENT_TOOLS (candlebar data + backtest).

thread_id is passed as the LangGraph config thread so that a checkpointer
can be added later for per-user conversation memory.
"""

from __future__ import annotations

from typing import Annotated, TypedDict

import json

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver

from .chat_agent_tools import CHAT_AGENT_TOOLS
from config import AGENT_MODEL, MODEL_PROVIDER, CHAT_AGENT_TRACE


_SYSTEM_PROMPT = """\
You are a trading assistant. Always call a tool to answer questions about \
portfolios, holdings, trades, PM runs, market data, backtests, setups, or the watchlist. \
Pick the single most relevant tool and call it immediately — do not explain or ask for \
clarification first.

Tool selection guide:
- "how is it going", "what's happening", "status", "update" for an account → get_open_portfolio_holdings
- "holdings", "positions", "what does the agent hold" → get_open_portfolio_holdings
- "all holdings" or "including closed" → get_portfolio_holdings
- "trades", "transactions", "what did it buy/sell" → get_portfolio_trades
- "pm runs", "agent runs", "what did the agent do", "daily run" → list_pm_run_results
- "accounts", "what accounts" → list_portfolio_accounts
- "watchlist" → list_watchlist
- "recommend", "should I buy" → get_recommendation
- "backtest runs", "list backtests", "backtest history" → list_backtest_runs
- "show backtest result", "get backtest id", "backtest run id" → get_backtest_result
- "run a backtest", "backtest [ticker]" → run_backtest
- "candlebar", "price history", "ohlcv" → get_candlebar_data

Rules:
- Call exactly one tool per request unless the user explicitly asks for multiple things.
- After a tool returns its result, stop and do not call additional tools.
- For greetings, farewells, or casual conversation only, respond without calling a tool.
- When the user says "run it on X" or "try X instead", infer the setup and day count \
from the previous request and run the same backtest for ticker X."""


# ── LLM factory ──────────────────────────────────────────────────────────────

def _build_llm():
    if MODEL_PROVIDER in ("ollama", "qwen"):
        from langchain_ollama import ChatOllama
        return ChatOllama(model=AGENT_MODEL)
    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(model=AGENT_MODEL)


# ── Graph state ───────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


# ── Graph builder ─────────────────────────────────────────────────────────────

def _build_graph():
    llm = _build_llm().bind_tools(CHAT_AGENT_TOOLS)
    tool_node = ToolNode(CHAT_AGENT_TOOLS)

    def call_model(state: AgentState) -> AgentState:
        messages = state["messages"]
        # Prepend system prompt if not already present
        if not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=_SYSTEM_PROMPT)] + messages
        response = llm.invoke(messages)
        return {"messages": [response]}

    def should_continue(state: AgentState) -> str:
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else END

    def after_tools(state: AgentState) -> str:
        """Return END if ALL tool results in this batch are already_formatted.

        When the LLM makes parallel tool calls, ToolNode produces one ToolMessage
        per call. We only short-circuit to END if every result in the batch is
        already_formatted — otherwise route back to the agent so it can synthesise
        the mixed results properly.
        """
        messages = state["messages"]

        # Find the last AIMessage to know how many tool calls were made
        n_tool_calls = 0
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                n_tool_calls = len(getattr(msg, "tool_calls", []))
                break

        # Collect the last n_tool_calls ToolMessages (this batch)
        tool_msgs = [m for m in messages if isinstance(m, ToolMessage)]
        batch = tool_msgs[-n_tool_calls:] if n_tool_calls else tool_msgs[-1:]

        all_formatted = True
        for tm in batch:
            try:
                data = json.loads(tm.content)
                if not data.get("already_formatted"):
                    all_formatted = False
                    break
            except (json.JSONDecodeError, TypeError):
                all_formatted = False
                break

        return END if all_formatted else "agent"

    graph = StateGraph(AgentState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", tool_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_conditional_edges("tools", after_tools, {"agent": "agent", END: END})
    return graph.compile(checkpointer=MemorySaver())


# ── Public class ──────────────────────────────────────────────────────────────

class ChatAgent:
    def __init__(self):
        self._graph = _build_graph()

    def invoke(self, thread_id: str, message: str) -> dict | str:
        """Run the agent and return the result.

        Returns the LLM's final response. When CHAT_AGENT_TRACE is enabled,
        the result dict will include a "trace" key with each step the agent took.
        """
        print(f"[ChatAgent] thread_id={thread_id!r}  message={message!r}")
        config = {"configurable": {"thread_id": thread_id}}

        # Snapshot message count before invoking so we can slice only new messages
        prior_state = self._graph.get_state(config)
        prior_count = len(prior_state.values.get("messages", [])) if prior_state.values else 0

        result = self._graph.invoke(
            {"messages": [HumanMessage(content=message)]},
            config=config,
        )

        # Find the best response message. Prefer an already_formatted ToolMessage
        # that is NOT a simple list (e.g. prefer BackTestResults over TradeSetupList)
        # so parallel tool calls don't clobber the primary result.
        new_messages = result["messages"][prior_count:]
        last = result["messages"][-1]

        _priority = {
            "BackTestResults": 10, "Recommendation": 9, "CandlebarData": 8,
            "TradeSetup": 7, "WatchlistEntry": 6, "PortfolioAccount": 5,
            "PMAgentRun": 4, "PMAgentRunList": 4,
            "HoldingList": 3, "OpenHoldingList": 3, "TradeList": 3,
        }
        best_tool_msg = None
        best_score = -1
        for msg in new_messages:
            if not isinstance(msg, ToolMessage):
                continue
            try:
                data = json.loads(msg.content)
                if data.get("already_formatted"):
                    score = _priority.get(data.get("responseType", ""), 0)
                    if score > best_score:
                        best_score = score
                        best_tool_msg = msg
            except (json.JSONDecodeError, TypeError):
                pass

        source = best_tool_msg if best_tool_msg else last
        try:
            response = json.loads(source.content)
        except (json.JSONDecodeError, TypeError):
            response = {"message": source.content}
        response.pop("already_formatted", None)

        if CHAT_AGENT_TRACE:
            response["trace"] = _build_trace(new_messages)

        # Trim large array fields from ToolMessages stored in MemorySaver so
        # they don't bloat the context window and confuse follow-up requests.
        _trim_tool_messages(self._graph, config)

        return response


# Keys that carry large arrays and should be stripped from conversation history.
# The full data is returned to the API caller; only a compact summary is kept
# in MemorySaver so follow-up messages have clean, understandable context.
_LARGE_KEYS = ("candle_data", "bars", "trades", "entries", "runs", "accounts", "holdings")


def _trim_tool_messages(graph, config: dict) -> None:
    """Replace large array fields in the most recent ToolMessages with counts.

    This keeps the MemorySaver context window lean so the LLM can correctly
    resolve follow-up references like "try it with MSFT instead".
    """
    try:
        state = graph.get_state(config)
        messages = state.values.get("messages", [])

        updated: list[BaseMessage] = []
        changed = False
        for msg in messages:
            if not isinstance(msg, ToolMessage):
                updated.append(msg)
                continue
            try:
                data = json.loads(msg.content)
                trimmed = False
                for key in _LARGE_KEYS:
                    if key in data and isinstance(data[key], list) and len(data[key]) > 5:
                        data[f"{key}_count"] = len(data[key])
                        data[key] = f"[{len(data[key])} items — omitted from context]"
                        trimmed = True
                if trimmed:
                    msg = ToolMessage(
                        content=json.dumps(data),
                        tool_call_id=msg.tool_call_id,
                        name=msg.name,
                    )
                    changed = True
            except (json.JSONDecodeError, TypeError):
                pass
            updated.append(msg)

        if changed:
            graph.update_state(config, {"messages": updated})
    except Exception:
        pass  # trimming is best-effort — never break the main flow


def _build_trace(messages: list[BaseMessage]) -> list[dict]:
    """Extract a human-readable step-by-step trace from the message list."""
    trace = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            continue
        if isinstance(msg, HumanMessage):
            trace.append({"step": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    trace.append({
                        "step": "tool_call",
                        "tool": tc["name"],
                        "args": tc["args"],
                    })
            elif msg.content:
                trace.append({"step": "assistant", "content": msg.content})
        elif isinstance(msg, ToolMessage):
            try:
                content = json.loads(msg.content)
            except (json.JSONDecodeError, TypeError):
                content = msg.content
            trace.append({
                "step": "tool_result",
                "tool": msg.name,
                "content": content,
            })
    return trace


# ── Quick test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    agent = ChatAgent()

    print("\n" + "="*60)
    print("TEST 1: get_candlebar_data")
    print("="*60)
    response1 = agent.invoke(
        thread_id="test-thread-1",
        message="Get me 5 days of daily candlebar data for NVDA.",
    )
    print(json.dumps(response1, indent=2))

    print("\n" + "="*60)
    print("TEST 2: run_backtest")
    print("="*60)
    response2 = agent.invoke(
        thread_id="test-thread-2",
        message=(
            "Run a backtest for AAPL over the last 30 days "
            "using the 'RSI14_Below30' setup and show me the results."
        ),
    )
    print(json.dumps(response2, indent=2))
