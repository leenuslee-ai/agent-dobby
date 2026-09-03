# 3 Algorithmic Swing Templates For Daily Monitoring1. 

## Mean-Reversal 
(Best for GOOGL & AMZN)
This algorithm monitors daily charts to identify when highly capitalized, fundamentally sound tech stocks are structurally oversold relative to their historical valuation limits.

## 1. Daily Evaluation Logic 
### (Entry):Price is less than or equal to 50-Day EMA.RSI (14-period) is less than or equal to 40.Daily Volume is greater than 1.2x of the 20-Day Volume Moving Average.
### Algorithmic Automation Rule: If all three parameters evaluate to TRUE at market close, place a buy order for the next morning's open.
### Risk Engine (Exit):
#### Hard Stop: Set a trailing script condition Price is less than Entry Price - 3.5%.
#### Take Profit: Exit code triggers automatically when RSI (14-period) crosses above 65.

## 2. Momentum-Breakout -- Not easy -- so not configured
(Best for NVDA & TSLA)
This setup monitors the daily consolidation ranges of highly volatile stocks and triggers an order execution when a breakout occurs with high institutional volume.
## Daily Evaluation Logic 
### (Entry):Identify the Highest High and Lowest Low of the last 5 trading days (forming a local price channel).Price crosses above the calculated 5-Day Highest High marker.Daily Volume is greater than 1.5x of the 20-Day Volume Moving Average.
### Algorithmic Automation Rule: Fire an immediate market buy order if a breakout condition occurs between 10:00 AM and 3:30 PM EST to avoid opening bell volatility spikes.
### Risk Engine (Exit):
#### Hard Stop: Calculated utilizing the Average True Range (ATR). Set stop condition to Breakout Entry Price - (1.5 * ATR).
#### Take Profit: Set an automated rolling target condition to scale out 50% of the position at Breakout Entry Price + (3.0 * ATR), while applying a trailing stop on the remaining shares.

## MA-Trend-Follower 
(Best for AAPL)
This trend-continuation engine functions by analyzing short-term daily exponential moving averages against medium-term trend direction.
## Daily Evaluation Logic 
### (Entry):Price is sitting strictly above the 50-Day Simple Moving Average (SMA) (ensures macro bullish structure).The 8-Day EMA crosses above the 21-Day EMA on the daily chart.
### Algorithmic Automation Rule: If the daily candle finishes with a positive close and the crossover holds valid, auto-execute a market position entry.
### Risk Engine (Exit):
#### Hard Stop: Close position if Price drops below the 21-Day EMA line on a daily closing basis.
#### Take Profit: System automatically exits the trade if a fixed 2.5:1 Risk-to-Reward Ratio parameter is met.

Daily-RSI-2
The Daily RSI-2 Momentum Connors Setup (Medium-High Trigger Frequency)Standard swing indicators use a 14-day window, which makes them slow to react. By drastically shortening your monitoring window to an ultra-fast 2-period RSI, your algorithm will catch rapid 2-to-3 day extreme price drops and sudden explosive moves.Daily Evaluation Logic (Entry):Price must be trading completely above its macro 200-day SMA (ensuring you only buy pullbacks in structural uptrends).The ultra-fast RSI (2-period) drops below 10 at the daily market close.Why It Triggers Constantly: In a normal market, healthy stocks like AMZN, AAPL, and GOOGL drop for 2 or 3 consecutive days all the time. A 2-period RSI will immediately flag these brief pullbacks as "exhausted" and buy the quick bounce.Risk Engine (Exit):Stop Loss: Set a hard stop at 2.0 * ATR (Average True Range) below your entry price.Take Profit: Close the trade the exact moment the RSI (2-period) crosses back above 70.

Daily-RSI-14
A simple swing setup using RSI 14-day window
Daily Evaluation Logic 
Entry: RSI14 < 30
Exit: RSI > 70
 



{
  "id": "33260f16-c393-4bb6-a220-5e4de9f09ac9",
  "name": "RSI_MACD_TREND",
  "description": "Enter when RSI is oversold and MACD crosses up above its signal line, confirming an uptrend via SMA-50 and a trending market via ADX > 20.",
  "definition": {
    "entry_conditions": [
      {
        "label": "RSI(14) < 35 (oversold)",
        "type": "rsi_below",
        "params": {
          "value": 35
        }
      },
      {
        "label": "MACD crossover up",
        "type": "macd_crossover_up",
        "params": {}
      },
      {
        "label": "Price above SMA(50)",
        "type": "price_above_sma",
        "params": {
          "period": 50
        }
      },
      {
        "label": "ADX(14) > 20 (trending market)",
        "type": "adx_above",
        "params": {
          "value": 20
        }
      }
    ],
    "exit_conditions": [
      {
        "label": "RSI(14) > 70 (overbought)",
        "type": "rsi_above",
        "params": {
          "value": 70
        }
      },
      {
        "label": "MACD crossover down",
        "type": "macd_crossover_down",
        "params": {}
      }
    ],
    "stop_loss_pct": 0.05,
    "take_profit_pct": 0.15,
    "position_type": "equity_pct",
    "position_value": 0.1
  },
  "created_at": "2026-08-29T12:35:51.086739"
}

{
  "id": "df0c213a-002a-4911-a3a1-9f07b82e3dfc",
  "name": "EMA20_PB",
  "description": "In a clear uptrend, wait for price to pull back and touch the rising 20 EMA, then enter on a hammer or bullish engulfing candle at the line.",
  "definition": {
    "entry_conditions": [
      {
        "label": "EMA-20 is rising",
        "type": "ema_rising",
        "params": {
          "window": 20
        }
      },
      {
        "label": "Price above SMA-50 (uptrend)",
        "type": "price_above_sma",
        "params": {
          "period": 50
        }
      },
      {
        "label": "Low touched EMA-20 (pullback)",
        "type": "touched_ema",
        "params": {
          "window": 20
        }
      },
      {
        "label": "Closed back above EMA-20",
        "type": "closed_above_ema",
        "params": {
          "window": 20
        }
      },
      {
        "label": "Reversal candle (hammer or engulf)",
        "type": "hammer_or_engulf",
        "params": {}
      }
    ],
    "exit_conditions": [
      {
        "label": "RSI overbought > 70",
        "type": "rsi_above",
        "params": {
          "value": 70
        }
      },
      {
        "label": "Price crosses back below EMA-20",
        "type": "price_below_ema",
        "params": {
          "period": 20
        }
      }
    ],
    "stop_loss_pct": 0.03,
    "take_profit_pct": 0.08,
    "position_type": "equity_pct",
    "position_value": 0.1
  },
  "created_at": "2026-08-29T12:35:51.087521"
}

{
  "id": "3f3b0f6e-2c3d-4d50-8387-d9e1ff6ec155",
  "name": "RSI14_Below30",
  "description": "RSI_Below30",
  "definition": {
    "entry_conditions": [
      {
        "label": "RSI(14) < 35 (oversold)",
        "type": "rsi_below",
        "params": {
          "value": 35
        }
      }
    ],
    "exit_conditions": [
      {
        "label": "RSI overbought > 70",
        "type": "rsi_above",
        "params": {
          "value": 70
        }
      },
      {
        "label": "Price crosses back below EMA-20",
        "type": "price_below_ema",
        "params": {
          "period": 20
        }
      }
    ],
    "stop_loss_pct": 0.03,
    "take_profit_pct": 0.08,
    "position_type": "equity_pct",
    "position_value": 0.1
  },
  "created_at": "2026-08-29T14:17:45.447472"
}

{
  "id": "e8d0ca66-52e8-4cd9-aff7-f806072d59ce",
  "name": "RSI_PRICE_ADX",
  "description": "Buy when RSI is oversold below 35, price is above 50-day SMA, and ADX shows trend strength above 20, with exit when RSI crosses above 70.",
  "definition": {
    "entry_conditions": [
      {
        "label": "RSI(14) is below 35 (oversold)",
        "type": "rsi_below",
        "params": {
          "value": 35
        }
      },
      {
        "label": "Price is above 50-day SMA",
        "type": "price_above_sma",
        "params": {
          "period": 50
        }
      },
      {
        "label": "ADX(14) > 20 (trend strength)",
        "type": "adx_above",
        "params": {
          "value": 20
        }
      }
    ],
    "exit_conditions": [
      {
        "label": "RSI(14) crosses above 70 (overbought)",
        "type": "rsi_above",
        "params": {
          "value": 70
        }
      }
    ],
    "stop_loss_pct": 0.05,
    "take_profit_pct": null,
    "position_type": "equity_pct",
    "position_value": 0.02
  },
  "created_at": "2026-08-29T18:01:22.297298"
}

{
  "id": "a8f0fb0f-a504-42eb-ae15-22ff8b1b433a",
  "name": "Mean-Reversal",
  "description": "Identifies oversold tech stocks on daily charts and enters when price is below 50-day EMA, RSI is below 40, and volume exceeds 1.2x average.",
  "definition": {
    "entry_conditions": [
      {
        "label": "Price below 50-day EMA",
        "type": "price_below_ema",
        "params": {
          "period": 50
        }
      },
      {
        "label": "RSI(14) below 40",
        "type": "rsi_below",
        "params": {
          "value": 40
        }
      },
      {
        "label": "Volume above 1.2x 20-day average",
        "type": "volume_above_avg",
        "params": {
          "multiplier": 1.2
        }
      }
    ],
    "exit_conditions": [
      {
        "label": "RSI(14) crosses above 65",
        "type": "rsi_above",
        "params": {
          "value": 65
        }
      }
    ],
    "stop_loss_pct": 0.035,
    "take_profit_pct": null,
    "position_type": "equity_pct",
    "position_value": 0.035
  },
  "created_at": "2026-08-31T23:03:47.215840"
}

{
  "id": "64def0f8-8b8b-45ae-9756-db5facad42f5",
  "name": "MA-Trend-Follower",
  "description": "Trend-continuation strategy using SMA-50 bullish structure, EMA-8/21 crossover, and positive close on daily chart with 2.5:1 risk-reward exit.",
  "definition": {
    "entry_conditions": [
      {
        "label": "Price above 50-Day SMA",
        "type": "price_above_sma",
        "params": {
          "period": 50
        }
      },
      {
        "label": "8-Day EMA crosses above 21-Day EMA",
        "type": "ema_cross_above",
        "params": {
          "fast": 8,
          "slow": 21
        }
      },
      {
        "label": "Daily candle closes positive",
        "type": "formula",
        "params": {
          "expr": "close > open"
        }
      }
    ],
    "exit_conditions": [
      {
        "label": "Price closes below 21-Day EMA",
        "type": "price_below_ema",
        "params": {
          "period": 21
        }
      }
    ],
    "stop_loss_pct": 0.04,
    "take_profit_pct": 0.1,
    "position_type": "equity_pct",
    "position_value": 0.04
  },
  "created_at": "2026-08-31T23:19:39.876875"
}

{
  "id": "2ad0d41c-36c6-4b09-abf9-c1fab9be061c",
  "name": "Daily-RSI-2",
  "description": "Ultra-fast 2-period RSI momentum strategy that enters on extreme oversold conditions (RSI-2 < 10) within a macro uptrend (price > SMA-200), with exits on RSI-2 > 70 or 2.0\u00d7ATR stop loss.",
  "definition": {
    "entry_conditions": [
      {
        "label": "Price above 200-day SMA (macro uptrend)",
        "type": "price_above_sma",
        "params": {
          "period": 200
        }
      },
      {
        "label": "RSI-2 drops below 10 (extreme oversold)",
        "type": "rsi_2_below",
        "params": {
          "value": 10
        }
      }
    ],
    "exit_conditions": [
      {
        "label": "RSI-2 crosses back above 70 (momentum exhaustion)",
        "type": "rsi_2_above",
        "params": {
          "value": 70
        }
      }
    ],
    "stop_loss_pct": 0.06,
    "take_profit_pct": null,
    "position_type": "equity_pct",
    "position_value": 0.02
  },
  "created_at": "2026-08-31T23:37:04.074764"
}







EMA-8/21 Trend Pullback

Concept: Enter when a strong uptrend pulls back briefly to the fast EMA and shows a recovery signal. Rides the trend rather than trying to catch bottoms.


Entry conditions (all must be met):

Price is above SMA-50 (macro uptrend filter)
EMA-8 is above EMA-21 (short-term trend intact)
Price touched or dipped below EMA-8 on the low (the pullback)
Candle closed back above EMA-8 (recovery confirmed)
ADX > 20 (trending market, not choppy)

Exit conditions (any triggers):

Price closes below EMA-21 (trend has broken)
RSI-14 crosses above 75 (extended/overbought, take profits)

Risk management:

Stop loss: 4% below entry
Take profit: 10% above entry (2.5:1 R:R)
Position size: 2% of equity per trade

---


Why this works well for large-cap tech:

These stocks trend strongly and pull back cleanly to their fast EMAs
The ADX filter avoids choppy sideways periods which are common after earnings
The EMA-8 > EMA-21 condition means you're only buying dips in confirmed uptrends, not catching falling knives
The 4% stop is tight enough for large-caps which don't gap as violently as small-caps

What to watch out for:

Avoid entering right before earnings — the setup will fire but gap risk is high
Works best when the broader market (SPY) is also in an uptrend

---


You could save this directly through the chat interface with something like:

> "Save a setup called EMA8_21_PB: entry when price above SMA-50, EMA-8 above EMA-21, touched EMA-8, closed above EMA-8, ADX above 20. Exit when price below EMA-21 or RSI above 75. Stop loss 4%, take profit 10%, risk 2% of equity."