"""Shared helpers for buy/sell technical evaluator agents."""

from __future__ import annotations

import time
from datetime import datetime, timezone

from tools.alphavantage.alphavantage_data import get_ohlcv_with_indicators
from tools.trade_setup.condition_registry import build_condition
from tools.trade_setup.setup_store import SetupStore
from tools.trade_setup.setup_schema import Setup, setup_from_dict

# SMA-200 needs the most history; keep this high enough for all indicators.
WARMUP_DAYS = 250

_store = SetupStore()


def load_setup(setup_name: str) -> tuple[Setup, dict] | tuple[None, None]:
    """Load a Setup from SetupStore by name. Returns (Setup, raw_record) or (None, None)."""
    record = _store.get(setup_name)
    if record is None:
        return None, None
    definition = record["definition"]
    definition.setdefault("name", record["name"])
    return setup_from_dict(definition), record


def fetch_latest_row(ticker: str):
    """Fetch indicator data and return the most recent bar as a (date_str, pd.Series) tuple."""
    df = get_ohlcv_with_indicators(ticker, lookback_days=WARMUP_DAYS)
    row = df.iloc[-1]
    bar_date = df.index[-1].strftime("%Y-%m-%d")
    return bar_date, row


def evaluate_conditions(
    conditions: list[tuple[str, object]],
    row,
    require_all: bool = True,
) -> tuple[dict[str, str], bool]:
    """Evaluate a list of (label, condition_fn) pairs against a data row.

    Args:
        conditions:  List of (label, fn) from Setup.entry_conditions or exit_conditions
        row:         Latest market data bar (pd.Series)
        require_all: True → all must be met (AND); False → any triggers (OR)

    Returns:
        (results dict {label: "MET"|"NOT MET"}, overall bool)
    """
    results: dict[str, str] = {}
    triggered = False

    for label, condition_fn in conditions:
        try:
            met = bool(condition_fn(row))
        except KeyError as e:
            met = False
            label = f"{label} (missing column: {e})"
        results[label] = "MET" if met else "NOT MET"
        if met:
            triggered = True

    if require_all:
        overall = all(v == "MET" for v in results.values())
    else:
        overall = triggered

    return results, overall


def generate_reason(llm, ticker: str, setup_name: str, conditions: dict[str, str], decision: str) -> str:
    """Ask the LLM for a one-sentence reason based on evaluated conditions."""
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
        return llm.invoke(prompt).content.strip()
    except Exception as e:
        return f"Decision based on condition evaluation. (Reason generation failed: {e})"


def poll_order_status(client, order_id: str, max_attempts: int = 5, pause_secs: float = 1.5) -> dict:
    """Poll Alpaca for order status until filled or attempts exhausted.

    Returns a dict with keys: order_id, status, filled_qty, filled_avg_price, filled_at.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            order = client.get_order_by_id(order_id)
            filled_qty = float(order.filled_qty or 0)
            filled_price = float(order.filled_avg_price or 0)
            status = str(order.status)

            result = {
                "order_id":         order_id,
                "status":           status,
                "filled_qty":       filled_qty,
                "filled_avg_price": filled_price,
                "filled_at":        datetime.now(timezone.utc).isoformat(),
            }

            if status in ("filled", "partially_filled") and filled_qty > 0:
                return result

            if attempt < max_attempts:
                time.sleep(pause_secs)

        except Exception as e:
            if attempt == max_attempts:
                return {"order_id": order_id, "status": "unknown", "error": str(e)}
            time.sleep(pause_secs)

    return result
