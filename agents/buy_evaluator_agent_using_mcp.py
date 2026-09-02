"""Buy Evaluator Agent

Evaluates whether a ticker meets the conditions defined in a trade setup
and returns a structured BUY / WAIT decision with risk percentage.

Usage:
    python buy_evaluator_agent_using_mcp.py
    python buy_evaluator_agent_using_mcp.py NVDA

Or import and call:
    from agents.buy_evaluator_agent_using_mcp import BuyEvaluatorAgent
    agent = BuyEvaluatorAgent()
    result = agent.evaluate(ticker="NVDA", trade_setup=MY_SETUP)
    # {"decision": "BUY", "risk_percent": 2}

Note : This agent is a little expensive. So I will use the buy_tech_evaluator that uses local LLM and local modules for calculating indicators
"""

import asyncio
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated, TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

from config import ANTHROPIC_API_KEY, AGENT_MODEL, MODEL_PROVIDER
from tools.alphavantage.alphavantage_mcp_tools import get_mcp_tools, build_tool_node

# Only load the technical indicator tools needed for entry condition evaluation.
# Excludes fundamentals, earnings, congress trades, etc. which are not needed
# here and add significant token overhead when bound to the LLM.
_EVALUATOR_TOOLS = [
    "RSI", "MACD", "BBANDS", "SMA", "EMA", "ADX", "STOCH", "QUOTE",
    "av_rsi", "av_macd", "av_bbands", "av_sma", "av_ema", "av_adx", "av_stoch", "av_quote",
]


# ── LLM factory ───────────────────────────────────────────────────────────────

_MCP_PROVIDER = os.getenv("MCP_AGENT_PROVIDER", "anthropic").lower()
_MCP_MODEL    = os.getenv("MCP_AGENT_MODEL", AGENT_MODEL if MODEL_PROVIDER == "anthropic" else "claude-sonnet-4-6") # Works fine -- need to evaluate cost
#_MCP_PROVIDER = os.getenv("MODEL_PROVIDER", "ollama"). -- doesn't work good
#_MCP_MODEL    = os.getenv("MCP_AGENT_MODEL", AGENT_MODEL) -- doesn't work that great

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


# ── State ─────────────────────────────────────────────────────────────────────

class EvaluatorState(TypedDict):
    messages: Annotated[list, add_messages]


# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a disciplined trade evaluator agent. Your job is to evaluate whether a \
specific ticker meets the BUY conditions defined in the provided trade setup.

WORKFLOW — always follow this order:
1. TECHNICALS: Use Alpha Vantage tools to gather every indicator required by the setup
   (e.g. av_rsi, av_macd, av_bbands, av_sma, av_ema, av_adx, av_stoch, av_quote).
2. EVALUATION: Check each entry condition in the setup one by one. State clearly
   whether each condition is MET or NOT MET with the actual observed value.
3. DECISION: Based on the evaluation:
   - If ALL entry conditions are met → BUY
   - Otherwise → WAIT

TRADE SETUP:
{trade_setup}

TICKER: {ticker}

IMPORTANT: You MUST respond with ONLY a JSON object in this exact format — no prose, \
no markdown, no explanation outside the JSON:
{{
  "decision": "<BUY|WAIT>",
  "risk_percent": <number from the setup's position sizing, default 2 if not specified>,
  "conditions": {{
    "<condition description>": "<MET|NOT MET> — <observed value>"
  }},
  "reason": "<one or two sentence summary>"
}}"""


# ── Agent class ───────────────────────────────────────────────────────────────

class BuyEvaluatorAgent:
    def __init__(self):
        self._tools = None
        self._tool_map = None
        self._app = None

    async def _build(self):
        """Lazy async initialisation — connects to MCP server and compiles the graph."""
        if self._app is not None:
            return

        tools, tool_map = await get_mcp_tools(tool_names=_EVALUATOR_TOOLS)
        self._tools = tools
        self._tool_map = tool_map

        llm = _build_llm(tools)
        call_tools = build_tool_node(tool_map, max_data_points=3)

        async def call_model(state: EvaluatorState) -> EvaluatorState:
            response = await llm.ainvoke(state["messages"])
            return {"messages": [response]}

        def should_continue(state: EvaluatorState) -> str:
            last = state["messages"][-1]
            if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
                return "tools"
            return END

        graph = StateGraph(EvaluatorState)
        graph.add_node("agent", call_model)
        graph.add_node("tools", call_tools)
        graph.set_entry_point("agent")
        graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
        graph.add_edge("tools", "agent")
        self._app = graph.compile()

    async def _evaluate_async(self, ticker: str, trade_setup: str) -> dict:
        await self._build()

        system = _SYSTEM_PROMPT.format(ticker=ticker.upper(), trade_setup=trade_setup)

        print(f"\n{'='*70}")
        print(f"Buy Evaluator Agent | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Ticker    : {ticker.upper()}")
        print(f"LLM       : {_MCP_PROVIDER.upper()} / {_MCP_MODEL}")
        print(f"{'='*70}\n")

        result = await self._app.ainvoke({
            "messages": [
                SystemMessage(content=system),
                HumanMessage(content=f"Evaluate {ticker.upper()} against the trade setup and return your JSON decision."),
            ]
        })

        content = result["messages"][-1].content

        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        return {"decision": "WAIT", "risk_percent": 2, "reason": content.strip()}

    def evaluate(self, ticker: str, trade_setup: str) -> dict:
        """Evaluate a ticker against a trade setup and return a BUY/WAIT decision.

        Args:
            ticker:      Stock symbol, e.g. "NVDA"
            trade_setup: Trade setup rules as plain text (same structure as MY_SETUP)

        Returns:
            dict with keys: decision, risk_percent, conditions, reason
        """
        return asyncio.run(self._evaluate_async(ticker, trade_setup))


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import textwrap

    MY_SETUP = textwrap.dedent("""\
        ENTRY CONDITIONS (ALL must be met to BUY):
          1. RSI(14, daily) is below 35 (oversold)
          2. Price is above the 50-day SMA
          3. ADX(14) > 20 (trend has strength)

        POSITION SIZING:
          - Risk 2% of portfolio per trade

        EXIT CONDITIONS (SELL when):
          - RSI(14) crosses above 70 (overbought)
          - Stop loss: -5% from entry price

        HOLD if conditions are mixed or unclear.
    """)

    ticker = sys.argv[1] if len(sys.argv) > 1 else "NVDA"

    agent = BuyEvaluatorAgent()
    decision = agent.evaluate(ticker=ticker, trade_setup=MY_SETUP)
    print("\nDecision:")
    print(json.dumps(decision, indent=2))
