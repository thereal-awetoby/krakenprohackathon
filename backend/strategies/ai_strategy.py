# backend/strategies/ai_strategy.py
import openai
import json
import os
import logging

logger = logging.getLogger(__name__)

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _safe_fallback(reason: str) -> dict:
    """Returns a safe HOLD signal when AI is unavailable or fails."""
    return {
        "action": "hold",
        "reason": reason,
        "confidence": 0.0,
        "stop_loss_pct": 2.0,
        "take_profit_pct": 4.0,
        "indicators": {}
    }

def _validate_response(data: dict) -> dict:
    """
    Makes sure the AI response has all required fields.
    Fills in safe defaults for anything missing.
    """
    valid_actions = {"buy", "sell", "hold"}

    # Ensure action is valid
    if data.get("action") not in valid_actions:
        data["action"] = "hold"

    # Ensure confidence is a float between 0 and 1
    try:
        confidence = float(data.get("confidence", 0.0))
        data["confidence"] = max(0.0, min(confidence, 1.0))
    except (TypeError, ValueError):
        data["confidence"] = 0.0

    # Ensure stop loss and take profit are reasonable numbers
    try:
        data["stop_loss_pct"] = float(data.get("stop_loss_pct", 2.0))
    except (TypeError, ValueError):
        data["stop_loss_pct"] = 2.0

    try:
        data["take_profit_pct"] = float(data.get("take_profit_pct", 4.0))
    except (TypeError, ValueError):
        data["take_profit_pct"] = 4.0

    # Ensure reason is a string
    if not isinstance(data.get("reason"), str):
        data["reason"] = "AI signal (no reason provided)"

    return data

def _build_prompt(symbol: str, prices: list, market_type: str) -> str:
    """
    Builds a detailed prompt for the AI with useful market context.
    More context = better AI decisions.
    """
    recent_prices  = prices[-20:]
    current_price  = recent_prices[-1]
    highest_price  = max(recent_prices)
    lowest_price   = min(recent_prices)
    price_change   = ((current_price - recent_prices[0]) / recent_prices[0]) * 100

    # Calculate a simple average to see trend direction
    first_half_avg = sum(recent_prices[:10]) / 10
    second_half_avg = sum(recent_prices[10:]) / 10
    trend = "upward" if second_half_avg > first_half_avg else "downward"

    # Volatility = difference between high and low as a percentage
    volatility = ((highest_price - lowest_price) / lowest_price) * 100

    return f"""
You are an expert quantitative trading analyst specializing in {market_type} markets.
Analyze the following market data and return a trading signal.

=== ASSET INFO ===
Symbol: {symbol}
Market Type: {market_type}

=== PRICE DATA (last 20 periods) ===
Prices: {recent_prices}
Current Price: {current_price}
Highest in Period: {highest_price}
Lowest in Period: {lowest_price}
Price Change: {price_change:.2f}%
Trend Direction: {trend}
Volatility: {volatility:.2f}%

=== YOUR TASK ===
Based ONLY on this data, return a JSON trading signal.
Consider: trend direction, support/resistance levels, volatility, and momentum.

Respond ONLY with a valid JSON object — no extra text, no markdown:
{{
    "action": "buy" or "sell" or "hold",
    "reason": "1-2 sentence explanation of your decision",
    "confidence": a float from 0.0 (uncertain) to 1.0 (very confident),
    "stop_loss_pct": percentage below entry to place stop loss (e.g. 2.0),
    "take_profit_pct": percentage above entry to place take profit (e.g. 4.0)
}}

Rules:
- Only return "buy" or "sell" if confidence is above 0.5
- Return "hold" if the signal is unclear or risky
- stop_loss_pct must always be less than take_profit_pct (good risk/reward)
- Be conservative — protecting capital is more important than making trades
"""

# ─── Main AI Signal Function ──────────────────────────────────────────────────

async def ai_signal(symbol: str, prices: list, market_type: str) -> dict:
    """
    Uses GPT to analyze price data and return a trading signal.

    Returns:
        dict with keys: action, reason, confidence, stop_loss_pct, take_profit_pct
    """

    # ── Check we have an API key ──────────────────────────────────────────────
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.warning("OPENAI_API_KEY not set — AI strategy returning hold")
        return _safe_fallback("OpenAI API key not configured")

    # ── Check we have enough price data ──────────────────────────────────────
    if not prices or len(prices) < 20:
        logger.warning(f"Not enough price data for AI signal on {symbol}. Need 20, got {len(prices)}")
        return _safe_fallback("Not enough price data for AI analysis")

    # ── Call OpenAI ───────────────────────────────────────────────────────────
    try:
        client = openai.AsyncOpenAI(api_key=api_key)
        prompt = _build_prompt(symbol, prices, market_type)

        logger.info(f"Requesting AI signal for {symbol} ({market_type})...")

        response = await client.chat.completions.create(
            model="gpt-4o-mini",       # cheap and fast — good for frequent signals
            max_tokens=300,            # signal is short, no need for more
            temperature=0.2,           # low temperature = more consistent decisions
            messages=[
                {
                    "role": "system",
                    "content": "You are a trading analyst. Always respond with valid JSON only. No markdown, no explanation outside the JSON."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            response_format={"type": "json_object"}  # forces JSON output
        )

        raw_content = response.choices[0].message.content
        logger.info(f"AI response for {symbol}: {raw_content}")

        # ── Parse and validate the response ──────────────────────────────────
        data = json.loads(raw_content)
        validated = _validate_response(data)

        logger.info(f"AI signal for {symbol}: {validated['action']} (confidence: {validated['confidence']})")
        return validated

    except json.JSONDecodeError as e:
        logger.error(f"AI returned invalid JSON for {symbol}: {e}")
        return _safe_fallback("AI returned invalid response format")

    except openai.RateLimitError:
        logger.error("OpenAI rate limit hit — returning hold")
        return _safe_fallback("OpenAI rate limit reached, skipping AI signal")

    except openai.AuthenticationError:
        logger.error("OpenAI API key is invalid")
        return _safe_fallback("OpenAI authentication failed — check your API key in .env")

    except openai.APIConnectionError:
        logger.error("Cannot connect to OpenAI API")
        return _safe_fallback("Cannot connect to OpenAI — check your internet connection")

    except Exception as e:
        logger.error(f"Unexpected error in AI strategy for {symbol}: {e}")
        return _safe_fallback(f"AI strategy error: {str(e)}")