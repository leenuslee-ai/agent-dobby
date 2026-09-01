from .backtester import Backtester
from .example_setups import build_example_setup, build_ema_pullback_setup
from tools.alphavantage.alphavantage_data import get_ohlcv_with_indicators

# Re-export tools symbols so existing callers using `from backtest import ...` still work
from tools import Setup, setup_from_dict, SetupStore, CONDITION_REGISTRY

__all__ = [
    "Backtester",
    "build_example_setup",
    "build_ema_pullback_setup",
    "get_ohlcv_with_indicators",
    "Setup",
    "setup_from_dict",
    "SetupStore",
    "CONDITION_REGISTRY",
]
