"""ChatAgent — LangGraph ReAct agent with tool calling.

The agent uses the LLM configured in config.py and has access to
CHAT_AGENT_TOOLS (candlebar data + backtest).

thread_id is passed as the LangGraph config thread so that a checkpointer
can be added later for per-user conversation memory.
"""

from __future__ import annotations

from typing import Annotated, TypedDict

import json

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver

from .chat_agent_tools import CHAT_AGENT_TOOLS
from config import AGENT_MODEL, MODEL_PROVIDER


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
        response = llm.invoke(state["messages"])
        return {"messages": [response]}

    def should_continue(state: AgentState) -> str:
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else END

    graph = StateGraph(AgentState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", tool_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    # End after tools instead of looping back to agent — the raw tool output
    # is returned directly so the second LLM summarisation call is unnecessary.
    graph.add_edge("tools", END)
    return graph.compile(checkpointer=MemorySaver())


# ── Public class ──────────────────────────────────────────────────────────────

class ChatAgent:
    def __init__(self):
        self._graph = _build_graph()

    def invoke(self, thread_id: str, message: str) -> dict | str:
        """Run the agent and return the result.

        If a tool was called, returns the raw tool output as a dict so the
        caller gets clean JSON without LLM prose wrapped around it.
        Falls back to the LLM's text reply when no tool was invoked.
        """
        print(f"[ChatAgent] thread_id={thread_id!r}  message={message!r}")
        result = self._graph.invoke(
            {"messages": [HumanMessage(content=message)]},
            config={"configurable": {"thread_id": thread_id}},
        )

        # Find the last ToolMessage (most recent tool output)
        tool_outputs = [
            m for m in result["messages"] if isinstance(m, ToolMessage)
        ]
        if tool_outputs:
            raw = tool_outputs[-1].content
            # ToolMessage content is a JSON string — parse it to a dict
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return raw

        # No tool was called — return the LLM's plain text reply
        return result["messages"][-1].content


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
