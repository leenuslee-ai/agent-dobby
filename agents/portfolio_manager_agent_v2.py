"""PortfolioManagerAgent v2 — skips ResearchAgent, goes straight to technical eval.

Used to verify the Alpaca buy order pipeline without Ollama involvement.

Flow:
  1. Get watchlist (ticker, setup) pairs
  2. BuyTechEvaluatorAgent.evaluate_many → filter to BUY
  3. Execute buy orders via Alpaca

Usage:
    python3 -m agents.portfolio_manager_agent_v2 <account_id>
"""

from __future__ import annotations

import sys
import json
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.buy_tech_evaluator_agent import BuyTechEvaluatorAgent
from agents.evaluator_helpers import poll_order_status
from tools.db.trade_data import save_trade
from tools.db.watchlist_data import list_watchlist
from tools.alpaca.trade_executor_tool import _get_client
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestTradeRequest
from config import ALPACA_API_KEY, ALPACA_SECRET_KEY

_MIN_CASH_THRESHOLD = 100.0


class PortfolioManagerAgentV2:
    def __init__(self, account_id: str):
        self.account_id = account_id
        self._buy_eval  = BuyTechEvaluatorAgent()

    def _get_available_cash(self) -> float:
        try:
            return float(_get_client().get_account().buying_power)
        except Exception as e:
            print(f"  [cash] Could not fetch balance: {e}")
            return 0.0

    def _get_current_price(self, ticker: str) -> float | None:
        try:
            data_client = StockHistoricalDataClient(
                api_key=ALPACA_API_KEY, secret_key=ALPACA_SECRET_KEY
            )
            trade = data_client.get_stock_latest_trade(StockLatestTradeRequest(symbol_or_symbols=ticker))
            return float(trade[ticker].price)
        except Exception as e:
            print(f"  [price] Could not fetch price for {ticker}: {e}")
            return None

    def _place_buy_order(self, ticker: str, qty: float) -> dict:
        try:
            client = _get_client()
            order  = client.submit_order(MarketOrderRequest(
                symbol=ticker, qty=qty,
                side=OrderSide.BUY, time_in_force=TimeInForce.DAY,
            ))
            print(f"  [buy] Order submitted: id={order.id} status={order.status}")
            return poll_order_status(client, str(order.id), max_attempts=6, pause_secs=2.0)
        except Exception as e:
            print(f"  [buy] Order failed for {ticker}: {e}")
            return {"status": "order_failed", "error": str(e)}

    def run(self) -> dict:
        run_start = datetime.now(timezone.utc)
        print(f"\n{'='*60}")
        print(f"PortfolioManagerAgentV2 | {run_start.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"Account : {self.account_id}")
        print(f"{'='*60}")

        # Build (ticker, setup) pairs from watchlist
        pairs = [
            (entry["ticker"], setup)
            for entry in list_watchlist(active_only=True)
            for setup in entry["setups"]
        ]
        print(f"\n[step 1] Watchlist pairs: {pairs}")

        if not pairs:
            print("[step 1] No pairs — nothing to do.")
            return {"buys_executed": [], "errors": ["No watchlist pairs"]}

        # Technical evaluation — no LLM, no research
        print(f"\n[step 2] Running BuyTechEvaluatorAgent on {len(pairs)} pairs...")
        tech_results   = self._buy_eval.evaluate_many(pairs)
        buy_candidates = [r for r in tech_results if r.get("decision") == "BUY"]
        print(f"[step 2] BUY candidates: {[r['ticker'] for r in buy_candidates]}")

        if not buy_candidates:
            print("[step 2] No BUY candidates — done.")
            return {"buys_executed": [], "buy_candidates": [], "errors": []}

        # Execute buys
        print(f"\n[step 3] Executing {len(buy_candidates)} buy order(s)...")
        buys_executed = []
        errors        = []
        for candidate in buy_candidates:
            available_cash = self._get_available_cash()
            if available_cash < _MIN_CASH_THRESHOLD:
                print(f"  [buy] Insufficient cash (${available_cash:,.2f}) — stopping.")
                break

            ticker     = candidate["ticker"]
            setup_name = candidate["setup_name"]
            price      = self._get_current_price(ticker)
            if not price:
                errors.append(f"No price for {ticker}")
                continue

            qty  = round(available_cash * candidate.get("risk_percent", 2.0) / 100.0 / price, 4)
            mode = "LIVE" if not True else "PAPER"
            print(f"  [buy] [{mode}] BUY {qty} x {ticker} @ ~${price:.2f} (setup={setup_name})")

            fill = self._place_buy_order(ticker, qty)
            if fill.get("status") == "order_failed":
                errors.append(f"{ticker}: {fill.get('error')}")
                continue

            print(f"  [buy] Fill: status={fill['status']} qty={fill['filled_qty']} @ ${fill['filled_avg_price']}")

            if fill["status"] in ("filled", "partially_filled") and fill["filled_qty"] > 0:
                try:
                    trade = save_trade(
                        account_id=self.account_id,
                        ticker=ticker,
                        side="BUY",
                        open_close="Open",
                        qty=fill["filled_qty"],
                        price=fill["filled_avg_price"],
                        setup_name=setup_name,
                        status=fill["status"],
                        filled_at=datetime.fromisoformat(fill["filled_at"]) if fill.get("filled_at") else None,
                        broker_order_id=fill["order_id"],
                    )
                    print(f"  [buy] Trade persisted: txn_id={trade['transaction_id']}")
                    buys_executed.append({"ticker": ticker, "order": fill, "trade": trade})
                except Exception as e:
                    errors.append(f"{ticker} persist failed: {e}")

        elapsed = round((datetime.now(timezone.utc) - run_start).total_seconds(), 1)
        print(f"\n{'='*60}")
        print(f"V2 Run Summary | elapsed={elapsed}s")
        print(f"  Buys executed : {len(buys_executed)}")
        if errors:
            print(f"  Errors        : {errors}")
        print(f"{'='*60}\n")

        return {"buys_executed": buys_executed, "errors": errors, "elapsed_seconds": elapsed}


if __name__ == "__main__":
    account_id = sys.argv[1] if len(sys.argv) > 1 else None
    if not account_id:
        print("Usage: python3 -m agents.portfolio_manager_agent_v2 <account_id>")
        sys.exit(1)

    agent = PortfolioManagerAgentV2(account_id=account_id)
    print(json.dumps(agent.run(), indent=2, default=str))
