"""Registry of named, parameterised conditions for trading setups.

Each entry maps a condition type name to a factory that accepts a params dict
and returns a callable (pd.Series -> bool) suitable for use in Setup.

To add a new condition: add one entry to REGISTRY. No code deploy needed for
simple comparisons — use type "formula" with an expression string instead.

Formula examples
----------------
{"type": "formula", "params": {"expr": "rsi < 40"}}
{"type": "formula", "params": {"expr": "close > ema_20 and adx > 25"}}
{"type": "formula", "params": {"expr": "bb_pct < 0.1 and rsi < 35"}}

Available column names in expressions: any column produced by backtest_data.py
  close, open, high, low, volume,
  rsi, macd, macd_signal, macd_hist, macd_crossover_up, macd_crossover_down,
  sma_20, sma_50, sma_200, ema_12, ema_20, ema_26, adx,
  bb_upper, bb_lower, bb_middle, bb_pct, atr, obv,
  stoch_k, stoch_d, price_above_sma50, price_above_sma200,
  golden_cross, death_cross, ema20_rising, touched_ema20,
  closed_above_ema20, hammer, bullish_engulfing
"""

from __future__ import annotations

import ast
from typing import Callable

import pandas as pd

ConditionFn = Callable[[pd.Series], bool]
ConditionFactory = Callable[[dict], ConditionFn]


# ── Safe formula evaluator ────────────────────────────────────────────────────

_SAFE_NODES = (
    ast.Expression,
    ast.BoolOp, ast.And, ast.Or,
    ast.UnaryOp, ast.Not,
    ast.Compare,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div,
    ast.Name, ast.Constant, ast.Load,
)

def _validate(node: ast.AST):
    """Reject any AST node that isn't a safe arithmetic/comparison/boolean op."""
    if not isinstance(node, _SAFE_NODES):
        raise ValueError(
            f"Disallowed expression element: '{type(node).__name__}'. "
            "Only comparisons, boolean operators, and arithmetic are allowed."
        )
    for child in ast.iter_child_nodes(node):
        _validate(child)


def eval_formula(expr: str, row: pd.Series) -> bool:
    """Safely evaluate a comparison expression against a market data row.

    The expression may reference any column by name.
    No function calls, imports, or assignments are permitted.

    Args:
        expr: e.g. "rsi < 35 and close > ema_20"
        row:  one bar of market data as a pandas Series

    Returns:
        True / False
    """
    tree = ast.parse(expr.strip(), mode="eval")
    _validate(tree.body)
    return bool(eval(  # noqa: S307
        compile(tree, filename="<formula>", mode="eval"),
        {"__builtins__": {}},
        row.to_dict(),
    ))


# ── Condition registry ────────────────────────────────────────────────────────

REGISTRY: dict[str, ConditionFactory] = {

    # ── Formula (no-deploy escape hatch) ─────────────────────────────────────
    # params: {"expr": "rsi < 40 and close > ema_20"}
    "formula":              lambda p: (lambda r: eval_formula(p["expr"], r)),

    # ── RSI ──────────────────────────────────────────────────────────────────
    "rsi_below":            lambda p: (lambda r: r["rsi"] < p["value"]),
    "rsi_above":            lambda p: (lambda r: r["rsi"] > p["value"]),

    # ── MACD ─────────────────────────────────────────────────────────────────
    "macd_crossover_up":    lambda p: (lambda r: bool(r["macd_crossover_up"])),
    "macd_crossover_down":  lambda p: (lambda r: bool(r["macd_crossover_down"])),
    "macd_hist_positive":   lambda p: (lambda r: r["macd_hist"] > 0),
    "macd_hist_negative":   lambda p: (lambda r: r["macd_hist"] < 0),

    # ── Moving averages ───────────────────────────────────────────────────────
    # params: {"period": 50}  — works for any sma period available in data
    "price_above_sma":      lambda p: (lambda r: r["close"] > r[f"sma_{p['period']}"]),
    "price_below_sma":      lambda p: (lambda r: r["close"] < r[f"sma_{p['period']}"]),
    # params: {"period": 20}  — works for any ema period available in data
    "price_above_ema":      lambda p: (lambda r: r["close"] > r[f"ema_{p['period']}"]),
    "price_below_ema":      lambda p: (lambda r: r["close"] < r[f"ema_{p['period']}"]),
    "golden_cross":         lambda p: (lambda r: bool(r["golden_cross"])),
    "death_cross":          lambda p: (lambda r: bool(r["death_cross"])),

    # ── EMA-20 pullback signals ───────────────────────────────────────────────
    "ema20_rising":         lambda p: (lambda r: bool(r["ema20_rising"])),
    "touched_ema20":        lambda p: (lambda r: bool(r["touched_ema20"])),
    "closed_above_ema20":   lambda p: (lambda r: bool(r["closed_above_ema20"])),

    # ── Candlestick patterns ─────────────────────────────────────────────────
    "hammer":               lambda p: (lambda r: bool(r["hammer"])),
    "bullish_engulfing":    lambda p: (lambda r: bool(r["bullish_engulfing"])),
    "hammer_or_engulf":     lambda p: (lambda r: bool(r["hammer"]) or bool(r["bullish_engulfing"])),

    # ── ADX (trend strength) ─────────────────────────────────────────────────
    "adx_above":            lambda p: (lambda r: r["adx"] > p["value"]),
    "adx_below":            lambda p: (lambda r: r["adx"] < p["value"]),

    # ── Bollinger Bands ──────────────────────────────────────────────────────
    "bb_pct_below":         lambda p: (lambda r: r["bb_pct"] < p["value"]),
    "bb_pct_above":         lambda p: (lambda r: r["bb_pct"] > p["value"]),
    "price_below_bb_lower": lambda p: (lambda r: r["close"] < r["bb_lower"]),
    "price_above_bb_upper": lambda p: (lambda r: r["close"] > r["bb_upper"]),

    # ── Stochastic ───────────────────────────────────────────────────────────
    "stoch_k_below":        lambda p: (lambda r: r["stoch_k"] < p["value"]),
    "stoch_k_above":        lambda p: (lambda r: r["stoch_k"] > p["value"]),
    # params: {"value": 20}
    "stoch_oversold":       lambda p: (lambda r: r["stoch_k"] < p.get("value", 20) and r["stoch_d"] < p.get("value", 20)),
    "stoch_overbought":     lambda p: (lambda r: r["stoch_k"] > p.get("value", 80) and r["stoch_d"] > p.get("value", 80)),
}


def build_condition(type_: str, params: dict) -> ConditionFn:
    """Resolve a condition type name + params dict to a callable."""
    if type_ not in REGISTRY:
        raise ValueError(
            f"Unknown condition type: '{type_}'. "
            f"Available: {sorted(REGISTRY.keys())}"
        )
    return REGISTRY[type_](params)
