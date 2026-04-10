# backend/strategies/rsi_strategy.py
import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)

# ─── Core Indicators ──────────────────────────────────────────────────────────

def calculate_rsi(prices: list, period: int = 14) -> float:
    """
    Calculate RSI (Relative Strength Index).
    Returns a float between 0-100, or None if not enough data.
    """
    if len(prices) < period + 1:
        logger.warning(f"Not enough prices for RSI. Need {period + 1}, got {len(prices)}")
        return None

    df = pd.Series(prices, dtype=float)
    delta = df.diff()

    gain = delta.where(delta > 0, 0.0).rolling(window=period).mean()
    loss = -delta.where(delta < 0, 0.0).rolling(window=period).mean()

    # Avoid division by zero — if loss is 0, RSI is 100 (fully overbought)
    last_loss = loss.iloc[-1]
    if last_loss == 0:
        return 100.0

    rs = gain.iloc[-1] / last_loss
    rsi = 100 - (100 / (1 + rs))

    return round(float(rsi), 2)


def calculate_macd(prices: list, fast: int = 12, slow: int = 26, signal: int = 9):
    """
    Calculate MACD line, signal line, and histogram.
    Returns (macd, signal, histogram) or (None, None, None) if not enough data.
    """
    if len(prices) < slow + signal:
        logger.warning(f"Not enough prices for MACD. Need {slow + signal}, got {len(prices)}")
        return None, None, None

    df = pd.Series(prices, dtype=float)

    ema_fast   = df.ewm(span=fast,   adjust=False).mean()
    ema_slow   = df.ewm(span=slow,   adjust=False).mean()
    macd_line  = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram  = macd_line - signal_line

    return (
        round(float(macd_line.iloc[-1]),   6),
        round(float(signal_line.iloc[-1]), 6),
        round(float(histogram.iloc[-1]),   6)
    )


def calculate_bollinger_bands(prices: list, period: int = 20, std_dev: float = 2.0):
    """
    Calculate Bollinger Bands.
    Returns (upper_band, middle_band, lower_band) or (None, None, None).
    Used as extra confirmation for buy/sell signals.
    """
    if len(prices) < period:
        logger.warning(f"Not enough prices for Bollinger Bands. Need {period}, got {len(prices)}")
        return None, None, None

    df = pd.Series(prices, dtype=float)
    middle = df.rolling(window=period).mean().iloc[-1]
    std    = df.rolling(window=period).std().iloc[-1]

    upper = middle + (std_dev * std)
    lower = middle - (std_dev * std)

    return round(upper, 6), round(middle, 6), round(lower, 6)


# ─── Individual Signals ───────────────────────────────────────────────────────

def rsi_signal(prices: list) -> dict:
    """
    RSI-based trading signal.
    Returns: { action, reason, confidence, rsi_value }
    
    Logic:
      - RSI < 30  → oversold  → BUY signal
      - RSI > 70  → overbought → SELL signal
      - RSI 30-70 → neutral   → HOLD
    """
    if not prices or len(prices) < 15:
        return {
            "action": "hold",
            "reason": "Not enough price data for RSI",
            "confidence": 0.0,
            "rsi_value": None
        }

    rsi = calculate_rsi(prices)

    if rsi is None:
        return {"action": "hold", "reason": "RSI calculation failed", "confidence": 0.0, "rsi_value": None}

    if rsi < 30:
        # More oversold = higher confidence (RSI of 10 = max confidence)
        confidence = round(min((30 - rsi) / 30, 1.0), 2)
        return {
            "action": "buy",
            "reason": f"RSI is {rsi} — oversold territory, expecting bounce upward",
            "confidence": confidence,
            "rsi_value": rsi
        }

    elif rsi > 70:
        # More overbought = higher confidence (RSI of 90 = max confidence)
        confidence = round(min((rsi - 70) / 30, 1.0), 2)
        return {
            "action": "sell",
            "reason": f"RSI is {rsi} — overbought territory, expecting pullback",
            "confidence": confidence,
            "rsi_value": rsi
        }

    else:
        # Scale confidence by how close to neutral 50 we are
        distance_from_neutral = abs(rsi - 50)
        return {
            "action": "hold",
            "reason": f"RSI is {rsi} — neutral zone, no clear signal",
            "confidence": 0.0,
            "rsi_value": rsi
        }


def macd_signal(prices: list) -> dict:
    """
    MACD crossover trading signal.
    Returns: { action, reason, confidence, macd_value, signal_value, histogram }

    Logic:
      - MACD crosses above signal AND both > 0 → strong BUY
      - MACD crosses below signal AND both < 0 → strong SELL
      - MACD > signal but negative territory   → weak buy (hold)
      - MACD < signal but positive territory   → weak sell (hold)
    """
    if not prices or len(prices) < 35:
        return {
            "action": "hold",
            "reason": "Not enough price data for MACD",
            "confidence": 0.0,
            "macd_value": None,
            "signal_value": None,
            "histogram": None
        }

    macd, signal, histogram = calculate_macd(prices)

    if macd is None:
        return {
            "action": "hold",
            "reason": "MACD calculation failed",
            "confidence": 0.0,
            "macd_value": None,
            "signal_value": None,
            "histogram": None
        }

    separation = abs(macd - signal)

    # Strong buy: MACD above signal AND in positive territory
    if macd > signal and macd > 0:
        confidence = round(min(separation * 100, 1.0), 2)
        return {
            "action": "buy",
            "reason": f"MACD ({macd}) above signal ({signal}) in positive zone — bullish crossover",
            "confidence": confidence,
            "macd_value": macd,
            "signal_value": signal,
            "histogram": histogram
        }

    # Strong sell: MACD below signal AND in negative territory
    elif macd < signal and macd < 0:
        confidence = round(min(separation * 100, 1.0), 2)
        return {
            "action": "sell",
            "reason": f"MACD ({macd}) below signal ({signal}) in negative zone — bearish crossover",
            "confidence": confidence,
            "macd_value": macd,
            "signal_value": signal,
            "histogram": histogram
        }

    # Weak signals — hold
    else:
        return {
            "action": "hold",
            "reason": f"MACD ({macd}) vs signal ({signal}) — no strong crossover confirmed",
            "confidence": 0.0,
            "macd_value": macd,
            "signal_value": signal,
            "histogram": histogram
        }


# ─── Combined Signal (RSI + MACD + Bollinger) ─────────────────────────────────

def combined_signal(prices: list) -> dict:
    """
    Uses RSI + MACD + Bollinger Bands together for a stronger, more reliable signal.
    All three must agree for a high-confidence trade.
    
    This is the RECOMMENDED signal to use in the trading agent.
    Returns: { action, reason, confidence, indicators }
    """
    if not prices or len(prices) < 35:
        return {
            "action": "hold",
            "reason": "Not enough data for combined analysis",
            "confidence": 0.0,
            "indicators": {}
        }

    rsi_result  = rsi_signal(prices)
    macd_result = macd_signal(prices)
    upper, middle, lower = calculate_bollinger_bands(prices)
    current_price = prices[-1]

    rsi_action  = rsi_result["action"]
    macd_action = macd_result["action"]

    # Bollinger Band confirmation
    bb_action = "hold"
    if lower is not None:
        if current_price <= lower:
            bb_action = "buy"   # price at lower band = oversold
        elif current_price >= upper:
            bb_action = "sell"  # price at upper band = overbought

    # Count agreements
    votes = {"buy": 0, "sell": 0, "hold": 0}
    votes[rsi_action]  += 1
    votes[macd_action] += 1
    votes[bb_action]   += 1

    # All 3 agree = highest confidence
    if votes["buy"] == 3:
        avg_confidence = round((rsi_result["confidence"] + macd_result["confidence"]) / 2, 2)
        return {
            "action": "buy",
            "reason": f"STRONG BUY — RSI ({rsi_result['rsi_value']}), MACD, and Bollinger Bands all agree",
            "confidence": min(avg_confidence + 0.3, 1.0),  # bonus for full agreement
            "indicators": {
                "rsi": rsi_result["rsi_value"],
                "macd": macd_result["macd_value"],
                "bb_lower": lower,
                "bb_upper": upper,
                "price": current_price
            }
        }

    elif votes["sell"] == 3:
        avg_confidence = round((rsi_result["confidence"] + macd_result["confidence"]) / 2, 2)
        return {
            "action": "sell",
            "reason": f"STRONG SELL — RSI ({rsi_result['rsi_value']}), MACD, and Bollinger Bands all agree",
            "confidence": min(avg_confidence + 0.3, 1.0),
            "indicators": {
                "rsi": rsi_result["rsi_value"],
                "macd": macd_result["macd_value"],
                "bb_lower": lower,
                "bb_upper": upper,
                "price": current_price
            }
        }

    # 2 out of 3 agree = medium confidence
    elif votes["buy"] == 2:
        avg_confidence = round((rsi_result["confidence"] + macd_result["confidence"]) / 2, 2)
        agreeing = [k for k, v in {"RSI": rsi_action, "MACD": macd_action, "BB": bb_action}.items() if v == "buy"]
        return {
            "action": "buy",
            "reason": f"Moderate BUY — {' and '.join(agreeing)} signal bullish",
            "confidence": round(avg_confidence * 0.7, 2),  # lower confidence for partial agreement
            "indicators": {
                "rsi": rsi_result["rsi_value"],
                "macd": macd_result["macd_value"],
                "bb_lower": lower,
                "bb_upper": upper,
                "price": current_price
            }
        }

    elif votes["sell"] == 2:
        avg_confidence = round((rsi_result["confidence"] + macd_result["confidence"]) / 2, 2)
        agreeing = [k for k, v in {"RSI": rsi_action, "MACD": macd_action, "BB": bb_action}.items() if v == "sell"]
        return {
            "action": "sell",
            "reason": f"Moderate SELL — {' and '.join(agreeing)} signal bearish",
            "confidence": round(avg_confidence * 0.7, 2),
            "indicators": {
                "rsi": rsi_result["rsi_value"],
                "macd": macd_result["macd_value"],
                "bb_lower": lower,
                "bb_upper": upper,
                "price": current_price
            }
        }

    # No agreement = hold
    else:
        return {
            "action": "hold",
            "reason": f"Mixed signals — RSI says {rsi_action}, MACD says {macd_action}, BB says {bb_action}",
            "confidence": 0.0,
            "indicators": {
                "rsi": rsi_result["rsi_value"],
                "macd": macd_result["macd_value"],
                "bb_lower": lower,
                "bb_upper": upper,
                "price": current_price
            }
        }