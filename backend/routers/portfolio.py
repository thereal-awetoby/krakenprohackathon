# backend/routers/portfolio.py
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import Portfolio, Trade, TradeStatus, MarketType
from datetime import datetime

logger = logging.getLogger(__name__)
router = APIRouter()

# ─── Helper: Create Default Portfolio ────────────────────────────────────────

def _get_or_create_portfolio(db: Session) -> Portfolio:
    """
    Gets the portfolio from DB, or creates a fresh one with
    $100,000 paper money if it doesn't exist yet.
    """
    portfolio = db.query(Portfolio).first()
    if not portfolio:
        logger.info("No portfolio found — creating default with $100,000 paper balance")
        portfolio = Portfolio(
            balance         = 100000.0,
            initial_balance = 100000.0
        )
        db.add(portfolio)
        db.commit()
        db.refresh(portfolio)
    return portfolio

# ─── Get Portfolio ────────────────────────────────────────────────────────────

@router.get("/")
def get_portfolio(db: Session = Depends(get_db)):
    """
    Get full portfolio summary including balance, P&L,
    win rate, return %, and per-market breakdown.
    """
    try:
        portfolio = _get_or_create_portfolio(db)

        # Calculate win rate safely
        win_rate = (
            (portfolio.winning_trades / portfolio.total_trades) * 100
            if portfolio.total_trades > 0 else 0.0
        )

        # Calculate return % safely
        return_pct = (
            ((portfolio.balance - portfolio.initial_balance) / portfolio.initial_balance) * 100
            if portfolio.initial_balance > 0 else 0.0
        )

        # Count currently open positions
        open_positions = db.query(Trade).filter(
            Trade.status == TradeStatus.OPEN
        ).count()

        return {
            "balance":          round(portfolio.balance, 2),
            "initial_balance":  round(portfolio.initial_balance, 2),
            "total_pnl":        round(portfolio.total_pnl, 2),
            "return_pct":       round(return_pct, 2),
            "win_rate":         round(win_rate, 2),
            "total_trades":     portfolio.total_trades,
            "winning_trades":   portfolio.winning_trades,
            "losing_trades":    portfolio.losing_trades,
            "open_positions":   open_positions,

            # Per-market P&L breakdown
            "by_market": {
                "crypto": round(portfolio.crypto_pnl, 2),
                "stocks": round(portfolio.stock_pnl,  2),
                "forex":  round(portfolio.forex_pnl,  2)
            },

            "updated_at": portfolio.updated_at.isoformat() if portfolio.updated_at else None
        }

    except Exception as e:
        logger.error(f"get_portfolio error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ─── Get Portfolio History (P&L over time) ────────────────────────────────────

@router.get("/history")
def get_portfolio_history(db: Session = Depends(get_db)):
    """
    Returns closed trades in chronological order so the
    frontend can draw a P&L over time chart.
    """
    try:
        closed_trades = (
            db.query(Trade)
            .filter(Trade.status == TradeStatus.CLOSED)
            .order_by(Trade.closed_at)
            .all()
        )

        history     = []
        running_pnl = 0.0

        for trade in closed_trades:
            if trade.pnl is not None:
                running_pnl += trade.pnl
                history.append({
                    "date":        trade.closed_at.isoformat() if trade.closed_at else None,
                    "symbol":      trade.symbol,
                    "pnl":         round(trade.pnl, 2),
                    "running_pnl": round(running_pnl, 2),
                    "market_type": trade.market_type.value if trade.market_type else None
                })

        return {
            "count":   len(history),
            "history": history
        }

    except Exception as e:
        logger.error(f"get_portfolio_history error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ─── Get Open Positions Value ─────────────────────────────────────────────────

@router.get("/positions")
def get_open_positions(db: Session = Depends(get_db)):
    """
    Returns all currently open trades with their details.
    Used by the dashboard positions panel.
    """
    try:
        open_trades = (
            db.query(Trade)
            .filter(Trade.status == TradeStatus.OPEN)
            .order_by(Trade.opened_at)
            .all()
        )

        positions = []
        for t in open_trades:
            positions.append({
                "id":          t.id,
                "symbol":      t.symbol,
                "market_type": t.market_type.value if t.market_type else None,
                "broker":      t.broker.value      if t.broker      else None,
                "side":        t.side,
                "quantity":    t.quantity,
                "entry_price": t.entry_price,
                "stop_loss":   t.stop_loss,
                "take_profit": t.take_profit,
                "strategy":    t.strategy,
                "opened_at":   t.opened_at.isoformat() if t.opened_at else None
            })

        return {
            "count":     len(positions),
            "positions": positions
        }

    except Exception as e:
        logger.error(f"get_open_positions error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ─── Reset Portfolio ──────────────────────────────────────────────────────────

@router.post("/reset")
def reset_portfolio(db: Session = Depends(get_db)):
    """
    Reset portfolio back to $100,000 paper money and clear all trades.
    Useful for starting fresh during testing.
    """
    try:
        # Delete all trades
        db.query(Trade).delete()

        # Reset portfolio to defaults
        portfolio = db.query(Portfolio).first()
        if portfolio:
            portfolio.balance         = 100000.0
            portfolio.initial_balance = 100000.0
            portfolio.total_pnl       = 0.0
            portfolio.total_trades    = 0
            portfolio.winning_trades  = 0
            portfolio.losing_trades   = 0
            portfolio.crypto_pnl      = 0.0
            portfolio.stock_pnl       = 0.0
            portfolio.forex_pnl       = 0.0
            portfolio.updated_at      = datetime.utcnow()
        else:
            portfolio = Portfolio(
                balance         = 100000.0,
                initial_balance = 100000.0
            )
            db.add(portfolio)

        db.commit()
        logger.info("Portfolio reset to $100,000 paper balance")
        return {"message": "Portfolio reset successfully", "balance": 100000.0}

    except Exception as e:
        db.rollback()
        logger.error(f"reset_portfolio error: {e}")
        raise HTTPException(status_code=500, detail=str(e))