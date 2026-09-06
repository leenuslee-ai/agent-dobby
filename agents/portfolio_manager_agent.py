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
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.research_agent import ResearchAgent, _get_mock_price
from agents.buy_tech_evaluator_agent import BuyTechEvaluatorAgent
from agents.current_holdings_evaluator_agent import CurrentHoldingsEvaluatorAgent
from agents.evaluator_helpers import poll_order_status
from tools.db.trade_data import get_open_holdings, save_trade
from tools.db.portfolio_data import get_account
from tools.db.watchlist_data import list_watchlist
from tools.alpaca.trade_executor_tool import _get_client
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from config import ALPACA_PAPER, MOCK_STOCKS, MOCK_STOCKS_ENABLED, MOCK_SIMULATION_DATE
from tools.mock_data.mock_executor import simulate_fill
from tools.db.pm_agent_runs import save_pm_run

_MIN_CASH_THRESHOLD = 100.0   # dollars
_MOCK_DEFAULT_SETUP = "Daily-RSI-14"


class PortfolioManagerAgent:
    def __init__(self, account_id: str):
        self.account_id = account_id
        self._research  = ResearchAgent()
        self._buy_eval  = BuyTechEvaluatorAgent()

    # ── Account helpers ───────────────────────────────────────────────────────

    def _get_available_cash(self) -> float:
        if MOCK_STOCKS_ENABLED:
            account = get_account(self.account_id)
            return float(account["cash"]) if account else 0.0
        try:
            return float(_get_client().get_account().buying_power)
        except Exception as e:
            print(f"  [cash] Could not fetch account balance: {e}")
            return 0.0

    def _get_current_price(self, ticker: str) -> float | None:
        if MOCK_STOCKS_ENABLED and ticker.upper() in MOCK_STOCKS:
            raw = _get_mock_price(ticker.upper())
            try:
                return float(raw.split("price=$")[1].split(" ")[0])
            except Exception:
                return None
        try:
            return float(_get_client().get_latest_trade(ticker).price)
        except Exception:
            return None

    # ── Research ──────────────────────────────────────────────────────────────

    def _research_ticker(self, ticker: str) -> dict:
        # In mock mode, skip the LLM call and pass straight to technical eval.
        if MOCK_STOCKS_ENABLED and ticker.upper() in MOCK_STOCKS:
            return {"ticker": ticker, "recommendation": "BUY", "reason": "Mock stock — research skipped."}
        try:
            result = self._research.analyze_recommendation(
                f"Should I buy {ticker} right now? Check latest news and price."
            )
            result["ticker"] = ticker
            return result
        except Exception as e:
            return {"ticker": ticker, "recommendation": "WAIT", "reason": str(e)}

    def _run_research(self, tickers: list[str]) -> dict[str, dict]:
        """Run ResearchAgent on all tickers. Parallel for mock, sequential for Ollama."""
        from config import MODEL_PROVIDER
        # Ollama handles one request at a time — run sequentially to avoid deadlock
        max_workers = min(len(tickers), 6) if MODEL_PROVIDER not in ("ollama", "qwen") else 1
        print(f"\n[step 2b] Running ResearchAgent on {len(tickers)} tickers (workers={max_workers})...")
        research_map: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(self._research_ticker, t): t for t in tickers}
            for f in as_completed(futures):
                result = f.result()
                research_map[result["ticker"]] = result
                rec = result.get("recommendation", "WAIT")
                print(f"  [{result['ticker']}] Research → {rec}: {result.get('reason', '')[:80]}")
        return research_map

    # ── Watchlist ─────────────────────────────────────────────────────────────

    def _build_watchlist_pairs(self) -> list[tuple[str, str]]:
        """Return (ticker, setup) pairs from watchlist, plus mock stocks when enabled."""
        pairs: list[tuple[str, str]] = []
        for entry in list_watchlist(active_only=True):
            for setup in entry["setups"]:
                pairs.append((entry["ticker"], setup))

        if MOCK_STOCKS_ENABLED:
            existing = {t for t, _ in pairs}
            for ticker in MOCK_STOCKS:
                if ticker not in existing:
                    pairs.append((ticker, _MOCK_DEFAULT_SETUP))
            print(f"[step 2a] Mock mode: injected {MOCK_STOCKS} with setup '{_MOCK_DEFAULT_SETUP}'")

        sim_label = f" (sim_date={MOCK_SIMULATION_DATE})" if MOCK_SIMULATION_DATE else ""
        print(f"[step 2a] Watchlist (ticker, setup) pairs: {len(pairs)}{sim_label}")
        return pairs

    # ── Order placement ───────────────────────────────────────────────────────

    def _place_buy_order(self, ticker: str, qty: float) -> dict:
        """Submit a BUY order and return a fill dict. Bypasses Alpaca for mock tickers."""
        if MOCK_STOCKS_ENABLED and ticker.upper() in MOCK_STOCKS:
            return simulate_fill(ticker, qty, side="BUY")
        try:
            client = _get_client()
            order  = client.submit_order(MarketOrderRequest(
                symbol=ticker, qty=qty,
                side=OrderSide.BUY, time_in_force=TimeInForce.DAY,
            ))
            print(f"  [buy] Order submitted: id={order.id} status={order.status}")
            return poll_order_status(client, str(order.id), max_attempts=6, pause_secs=2.0)
        except Exception as e:
            print(f"  [buy] Order submission failed for {ticker}: {e}")
            return {"status": "order_failed", "error": str(e)}

    def _persist_buy_trade(self, ticker: str, setup_name: str, fill: dict) -> dict:
        """Save a filled BUY to the database. Returns the saved trade dict."""
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
            return trade
        except Exception as e:
            print(f"  [buy] Trade persistence failed for {ticker}: {e}")
            return {"error": str(e)}

    def _execute_buy(self, ticker: str, setup_name: str, qty: float) -> dict:
        """Place a BUY order, wait for fill, and persist the trade."""
        mode = "MOCK" if (MOCK_STOCKS_ENABLED and ticker.upper() in MOCK_STOCKS) else ("PAPER" if ALPACA_PAPER else "LIVE")
        print(f"  [buy] [{mode}] BUY {qty} x {ticker} (setup={setup_name})")

        fill = self._place_buy_order(ticker, qty)
        if fill.get("status") == "order_failed":
            return {"ticker": ticker, **fill}

        print(f"  [buy] Fill: status={fill['status']} qty={fill['filled_qty']} @ ${fill['filled_avg_price']}")

        if fill["status"] in ("filled", "partially_filled") and fill["filled_qty"] > 0:
            trade = self._persist_buy_trade(ticker, setup_name, fill)
            return {"ticker": ticker, "setup_name": setup_name, "order": fill, "trade": trade}

        return {"ticker": ticker, "order": fill, "status": "not_filled"}

    # ── Buy pipeline (step 2) ─────────────────────────────────────────────────

    def _run_buy_pipeline(self, summary: dict) -> None:
        """Research → technical eval → execute buys. Mutates summary in place."""
        pairs = self._build_watchlist_pairs()
        if not pairs:
            print("[step 2a] No (ticker, setup) pairs found — skipping buy pipeline.")
            return

        # Research pass
        research_map = self._run_research(list({t for t, _ in pairs}))
        summary["research_results"] = list(research_map.values())
        buy_tickers = {t for t, r in research_map.items() if r.get("recommendation") == "BUY"}
        research_filtered = [(t, s) for t, s in pairs if t in buy_tickers]
        print(f"[step 2b] After research filter: {len(research_filtered)} pairs")

        if not research_filtered:
            return

        # Technical evaluation pass
        print(f"\n[step 2c] Running BuyTechEvaluatorAgent on {len(research_filtered)} pairs...")
        tech_results   = self._buy_eval.evaluate_many(research_filtered)
        buy_candidates = [r for r in tech_results if r.get("decision") == "BUY"]
        summary["buy_candidates"] = buy_candidates
        print(f"[step 2c] Technical BUY candidates: {len(buy_candidates)}")

        if not buy_candidates:
            return

        # Execute buys sequentially
        print(f"\n[step 2d] Executing {len(buy_candidates)} buy order(s)...")
        for candidate in buy_candidates:
            available_cash = self._get_available_cash()
            if available_cash < _MIN_CASH_THRESHOLD:
                print(f"  [buy] Insufficient cash (${available_cash:,.2f}) — stopping.")
                break

            ticker     = candidate["ticker"]
            setup_name = candidate["setup_name"]
            last_price = self._get_current_price(ticker)

            if not last_price or last_price <= 0:
                print(f"  [buy] Could not get price for {ticker} — skipping.")
                summary["errors"].append(f"No price for {ticker}")
                continue

            qty = round(available_cash * candidate.get("risk_percent", 2.0) / 100.0 / last_price, 4)
            if qty < 0.001:
                print(f"  [buy] Qty too small for {ticker} ({qty}) — skipping.")
                continue

            summary["buys_executed"].append(self._execute_buy(ticker, setup_name, qty))

    # ── Holdings eval (steps 1 & 3) ───────────────────────────────────────────

    def _start_holdings_eval(self, open_holdings: list, executor: ThreadPoolExecutor) -> Future | None:
        if not open_holdings:
            return None
        agent = CurrentHoldingsEvaluatorAgent(account_id=self.account_id)
        future = executor.submit(agent.run)
        print("[step 1] CurrentHoldingsEvaluatorAgent launched in background.")
        return future

    def _await_holdings_eval(self, future: Future | None, open_holdings: list, summary: dict) -> None:
        if future is None:
            summary["open_holdings"] = open_holdings
            return
        print("\n[step 3] Awaiting CurrentHoldingsEvaluatorAgent...")
        try:
            result = future.result(timeout=300)
            summary["holdings_eval"] = result.get("evaluated", [])
            summary["open_holdings"] = result.get("open_holdings", [])
        except Exception as e:
            print(f"[step 3] Holdings evaluation error: {e}")
            summary["errors"].append(f"Holdings eval: {e}")

    # ── Summary ───────────────────────────────────────────────────────────────

    def _print_summary(self, summary: dict, run_start: datetime) -> None:
        elapsed = (datetime.now(timezone.utc) - run_start).total_seconds()
        summary["elapsed_seconds"] = round(elapsed, 1)

        sells = [h for h in (summary["holdings_eval"] or []) if h.get("decision") == "SELL"]
        print(f"\n{'='*60}")
        print(f"Run Summary | elapsed={elapsed:.1f}s")
        print(f"  Holdings evaluated : {len(summary['holdings_eval'] or [])}")
        print(f"  Sells executed     : {len(sells)}")
        print(f"  Research tickers   : {len(summary['research_results'])}")
        print(f"  Buy candidates     : {len(summary['buy_candidates'])}")
        print(f"  Buys executed      : {len(summary['buys_executed'])}")
        print(f"  Open holdings now  : {len(summary['open_holdings'])}")
        if summary["errors"]:
            print(f"  Errors             : {summary['errors']}")
        print(f"{'='*60}\n")

        sim_date = str(MOCK_SIMULATION_DATE) if MOCK_SIMULATION_DATE else None
        try:
            saved = save_pm_run(summary, sim_date=sim_date)
            summary["run_id"] = saved["id"]
        except Exception as e:
            print(f"[pm_agent_runs] Failed to save run summary: {e}")

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

        executor     = ThreadPoolExecutor(max_workers=2)
        open_holdings = get_open_holdings(self.account_id, opening_transaction_type="BUY")
        print(f"\n[step 1] Open BUY holdings: {len(open_holdings)}")

        holdings_future = self._start_holdings_eval(open_holdings, executor)

        available_cash = self._get_available_cash()
        print(f"\n[step 2] Available cash: ${available_cash:,.2f}")
        if available_cash >= _MIN_CASH_THRESHOLD:
            self._run_buy_pipeline(summary)
        else:
            print("[step 2] Insufficient cash — skipping buy pipeline.")

        self._await_holdings_eval(holdings_future, open_holdings, summary)
        executor.shutdown(wait=False)

        self._print_summary(summary, run_start)
        return summary


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    account_id = sys.argv[1] if len(sys.argv) > 1 else None
    if not account_id:
        print("Usage: python portfolio_manager_agent.py <account_id>")
        sys.exit(1)

    agent = PortfolioManagerAgent(account_id=account_id)
    print(json.dumps(agent.run(), indent=2, default=str))
