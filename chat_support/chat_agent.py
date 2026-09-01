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
You are a trading assistant with access to tools for market data, backtesting, \
recommendations, portfolio management, trade setups, and a watchlist.

Use tools only when the user is clearly asking for data or an action. \
For greetings, farewells, acknowledgements, or casual conversation, \
respond conversationally without calling any tool."""


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
        """Return END directly if the tool marked its output as already formatted."""
        last = state["messages"][-1]
        if isinstance(last, ToolMessage):
            try:
                data = json.loads(last.content)
                if data.get("already_formatted"):
                    return END
            except (json.JSONDecodeError, TypeError):
                pass
        return "agent"

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

        last = result["messages"][-1]
        try:
            response = json.loads(last.content)
        except (json.JSONDecodeError, TypeError):
            response = {"message": last.content}
        response.pop("already_formatted", None)

        if CHAT_AGENT_TRACE:
            new_messages = result["messages"][prior_count:]
            response["trace"] = _build_trace(new_messages)

        return response


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
