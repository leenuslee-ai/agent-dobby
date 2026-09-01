"""LangChain tools for trade setup management."""

import json
import re

from langchain_core.tools import tool

from backtest import SetupStore
from tools.trade_setup.condition_registry import REGISTRY

_store = SetupStore()

_SETUP_PARSE_PROMPT = """\
You are a trading setup parser. Convert the human-readable setup text below into a
structured JSON definition that matches the available condition registry.

AVAILABLE CONDITION TYPES (use ONLY these):
{registry_types}

CONDITION TYPE DETAILS:
- rsi_below / rsi_above:             params: {{"value": <number>}}  ← uses RSI(14)
- rsi_2_below / rsi_2_above:        params: {{"value": <number>}}  ← uses RSI(2) ultra-fast
- macd_crossover_up/down:            params: {{}}
- macd_hist_positive/negative:       params: {{}}
- price_above_sma / price_below_sma: params: {{"period": <number>}}
- price_above_ema / price_below_ema: params: {{"period": <number>}}  ← use for "price above/below EMA-N on close"
- golden_cross / death_cross:        params: {{}}
- ema_rising:                        params: {{"window": <number>}}  ← EMA slope is rising
- touched_ema:                       params: {{"window": <number>}}  ← low touched the EMA (pullback signal)
- closed_above_ema:                  params: {{"window": <number>}}  ← candle closed above EMA (pullback recovery)
- ema_cross_above / ema_cross_below: params: {{"fast": <number>, "slow": <number>}}  ← fast EMA crosses slow EMA
- hammer / bullish_engulfing / hammer_or_engulf: params: {{}}
- adx_above / adx_below:             params: {{"value": <number>}}
- bb_pct_below / bb_pct_above:       params: {{"value": <number>}}
- price_below_bb_lower / price_above_bb_upper: params: {{}}
- stoch_k_below / stoch_k_above:     params: {{"value": <number>}}
- stoch_oversold / stoch_overbought: params: {{"value": <number>}}
- volume_above_avg:                  params: {{"multiplier": <number>}}  e.g. 1.2 for volume > 1.2x 20-day avg
- formula:                           params: {{"expr": "<expression using column names>"}}
  Available columns: close, open, high, low, volume, vol_sma_20, rsi, rsi_2, macd, macd_signal,
  sma_20, sma_50, sma_200, ema_8, ema_12, ema_20, ema_21, ema_26, adx, bb_pct, atr, stoch_k, stoch_d

IMPORTANT RULES:
1. Map every stated condition to a registry type — do not drop any.
   "positive close" or "candle closes up" → formula {{"expr": "close > open"}}
2. "price below EMA-N" as an exit → use price_below_ema {{"period": N}}, NOT closed_above_ema.
   closed_above_ema is a pullback recovery signal, not a price-vs-EMA comparison.
3. stop_loss_pct and take_profit_pct must be plain decimals (0.05 = 5%). Never store a ratio.
   If a Risk-to-Reward ratio is given (e.g. 2.5:1) and no explicit stop is stated, default
   stop_loss_pct to 0.04 (4%) and compute take_profit_pct = ratio × stop_loss_pct.
   If an ATR-based stop is given (e.g. "2.0 × ATR"), approximate: default stop_loss_pct to 0.06 (6%)
   since 2×ATR for large-cap stocks is typically 5-8% of price.
4. position_value is the fraction of equity risked per trade (e.g. 0.02 for 2%).

OUTPUT: Respond with ONLY a valid JSON object in this exact format:
{{
  "name": "<setup name from the text>",
  "description": "<one sentence summary>",
  "definition": {{
    "entry_conditions": [
      {{"label": "<human readable label>", "type": "<registry type>", "params": {{}}}}
    ],
    "exit_conditions": [
      {{"label": "<human readable label>", "type": "<registry type>", "params": {{}}}}
    ],
    "stop_loss_pct": <decimal e.g. 0.05 for 5%>,
    "take_profit_pct": <decimal or null>,
    "position_type": "equity_pct",
    "position_value": <risk_percent / 100>
  }}
}}

SETUP TEXT:
{setup_text}"""


@tool
def save_trade_setup(setup_text: str) -> dict:
    """Parse a human-readable trading setup and save it to the setup store.

    Use this tool when the user wants to save, create, or add a new trading setup.
    The setup_text should contain the setup name, entry conditions, exit conditions,
    and position sizing in plain English.

    Args:
        setup_text: The full setup definition in human-readable format.

    Returns:
        JSON with the saved setup id and parsed definition, or an error.
    """
    from anthropic import Anthropic
    from config import ANTHROPIC_API_KEY

    registry_types = sorted(REGISTRY.keys())
    prompt = _SETUP_PARSE_PROMPT.format(
        registry_types=", ".join(registry_types),
        setup_text=setup_text.strip(),
    )

    try:
        client = Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        content = response.content[0].text

        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            return {"responseType": "SaveSetup", "status": "error", "error": "LLM did not return valid JSON."}

        parsed = json.loads(match.group())
        name        = parsed.get("name", "Unnamed Setup")
        description = parsed.get("description", "")
        definition  = parsed["definition"]

        all_conditions = definition.get("entry_conditions", []) + definition.get("exit_conditions", [])
        unknown = [c["type"] for c in all_conditions if c["type"] not in REGISTRY]
        if unknown:
            return {
                "responseType": "SaveSetup",
                "status": "error",
                "error": f"Unknown condition types: {unknown}. Available: {sorted(REGISTRY.keys())}",
            }

        setup_id = _store.save(name=name, description=description, definition=definition)
        return {
            "responseType":    "SaveSetup",
            "status":          "saved",
            "id":              setup_id,
            "name":            name,
            "description":     description,
            "definition":      definition,
            "already_formatted": True,
        }

    except Exception as e:
        return {"responseType": "SaveSetup", "status": "error", "error": str(e)}


@tool
def list_trade_setups() -> dict:
    """List all trading setups saved in the setup store.

    Use this tool when the user wants to see all available setups.
    Examples:
      - "Show me all setups"
      - "List my trading setups"
      - "What setups do I have?"

    Returns:
        JSON with a list of setup summaries (id, name, description, created_at).
    """
    setups = _store.list()
    return {
        "responseType":    "TradeSetupList",
        "count":           len(setups),
        "setups": [
            {
                "id":          s["id"],
                "name":        s["name"],
                "description": s["description"],
                "created_at":  s["created_at"],
            }
            for s in setups
        ],
        "already_formatted": True,
    }


@tool
def get_trade_setup(name: str) -> dict:
    """Retrieve an existing trading setup by name from the setup store.

    Use this tool when the user wants to view, show, or inspect a saved setup.
    Examples:
      - "Show me the RSI_MACD_TREND setup"
      - "What are the conditions for EMA20_PB?"
      - "View the setup called RSI_PRICE_ADX"

    Args:
        name: The setup name (e.g. "RSI_MACD_TREND")

    Returns:
        JSON with the full setup definition or an error if not found.
    """
    record = _store.get(name)
    if record is None:
        available = [s["name"] for s in _store.list()]
        return {
            "responseType": "TradeSetup",
            "status": "not_found",
            "error": f"Setup '{name}' not found.",
            "available": available,
        }
    return {
        "responseType":    "TradeSetup",
        "status":          "found",
        "id":              record["id"],
        "name":            record["name"],
        "description":     record["description"],
        "definition":      record["definition"],
        "created_at":      record["created_at"],
        "already_formatted": True,
    }


SETUP_TOOLS = [save_trade_setup, list_trade_setups, get_trade_setup]
