"""Buy Technical Evaluator Agent

Evaluates whether the most recent market data for a ticker satisfies the
entry conditions of a named trade setup stored in SetupStore.

Unlike buy_evaluator_agent_using_mcp.py (which calls the Alpha Vantage MCP
server via Claude), this version:
  - Computes all indicators locally using the `ta` library (fast, no API calls
    beyond the initial cached OHLCV fetch)
  - Evaluates setup conditions directly via condition_registry (no LLM tool loop)
  - Uses Ollama (free/local) only for generating a brief human-readable reason
  - Only processes the most recent data row — not the full history

Usage:
    python buy_tech_evaluator_agent.py AAPL RSI_MACD_TREND
    python buy_tech_evaluator_agent.py NVDA EMA20_PB

Or import and call:
    from agents.buy_tech_evaluator_agent import BuyTechEvaluatorAgent
    agent = BuyTechEvaluatorAgent()
    result = agent.evaluate(ticker="NVDA", setup_name="RSI_MACD_TREND")
    # {"decision": "BUY"|"WAIT", "risk_percent": 2, "conditions": {...}, "reason": "..."}
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.alphavantage.alphavantage_data import get_ohlcv_with_indicators
from tools.trade_setup.condition_registry import build_condition
from tools.trade_setup.setup_store import SetupStore
from tools.trade_setup.setup_schema import setup_from_dict
from config import AGENT_MODEL


# Minimum lookback to ensure all indicators warm up correctly.
# SMA-200 requires the most history; everything else is shorter.
_WARMUP_DAYS = 250


class BuyTechEvaluatorAgent:
    def __init__(self):
        self._store = SetupStore()
        self._llm = None

    def _get_llm(self):
        """Lazy-init Ollama LLM — only used for reason generation."""
        if self._llm is None:
            from langchain_ollama import ChatOllama
            self._llm = ChatOllama(model=AGENT_MODEL, temperature=0)
        return self._llm

    def _generate_reason(
        self,
        ticker: str,
        setup_name: str,
        conditions: dict[str, str],
        decision: str,
    ) -> str:
        """Ask Ollama for a one-sentence reason based on condition results."""
        lines = "\n".join(f"  - {label}: {result}" for label, result in conditions.items())
        prompt = (
            f"Ticker: {ticker.upper()}\n"
            f"Setup: {setup_name}\n"
            f"Decision: {decision}\n"
            f"Conditions:\n{lines}\n\n"
            "In one or two sentences, explain why this decision was reached "
            "based on the conditions above. Be concise and specific."
        )
        try:
            response = self._get_llm().invoke(prompt)
            return response.content.strip()
        except Exception as e:
            return f"Decision based on condition evaluation. (Reason generation failed: {e})"

    def evaluate(self, ticker: str, setup_name: str, generate_reason: bool = True) -> dict:
        """Evaluate the most recent bar for ticker against the named setup.

        Args:
            ticker:     Stock symbol (e.g. "NVDA")
            setup_name: Name of a setup stored in SetupStore (e.g. "RSI_MACD_TREND")

        Returns:
            dict with keys: decision, risk_percent, conditions, reason, evaluated_at
        """
        print(f"\n{'='*60}")
        print(f"Buy Tech Evaluator | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Ticker : {ticker.upper()}")
        print(f"Setup  : {setup_name}")
        print(f"{'='*60}")

        # ── 1. Load setup ─────────────────────────────────────────────────────
        record = self._store.get(setup_name)
        if record is None:
            available = [s["name"] for s in self._store.list()]
            return {
                "decision": "WAIT",
                "risk_percent": 0,
                "error": f"Setup '{setup_name}' not found.",
                "available_setups": available,
            }

        definition = record["definition"]
        definition.setdefault("name", record["name"])
        setup = setup_from_dict(definition)

        # ── 2. Fetch indicators — only enough rows for warmup ─────────────────
        print(f"  [data] Fetching indicators (lookback={_WARMUP_DAYS} days)...")
        df = get_ohlcv_with_indicators(ticker, lookback_days=_WARMUP_DAYS)
        row = df.iloc[-1]
        bar_date = df.index[-1].strftime("%Y-%m-%d")
        print(f"  [data] Evaluating bar: {bar_date}  close=${row['close']:.2f}")

        # ── 3. Evaluate each entry condition on the latest row ────────────────
        conditions: dict[str, str] = {}
        all_met = True

        for label, condition_fn in setup.entry_conditions:
            try:
                met = bool(condition_fn(row))
            except KeyError as e:
                met = False
                label = f"{label} (missing column: {e})"
            status = "MET" if met else "NOT MET"
            conditions[label] = status
            print(f"  [{status}] {label}")
            if not met:
                all_met = False

        decision = "BUY" if all_met else "WAIT"
        risk_percent = round(setup.position_value * 100, 2)

        print(f"\n  Decision: {decision}")

        # ── 4. Generate reason via Ollama ─────────────────────────────────────
        reason = self._generate_reason(ticker, setup_name, conditions, decision) if generate_reason else ""

        return {
            "ticker": ticker.upper(),
            "setup_name": setup_name,
            "decision": decision,
            "risk_percent": risk_percent,
            "conditions": conditions,
            "reason": reason,
            "evaluated_at": bar_date,
        }


    def evaluate_many(self, pairs: list[tuple[str, str]]) -> list[dict]:
        """Evaluate multiple (ticker, setup_name) pairs and return a list of results.

        Reason generation is disabled for batch evaluation to keep it fast.

        Args:
            pairs: List of (ticker, setup_name) tuples,
                   e.g. [("NVDA", "RSI_MACD_TREND"), ("AAPL", "EMA20_PB")]

        Returns:
            List of result dicts, one per pair.
        """
        return [
            self.evaluate(ticker, setup_name, generate_reason=False)
            for ticker, setup_name in pairs
        ]


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    ticker     = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    setup_name = sys.argv[2] if len(sys.argv) > 2 else "RSI_MACD_TREND"

    import json
    agent = BuyTechEvaluatorAgent()
    result = agent.evaluate(ticker=ticker, setup_name=setup_name)
    print("\nResult:")
    print(json.dumps(result, indent=2))
