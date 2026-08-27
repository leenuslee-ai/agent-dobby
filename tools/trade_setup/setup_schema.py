"""Setup dataclass and dynamic factory shared across modules.

Importing from here (rather than backtest.backtester) avoids circular deps
when other packages (chat_support, future modules) need Setup without
pulling in the full backtester.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import pandas as pd


@dataclass
class Setup:
    """Defines the rules for one trading setup.

    Each condition is a function that takes a DataFrame row (pd.Series)
    and returns True/False. ALL entry conditions must be True to enter.
    ANY exit condition triggers an exit.
    """
    name: str

    entry_conditions: list[tuple[str, Callable[[pd.Series], bool]]] = field(default_factory=list)
    exit_conditions:  list[tuple[str, Callable[[pd.Series], bool]]] = field(default_factory=list)

    stop_loss_pct:    float       = 0.05
    take_profit_pct:  float | None = None

    position_type:  str   = "equity_pct"   # "shares" | "dollars" | "equity_pct"
    position_value: float = 0.10


def setup_from_dict(data: dict) -> Setup:
    """Build a Setup object from a plain dict (e.g. loaded from the DB).

    Each condition entry must have:
        "label"  — human-readable name shown in trade logs
        "type"   — key into condition_registry.REGISTRY  (or "formula")
        "params" — dict of parameters the condition needs (may be empty)
    """
    from .condition_registry import build_condition

    def build(cond_list: list[dict]) -> list[tuple[str, Callable]]:
        return [
            (c["label"], build_condition(c["type"], c.get("params", {})))
            for c in cond_list
        ]

    return Setup(
        name=data["name"],
        entry_conditions=build(data["entry_conditions"]),
        exit_conditions=build(data["exit_conditions"]),
        stop_loss_pct=data["stop_loss_pct"],
        take_profit_pct=data.get("take_profit_pct"),
        position_type=data.get("position_type", "equity_pct"),
        position_value=data.get("position_value", 0.10),
    )
