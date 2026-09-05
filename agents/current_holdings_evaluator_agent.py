"""Current Holdings Evaluator Agent

For each open BUY holding in a portfolio account, evaluates the exit conditions
of the holding's setup. If exit conditions are met, places a market SELL order,
polls until filled, and persists the close trade.

Holdings are evaluated in parallel (ThreadPoolExecutor). Order placement and
status polling are sequential per holding to keep broker interactions safe.

Usage:
    from agents.current_holdings_evaluator_agent import CurrentHoldingsEvaluatorAgent
    agent = CurrentHoldingsEvaluatorAgent(account_id="<uuid>")
    result = agent.run()
    # {
    #   "evaluated": [...],   # one entry per holding
    #   "open_holdings": [...] # updated holdings after any closes
    # }
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.evaluator_helpers import (
    load_setup, fetch_latest_row, evaluate_conditions, generate_reason,
    poll_order_status, WARMUP_DAYS,
)
from tools.db.trade_data import get_open_holdings, save_trade
from tools.alpaca.trade_executor_tool import _get_client
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from config import AGENT_MODEL, ALPACA_PAPER, MOCK_STOCKS, MOCK_STOCKS_ENABLED, MOCK_SIMULATION_DATE
from tools.mock_data.mock_executor import simulate_fill


class CurrentHoldingsEvaluatorAgent:
    def __init__(self, account_id: str):
        self.account_id = account_id
        self._llm = None

    def _get_llm(self):
        if self._llm is None:
            from langchain_ollama import ChatOllama
            self._llm = ChatOllama(model=AGENT_MODEL, temperature=0)
        return self._llm

    # ── Per-holding evaluation (runs in thread pool) ──────────────────────────

    def _evaluate_holding(self, holding: dict) -> dict:
        """Evaluate exit conditions for one holding. Returns evaluation result dict."""
        ticker = holding["ticker"]
        setup_name = holding["setup_name"]

        print(f"\n[{ticker}] Evaluating exit | setup={setup_name} | pending_qty={holding['pending_qty']}")

        setup, _ = load_setup(setup_name)
        if setup is None:
            print(f"[{ticker}] Setup '{setup_name}' not found — skipping.")
            return {
                "holding_id":  holding["id"],
                "ticker":      ticker,
                "setup_name":  setup_name,
                "decision":    "HOLD",
                "conditions":  {},
                "reason":      f"Setup '{setup_name}' not found in store.",
                "error":       "setup_not_found",
            }

        bar_date, row = fetch_latest_row(ticker)
        print(f"[{ticker}] Bar: {bar_date}  close=${row['close']:.2f}")

        # Exit triggers on ANY condition (OR logic)
        conditions, should_sell = evaluate_conditions(
            setup.exit_conditions, row, require_all=False
        )
        for label, status in conditions.items():
            print(f"[{ticker}]   [{status}] {label}")

        # Also check stop-loss and take-profit against open price
        open_price = holding["open_price"]
        current_price = float(row["close"])
        pnl_pct = (current_price - open_price) / open_price

        stop_hit   = setup.stop_loss_pct   and pnl_pct <= -setup.stop_loss_pct
        target_hit = setup.take_profit_pct and pnl_pct >=  setup.take_profit_pct

        if stop_hit:
            conditions["Stop loss"] = "MET"
            should_sell = True
            print(f"[{ticker}]   [MET] Stop loss ({pnl_pct*100:.2f}% <= -{setup.stop_loss_pct*100:.0f}%)")
        if target_hit:
            conditions["Take profit"] = "MET"
            should_sell = True
            print(f"[{ticker}]   [MET] Take profit ({pnl_pct*100:.2f}% >= +{setup.take_profit_pct*100:.0f}%)")

        decision = "SELL" if should_sell else "HOLD"
        print(f"[{ticker}] Decision: {decision}")

        # Skip LLM reason generation in mock simulation — no Ollama calls needed.
        if MOCK_STOCKS_ENABLED and ticker.upper() in MOCK_STOCKS:
            reason = f"{decision} based on technical conditions."
        else:
            reason = generate_reason(self._get_llm(), ticker, setup_name, conditions, decision)

        return {
            "holding_id":     holding["id"],
            "ticker":         ticker,
            "setup_name":     setup_name,
            "pending_qty":    holding["pending_qty"],
            "open_price":     open_price,
            "current_price":  current_price,
            "pnl_pct":        round(pnl_pct * 100, 2),
            "decision":       decision,
            "conditions":     conditions,
            "reason":         reason,
            "evaluated_at":   bar_date,
        }

    # ── Order execution + persistence (sequential — one holding at a time) ────

    def _execute_sell(self, eval_result: dict) -> dict:
        """Place a market SELL, poll for fill, then persist the close trade."""
        ticker = eval_result["ticker"]
        qty    = eval_result["pending_qty"]
        mode   = "MOCK" if (MOCK_STOCKS_ENABLED and ticker.upper() in MOCK_STOCKS) else ("PAPER" if ALPACA_PAPER else "LIVE")

        print(f"\n[{ticker}] Placing [{mode}] SELL {qty} shares...")

        if MOCK_STOCKS_ENABLED and ticker.upper() in MOCK_STOCKS:
            fill = simulate_fill(ticker, qty, side="SELL")
        else:
            try:
                client = _get_client()
                req = MarketOrderRequest(
                    symbol=ticker,
                    qty=qty,
                    side=OrderSide.SELL,
                    time_in_force=TimeInForce.DAY,
                )
                order = client.submit_order(req)
                print(f"[{ticker}] Order submitted: id={order.id} status={order.status}")
            except Exception as e:
                print(f"[{ticker}] Order submission failed: {e}")
                eval_result["order_error"] = str(e)
                return eval_result
            fill = poll_order_status(client, str(order.id), max_attempts=6, pause_secs=2.0)
        eval_result["order"] = fill
        print(f"[{ticker}] Fill: status={fill['status']} qty={fill['filled_qty']} @ ${fill['filled_avg_price']}")

        # ── Persist close trade ──────────────────────────────────────────────
        if fill["status"] in ("filled", "partially_filled") and fill["filled_qty"] > 0:
            try:
                trade_result = save_trade(
                    account_id=self.account_id,
                    ticker=ticker,
                    side="SELL",
                    open_close="Close",
                    qty=fill["filled_qty"],
                    price=fill["filled_avg_price"],
                    setup_name=eval_result["setup_name"],
                    status=fill["status"],
                    filled_at=datetime.fromisoformat(fill["filled_at"]) if fill.get("filled_at") else None,
                    broker_order_id=fill["order_id"],
                )
                eval_result["trade_saved"] = trade_result
                print(f"[{ticker}] Trade persisted: txn_id={trade_result['transaction_id']}")
            except Exception as e:
                print(f"[{ticker}] Trade persistence failed: {e}")
                eval_result["trade_error"] = str(e)

        return eval_result

    # ── Main entry point ──────────────────────────────────────────────────────

    def run(self) -> dict:
        """Evaluate all open BUY holdings, sell where exit conditions are met.

        Returns:
            {
              "evaluated":      list of per-holding result dicts,
              "open_holdings":  updated open holdings after any closes,
              "run_at":         ISO timestamp
            }
        """
        print(f"\n{'='*60}")
        print(f"CurrentHoldingsEvaluatorAgent | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Account: {self.account_id}")
        print(f"{'='*60}")

        holdings = get_open_holdings(self.account_id, opening_transaction_type="BUY")
        print(f"Open BUY holdings: {len(holdings)}")

        if not holdings:
            return {
                "evaluated":     [],
                "open_holdings": [],
                "run_at":        datetime.utcnow().isoformat(),
            }

        # ── Step 1: Evaluate all holdings in parallel ─────────────────────────
        eval_results: list[dict] = [None] * len(holdings)
        with ThreadPoolExecutor(max_workers=min(len(holdings), 8)) as pool:
            future_to_idx = {
                pool.submit(self._evaluate_holding, h): i
                for i, h in enumerate(holdings)
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    eval_results[idx] = future.result()
                except Exception as e:
                    h = holdings[idx]
                    print(f"[{h['ticker']}] Evaluation error: {e}")
                    eval_results[idx] = {
                        "holding_id": h["id"],
                        "ticker":     h["ticker"],
                        "decision":   "HOLD",
                        "error":      str(e),
                    }

        # ── Step 2: Execute sells sequentially ────────────────────────────────
        final_results: list[dict] = []
        for result in eval_results:
            if result and result.get("decision") == "SELL":
                result = self._execute_sell(result)
            final_results.append(result)

        # ── Step 3: Refresh open holdings after closes ────────────────────────
        updated_holdings = get_open_holdings(self.account_id, opening_transaction_type="BUY")

        return {
            "evaluated":     final_results,
            "open_holdings": updated_holdings,
            "run_at":        datetime.utcnow().isoformat(),
        }


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    account_id = sys.argv[1] if len(sys.argv) > 1 else None
    if not account_id:
        print("Usage: python current_holdings_evaluator_agent.py <account_id>")
        sys.exit(1)

    agent = CurrentHoldingsEvaluatorAgent(account_id=account_id)
    result = agent.run()
    print("\nResult:")
    print(json.dumps(result, indent=2, default=str))
