"""Portfolio Manager Agent

Supervisor agent that manages one portfolio account per instance.
Orchestrates holdings evaluation, research, technical analysis, and trade
execution in a single coordinated run.

Flow per run:
  1. Load open BUY holdings → if any, run CurrentHoldingsEvaluatorAgent (async)
  2. If cash is available:
       a. Get (ticker, setup) pairs from watchlist (skip tickers with no setups)
       b. ResearchAgent.analyze_recommendation → filter to BUY only
       c. BuyTechEvaluatorAgent.evaluate_many → filter to BUY only
       d. Execute buy orders sequentially, respecting remaining cash balance
  3. Await holdings evaluation if still running
  4. Log a run summary

Usage:
    from agents.portfolio_manager_agent import PortfolioManagerAgent
    agent = PortfolioManagerAgent(account_id="<uuid>")
    summary = agent.run()
"""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.research_agent import ResearchAgent, _get_mock_price
from agents.buy_tech_evaluator_agent import BuyTechEvaluatorAgent
from agents.current_holdings_evaluator_agent import CurrentHoldingsEvaluatorAgent
from agents.evaluator_helpers import poll_order_status
from tools.db.trade_data import get_open_holdings, save_trade
from tools.db.watchlist_data import list_watchlist
from tools.alpaca.trade_executor_tool import _get_client
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from config import ALPACA_PAPER, MOCK_STOCKS, MOCK_STOCKS_ENABLED, MOCK_SIMULATION_DATE
from tools.mock_data.mock_executor import simulate_fill


# Minimum free cash fraction required before attempting new buys.
# Avoids tiny fractional orders when the account is nearly fully invested.
_MIN_CASH_THRESHOLD = 100.0   # dollars


class PortfolioManagerAgent:
    def __init__(self, account_id: str):
        self.account_id = account_id
        self._research  = ResearchAgent()
        self._buy_eval  = BuyTechEvaluatorAgent()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_available_cash(self) -> float:
        """Return current buying power — fixed simulation balance in mock mode."""
        if MOCK_STOCKS_ENABLED:
            return 10_000.0   # fixed paper balance for simulation runs
        try:
            acct = _get_client().get_account()
            return float(acct.buying_power)
        except Exception as e:
            print(f"  [cash] Could not fetch account balance: {e}")
            return 0.0

    def _get_current_price(self, ticker: str) -> float | None:
        """Return the current price for a ticker — mock CSV for mock stocks, Alpaca otherwise."""
        if MOCK_STOCKS_ENABLED and ticker.upper() in MOCK_STOCKS:
            # Parse price from the mock price string: "TICKER [MOCK]: price=$123.45 ..."
            raw = _get_mock_price(ticker.upper())
            try:
                return float(raw.split("price=$")[1].split(" ")[0])
            except Exception:
                return None
        try:
            return float(_get_client().get_latest_trade(ticker).price)
        except Exception:
            return None

    def _research_ticker(self, ticker: str) -> dict:
        """Run ResearchAgent.analyze_recommendation for one ticker."""
        try:
            result = self._research.analyze_recommendation(
                f"Should I buy {ticker} right now? Check latest news and price."
            )
            result["ticker"] = ticker
            return result
        except Exception as e:
            return {"ticker": ticker, "recommendation": "WAIT", "reason": str(e)}

    def _execute_buy(self, ticker: str, setup_name: str, qty: float) -> dict:
        """Place a market BUY, poll for fill, persist the open trade."""
        mode = "MOCK" if (MOCK_STOCKS_ENABLED and ticker.upper() in MOCK_STOCKS) else ("PAPER" if ALPACA_PAPER else "LIVE")
        print(f"  [buy] [{mode}] BUY {qty} x {ticker} (setup={setup_name})")

        if MOCK_STOCKS_ENABLED and ticker.upper() in MOCK_STOCKS:
            fill = simulate_fill(ticker, qty, side="BUY")
        else:
            try:
                client = _get_client()
                req = MarketOrderRequest(
                    symbol=ticker,
                    qty=qty,
                    side=OrderSide.BUY,
                    time_in_force=TimeInForce.DAY,
                )
                order = client.submit_order(req)
                print(f"  [buy] Order submitted: id={order.id} status={order.status}")
            except Exception as e:
                print(f"  [buy] Order submission failed for {ticker}: {e}")
                return {"ticker": ticker, "status": "order_failed", "error": str(e)}
            fill = poll_order_status(client, str(order.id), max_attempts=6, pause_secs=2.0)
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
                    broker_order_id=str(order.id),
                )
                print(f"  [buy] Trade persisted: txn_id={trade['transaction_id']}")
                return {"ticker": ticker, "setup_name": setup_name, "order": fill, "trade": trade}
            except Exception as e:
                print(f"  [buy] Trade persistence failed for {ticker}: {e}")
                return {"ticker": ticker, "order": fill, "trade_error": str(e)}

        return {"ticker": ticker, "order": fill, "status": "not_filled"}

    # ── Main run ──────────────────────────────────────────────────────────────

    def run(self) -> dict:
        run_start = datetime.now(timezone.utc)
        print(f"\n{'='*60}")
        print(f"PortfolioManagerAgent | {run_start.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"Account : {self.account_id}")
        print(f"{'='*60}")

        summary: dict = {
            "account_id":       self.account_id,
            "run_at":           run_start.isoformat(),
            "holdings_eval":    None,
            "research_results": [],
            "buy_candidates":   [],
            "buys_executed":    [],
            "open_holdings":    [],
            "errors":           [],
        }

        # ── Step 1: Kick off holdings evaluation async if needed ──────────────
        holdings_future: Future | None = None
        open_holdings = get_open_holdings(self.account_id, opening_transaction_type="BUY")
        print(f"\n[step 1] Open BUY holdings: {len(open_holdings)}")

        executor = ThreadPoolExecutor(max_workers=2)

        if open_holdings:
            holdings_agent = CurrentHoldingsEvaluatorAgent(account_id=self.account_id)
            holdings_future = executor.submit(holdings_agent.run)
            print("[step 1] CurrentHoldingsEvaluatorAgent launched in background.")

        # ── Step 2: Buy pipeline ──────────────────────────────────────────────
        available_cash = self._get_available_cash()
        print(f"\n[step 2] Available cash: ${available_cash:,.2f}")

        if available_cash >= _MIN_CASH_THRESHOLD:

            # 2a. Build (ticker, setup) pairs from watchlist
            watchlist = list_watchlist(active_only=True)
            ticker_setup_pairs: list[tuple[str, str]] = []
            for entry in watchlist:
                for setup in entry["setups"]:
                    ticker_setup_pairs.append((entry["ticker"], setup))

            # When running in mock mode, add mock stocks with their default setup
            if MOCK_STOCKS_ENABLED:
                existing_tickers = {t for t, _ in ticker_setup_pairs}
                default_setup = "Daily-RSI-14"
                for mock_ticker in MOCK_STOCKS:
                    if mock_ticker not in existing_tickers:
                        ticker_setup_pairs.append((mock_ticker, default_setup))
                print(f"[step 2a] Mock mode: added {MOCK_STOCKS} with setup '{default_setup}'")

            sim_label = f" (sim_date={MOCK_SIMULATION_DATE})" if MOCK_SIMULATION_DATE else ""
            print(f"[step 2a] Watchlist (ticker, setup) pairs: {len(ticker_setup_pairs)}{sim_label}")
            if not ticker_setup_pairs:
                print("[step 2a] No (ticker, setup) pairs found — skipping buy pipeline.")
            else:
                # 2b. Research all tickers in parallel, keep BUY recommendations
                unique_tickers = list({t for t, _ in ticker_setup_pairs})
                print(f"\n[step 2b] Running ResearchAgent on {len(unique_tickers)} tickers...")

                research_map: dict[str, dict] = {}
                with ThreadPoolExecutor(max_workers=min(len(unique_tickers), 6)) as pool:
                    futures = {pool.submit(self._research_ticker, t): t for t in unique_tickers}
                    for f in as_completed(futures):
                        result = f.result()
                        research_map[result["ticker"]] = result
                        rec = result.get("recommendation", "WAIT")
                        print(f"  [{result['ticker']}] Research → {rec}: {result.get('reason', '')[:80]}")

                summary["research_results"] = list(research_map.values())

                buy_research = {t for t, r in research_map.items() if r.get("recommendation") == "BUY"}
                research_filtered = [(t, s) for t, s in ticker_setup_pairs if t in buy_research]
                print(f"[step 2b] After research filter: {len(research_filtered)} pairs")

                # 2c. Technical evaluation
                buy_candidates: list[dict] = []
                if research_filtered:
                    print(f"\n[step 2c] Running BuyTechEvaluatorAgent on {len(research_filtered)} pairs...")
                    tech_results = self._buy_eval.evaluate_many(research_filtered)
                    buy_candidates = [r for r in tech_results if r.get("decision") == "BUY"]
                    summary["buy_candidates"] = buy_candidates
                    print(f"[step 2c] Technical BUY candidates: {len(buy_candidates)}")

                # 2d. Execute buys sequentially
                if buy_candidates:
                    print(f"\n[step 2d] Executing {len(buy_candidates)} buy order(s)...")
                    for candidate in buy_candidates:
                        available_cash = self._get_available_cash()
                        if available_cash < _MIN_CASH_THRESHOLD:
                            print(f"  [buy] Insufficient cash (${available_cash:,.2f}) — stopping.")
                            break

                        ticker     = candidate["ticker"]
                        setup_name = candidate["setup_name"]
                        risk_pct   = candidate.get("risk_percent", 2.0) / 100.0
                        trade_value = available_cash * risk_pct

                        # Get current price to calculate qty
                        last_price = self._get_current_price(ticker)

                        if not last_price or last_price <= 0:
                            print(f"  [buy] Could not get price for {ticker} — skipping.")
                            summary["errors"].append(f"No price for {ticker}")
                            continue

                        qty = round(trade_value / last_price, 4)
                        if qty < 0.001:
                            print(f"  [buy] Qty too small for {ticker} ({qty}) — skipping.")
                            continue

                        result = self._execute_buy(ticker, setup_name, qty)
                        summary["buys_executed"].append(result)
        else:
            print("[step 2] Insufficient cash — skipping buy pipeline.")

        # ── Step 3: Await holdings evaluation ────────────────────────────────
        if holdings_future is not None:
            print("\n[step 3] Awaiting CurrentHoldingsEvaluatorAgent...")
            try:
                holdings_result = holdings_future.result(timeout=300)
                summary["holdings_eval"]  = holdings_result.get("evaluated", [])
                summary["open_holdings"]  = holdings_result.get("open_holdings", [])
            except Exception as e:
                print(f"[step 3] Holdings evaluation error: {e}")
                summary["errors"].append(f"Holdings eval: {e}")
        else:
            summary["open_holdings"] = open_holdings

        executor.shutdown(wait=False)

        # ── Step 4: Summary ───────────────────────────────────────────────────
        run_end = datetime.now(timezone.utc)
        elapsed = (run_end - run_start).total_seconds()

        sells_executed = [
            h for h in (summary["holdings_eval"] or [])
            if h.get("decision") == "SELL"
        ]

        print(f"\n{'='*60}")
        print(f"Run Summary | elapsed={elapsed:.1f}s")
        print(f"  Holdings evaluated : {len(summary['holdings_eval'] or [])}")
        print(f"  Sells executed     : {len(sells_executed)}")
        print(f"  Research tickers   : {len(summary['research_results'])}")
        print(f"  Buy candidates     : {len(summary['buy_candidates'])}")
        print(f"  Buys executed      : {len(summary['buys_executed'])}")
        print(f"  Open holdings now  : {len(summary['open_holdings'])}")
        if summary["errors"]:
            print(f"  Errors             : {summary['errors']}")
        print(f"{'='*60}\n")

        summary["elapsed_seconds"] = round(elapsed, 1)
        return summary


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    account_id = sys.argv[1] if len(sys.argv) > 1 else None
    if not account_id:
        print("Usage: python portfolio_manager_agent.py <account_id>")
        sys.exit(1)

    agent = PortfolioManagerAgent(account_id=account_id)
    result = agent.run()
    print(json.dumps(result, indent=2, default=str))
