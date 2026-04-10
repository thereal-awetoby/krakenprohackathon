# backend/routers/trades.py
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from database import get_db
from models import Trade, Portfolio, TradeStatus, MarketType, BrokerName
from datetime import datetime

logger = logging.getLogger(__name__)
router = APIRouter()

# ─── Get All Trades ───────────────────────────────────────────────────────────

@router.get("/")
def get_all_trades(
    db:    Session = Depends(get_db),
    limit: int     = Query(default=100, le=500),   # max 500 at once
    skip:  int     = Query(default=0,   ge=0)
):
    """
    Get all trades (open + closed), newest first.
    Supports pagination with limit and skip.
    """
    try:
        trades = (
            db.query(Trade)
            .order_by(desc(Trade.opened_at))
            .offset(skip)
            .limit(limit)
            .all()
        )
        return {
            "total":  db.query(Trade).count(),
            "skip":   skip,
            "limit":  limit,
            "trades": [_format_trade(t) for t in trades]
        }
    except Exception as e:
        logger.error(f"get_all_trades error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ─── Get Open Trades ──────────────────────────────────────────────────────────

@router.get("/open")
def get_open_trades(db: Session = Depends(get_db)):
    """
    Get all currently open positions.
    These are trades that have been bought but not yet sold.
    """
    try:
        trades = (
            db.query(Trade)
            .filter(Trade.status == TradeStatus.OPEN)
            .order_by(desc(Trade.opened_at))
            .all()
        )

        # Calculate unrealized P&L for each open trade
        formatted = []
        for t in trades:
            trade_dict = _format_trade(t)
            formatted.append(trade_dict)

        return {
            "count":  len(formatted),
            "trades": formatted
        }
    except Exception as e:
        logger.error(f"get_open_trades error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ─── Get Trade History (Closed) ───────────────────────────────────────────────

@router.get("/history")
def get_trade_history(
    db:          Session = Depends(get_db),
    limit:       int     = Query(default=50, le=500),
    skip:        int     = Query(default=0,  ge=0),
    market_type: str     = Query(default=None)   # filter by "crypto", "stock", "forex"
):
    """
    Get all closed trades, newest first.
    Optionally filter by market type.
    """
    try:
        query = db.query(Trade).filter(Trade.status == TradeStatus.CLOSED)

        # Optional market filter
        if market_type:
            try:
                market_enum = MarketType(market_type.lower())
                query = query.filter(Trade.market_type == market_enum)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid market_type '{market_type}'. Use: crypto, stock, forex"
                )

        total  = query.count()
        trades = query.order_by(desc(Trade.closed_at)).offset(skip).limit(limit).all()

        return {
            "total":  total,
            "skip":   skip,
            "limit":  limit,
            "trades": [_format_trade(t) for t in trades]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"get_trade_history error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ─── Get Single Trade ─────────────────────────────────────────────────────────

@router.get("/{trade_id}")
def get_trade(trade_id: int, db: Session = Depends(get_db)):
    """Get a single trade by its ID."""
    trade = db.query(Trade).filter(Trade.id == trade_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found")
    return _format_trade(trade)

# ─── Get Trades By Market ─────────────────────────────────────────────────────

@router.get("/market/{market_type}")
def get_trades_by_market(
    market_type: str,
    db:          Session = Depends(get_db),
    limit:       int     = Query(default=50, le=500)
):
    """
    Get all trades for a specific market.
    market_type must be: crypto, stock, or forex
    """
    try:
        market_enum = MarketType(market_type.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid market '{market_type}'. Must be: crypto, stock, forex"
        )

    trades = (
        db.query(Trade)
        .filter(Trade.market_type == market_enum)
        .order_by(desc(Trade.opened_at))
        .limit(limit)
        .all()
    )

    return {
        "market": market_type,
        "count":  len(trades),
        "trades": [_format_trade(t) for t in trades]
    }

# ─── Get Trade Stats ──────────────────────────────────────────────────────────

@router.get("/stats/summary")
def get_trade_stats(db: Session = Depends(get_db)):
    """
    Get a full summary of trading performance.
    Used by the dashboard to show stats cards.
    """
    try:
        all_closed = db.query(Trade).filter(Trade.status == TradeStatus.CLOSED).all()
        all_open   = db.query(Trade).filter(Trade.status == TradeStatus.OPEN).all()

        total_closed = len(all_closed)
        total_open   = len(all_open)

        winning = [t for t in all_closed if t.pnl and t.pnl > 0]
        losing  = [t for t in all_closed if t.pnl and t.pnl < 0]

        total_pnl     = sum(t.pnl for t in all_closed if t.pnl) or 0.0
        best_trade    = max(all_closed, key=lambda t: t.pnl or 0, default=None)
        worst_trade   = min(all_closed, key=lambda t: t.pnl or 0, default=None)
        avg_pnl       = (total_pnl / total_closed) if total_closed > 0 else 0.0
        win_rate      = (len(winning) / total_closed * 100) if total_closed > 0 else 0.0

        # Breakdown by market
        crypto_trades = [t for t in all_closed if t.market_type == MarketType.CRYPTO]
        stock_trades  = [t for t in all_closed if t.market_type == MarketType.STOCK]
        forex_trades  = [t for t in all_closed if t.market_type == MarketType.FOREX]

        return {
            "total_trades":    total_closed,
            "open_positions":  total_open,
            "winning_trades":  len(winning),
            "losing_trades":   len(losing),
            "win_rate":        round(win_rate, 2),
            "total_pnl":       round(total_pnl, 2),
            "average_pnl":     round(avg_pnl, 2),
            "best_trade": {
                "symbol": best_trade.symbol,
                "pnl":    round(best_trade.pnl, 2)
            } if best_trade and best_trade.pnl else None,
            "worst_trade": {
                "symbol": worst_trade.symbol,
                "pnl":    round(worst_trade.pnl, 2)
            } if worst_trade and worst_trade.pnl else None,
            "by_market": {
                "crypto": {
                    "trades": len(crypto_trades),
                    "pnl":    round(sum(t.pnl for t in crypto_trades if t.pnl), 2)
                },
                "stocks": {
                    "trades": len(stock_trades),
                    "pnl":    round(sum(t.pnl for t in stock_trades if t.pnl), 2)
                },
                "forex": {
                    "trades": len(forex_trades),
                    "pnl":    round(sum(t.pnl for t in forex_trades if t.pnl), 2)
                }
            }
        }
    except Exception as e:
        logger.error(f"get_trade_stats error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ─── Cancel / Close a Trade Manually ─────────────────────────────────────────

@router.post("/{trade_id}/close")
def manually_close_trade(trade_id: int, db: Session = Depends(get_db)):
    """
    Manually close/cancel an open trade.
    Useful for emergency exits from the dashboard.
    """
    trade = db.query(Trade).filter(Trade.id == trade_id).first()

    if not trade:
        raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found")

    if trade.status != TradeStatus.OPEN:
        raise HTTPException(
            status_code=400,
            detail=f"Trade {trade_id} is already {trade.status.value}"
        )

    try:
        trade.status    = TradeStatus.CANCELLED
        trade.closed_at = datetime.utcnow()
        db.commit()

        logger.info(f"Trade {trade_id} manually cancelled")
        return {"message": f"Trade {trade_id} cancelled successfully"}

    except Exception as e:
        db.rollback()
        logger.error(f"manually_close_trade error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ─── Format Helper ────────────────────────────────────────────────────────────

def _format_trade(trade: Trade) -> dict:
    """
    Converts a Trade DB object to a clean dictionary for the API response.
    Handles None values safely so the frontend never crashes.
    """
    return {
        "id":           trade.id,
        "symbol":       trade.symbol,
        "market_type":  trade.market_type.value  if trade.market_type  else None,
        "broker":       trade.broker.value        if trade.broker       else None,
        "side":         trade.side,
        "quantity":     trade.quantity,
        "entry_price":  trade.entry_price,
        "exit_price":   trade.exit_price,
        "stop_loss":    trade.stop_loss,
        "take_profit":  trade.take_profit,
        "status":       trade.status.value        if trade.status       else None,
        "strategy":     trade.strategy,
        "reason":       trade.reason,
        "pnl":          round(trade.pnl, 4)        if trade.pnl          else None,
        "pnl_pct":      round(trade.pnl_pct, 2)    if trade.pnl_pct      else None,
        "opened_at":    trade.opened_at.isoformat() if trade.opened_at   else None,
        "closed_at":    trade.closed_at.isoformat() if trade.closed_at   else None,
    }