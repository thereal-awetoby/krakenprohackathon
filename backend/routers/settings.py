# backend/routers/settings.py
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import BotSettings
from datetime import datetime
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()

# ─── Pydantic Schema for Updates ─────────────────────────────────────────────

class SettingsUpdate(BaseModel):
    """
    Schema for updating multiple settings at once.
    All fields are optional — only send what you want to change.
    """
    max_risk_per_trade:   float | None = None   # e.g. 2.0 = 2% per trade
    max_open_trades:      int   | None = None   # e.g. 5 max positions
    trade_crypto:         bool  | None = None
    trade_stocks:         bool  | None = None
    trade_forex:          bool  | None = None
    strategy:             str   | None = None   # "rsi", "macd", "combined", "ai"
    run_interval_minutes: int   | None = None   # how often agent runs

# ─── Helper: Get or Create Settings ──────────────────────────────────────────

def _get_or_create_settings(db: Session) -> BotSettings:
    """
    Gets settings from DB, or creates safe defaults if none exist yet.
    """
    settings = db.query(BotSettings).first()
    if not settings:
        logger.info("No settings found — creating defaults")
        settings = BotSettings(
            is_running           = False,
            max_risk_per_trade   = 2.0,
            max_open_trades      = 5,
            trade_crypto         = True,
            trade_stocks         = True,
            trade_forex          = True,
            strategy             = "combined",
            run_interval_minutes = 60
        )
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings

# ─── Get Settings ─────────────────────────────────────────────────────────────

@router.get("/")
def get_settings(db: Session = Depends(get_db)):
    """Get all current bot settings."""
    try:
        settings = _get_or_create_settings(db)
        return _format_settings(settings)
    except Exception as e:
        logger.error(f"get_settings error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ─── Toggle Bot On / Off ──────────────────────────────────────────────────────

@router.post("/toggle")
def toggle_bot(db: Session = Depends(get_db)):
    """
    Start or stop the trading bot.
    If running → stops it. If stopped → starts it.
    """
    try:
        settings            = _get_or_create_settings(db)
        settings.is_running = not settings.is_running
        db.commit()

        status = "STARTED ▶️" if settings.is_running else "STOPPED ⏸"
        logger.info(f"Bot {status}")

        return {
            "is_running": settings.is_running,
            "message":    f"Bot {status}"
        }

    except Exception as e:
        db.rollback()
        logger.error(f"toggle_bot error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ─── Set Strategy ─────────────────────────────────────────────────────────────

@router.post("/strategy/{name}")
def set_strategy(name: str, db: Session = Depends(get_db)):
    """
    Change the trading strategy.
    Valid options: rsi, macd, combined, ai
    """
    valid_strategies = {"rsi", "macd", "combined", "ai"}

    if name.lower() not in valid_strategies:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid strategy '{name}'. Must be one of: {', '.join(valid_strategies)}"
        )

    try:
        settings          = _get_or_create_settings(db)
        settings.strategy = name.lower()
        db.commit()

        logger.info(f"Strategy changed to: {name}")
        return {
            "strategy": settings.strategy,
            "message":  f"Strategy updated to {name}"
        }

    except Exception as e:
        db.rollback()
        logger.error(f"set_strategy error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ─── Update Multiple Settings At Once ────────────────────────────────────────

@router.post("/update")
def update_settings(payload: SettingsUpdate, db: Session = Depends(get_db)):
    """
    Update one or more settings at once.
    Only the fields you send will be updated — others stay the same.
    """
    try:
        settings = _get_or_create_settings(db)

        # Only update fields that were actually sent
        if payload.max_risk_per_trade is not None:
            if not (0.1 <= payload.max_risk_per_trade <= 10.0):
                raise HTTPException(
                    status_code=400,
                    detail="max_risk_per_trade must be between 0.1% and 10%"
                )
            settings.max_risk_per_trade = payload.max_risk_per_trade

        if payload.max_open_trades is not None:
            if not (1 <= payload.max_open_trades <= 20):
                raise HTTPException(
                    status_code=400,
                    detail="max_open_trades must be between 1 and 20"
                )
            settings.max_open_trades = payload.max_open_trades

        if payload.trade_crypto is not None:
            settings.trade_crypto = payload.trade_crypto

        if payload.trade_stocks is not None:
            settings.trade_stocks = payload.trade_stocks

        if payload.trade_forex is not None:
            settings.trade_forex = payload.trade_forex

        if payload.strategy is not None:
            valid = {"rsi", "macd", "combined", "ai"}
            if payload.strategy.lower() not in valid:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid strategy. Must be one of: {', '.join(valid)}"
                )
            settings.strategy = payload.strategy.lower()

        if payload.run_interval_minutes is not None:
            if not (5 <= payload.run_interval_minutes <= 1440):
                raise HTTPException(
                    status_code=400,
                    detail="run_interval_minutes must be between 5 and 1440 (1 day)"
                )
            settings.run_interval_minutes = payload.run_interval_minutes

        db.commit()
        logger.info("Settings updated successfully")
        return _format_settings(settings)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"update_settings error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ─── Toggle Individual Markets ────────────────────────────────────────────────

@router.post("/markets/{market}/toggle")
def toggle_market(market: str, db: Session = Depends(get_db)):
    """
    Enable or disable trading for a specific market.
    market must be: crypto, stocks, or forex
    """
    valid_markets = {"crypto", "stocks", "forex"}
    if market.lower() not in valid_markets:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid market '{market}'. Must be: crypto, stocks, forex"
        )

    try:
        settings = _get_or_create_settings(db)

        if market == "crypto":
            settings.trade_crypto = not settings.trade_crypto
            new_state = settings.trade_crypto
        elif market == "stocks":
            settings.trade_stocks = not settings.trade_stocks
            new_state = settings.trade_stocks
        elif market == "forex":
            settings.trade_forex = not settings.trade_forex
            new_state = settings.trade_forex

        db.commit()
        logger.info(f"{market} trading {'enabled' if new_state else 'disabled'}")

        return {
            "market":  market,
            "enabled": new_state,
            "message": f"{market} trading {'enabled ✅' if new_state else 'disabled ❌'}"
        }

    except Exception as e:
        db.rollback()
        logger.error(f"toggle_market error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ─── Format Helper ────────────────────────────────────────────────────────────

def _format_settings(settings: BotSettings) -> dict:
    """Converts BotSettings DB object to clean dictionary."""
    return {
        "id":                   settings.id,
        "is_running":           settings.is_running,
        "strategy":             settings.strategy,
        "max_risk_per_trade":   settings.max_risk_per_trade,
        "max_open_trades":      settings.max_open_trades,
        "trade_crypto":         settings.trade_crypto,
        "trade_stocks":         settings.trade_stocks,
        "trade_forex":          settings.trade_forex,
        "run_interval_minutes": settings.run_interval_minutes,
        "last_run":             settings.last_run.isoformat() if settings.last_run else None,
        "created_at":           settings.created_at.isoformat() if settings.created_at else None,
    }