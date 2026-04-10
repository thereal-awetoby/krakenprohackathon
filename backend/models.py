# backend/models.py
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Enum
from sqlalchemy.orm import declarative_base
from datetime import datetime
import enum

Base = declarative_base()

# ─── Enums ────────────────────────────────────────────────────────────────────

class MarketType(enum.Enum):
    CRYPTO = "crypto"
    STOCK  = "stock"
    FOREX  = "forex"

class TradeStatus(enum.Enum):
    OPEN      = "open"
    CLOSED    = "closed"
    CANCELLED = "cancelled"

class BrokerName(enum.Enum):
    BINANCE      = "binance"
    ALPACA       = "alpaca"
    ALPHAVANTAGE = "alphavantage"

# ─── Trade Model ──────────────────────────────────────────────────────────────

class Trade(Base):
    __tablename__ = "trades"

    id           = Column(Integer, primary_key=True, index=True)
    symbol       = Column(String,  nullable=False)
    market_type  = Column(Enum(MarketType), nullable=False)
    broker       = Column(Enum(BrokerName), nullable=True)

    side         = Column(String, nullable=False)
    quantity     = Column(Float,  nullable=False)
    entry_price  = Column(Float,  nullable=False)
    exit_price   = Column(Float,  nullable=True)

    stop_loss    = Column(Float,  nullable=True)
    take_profit  = Column(Float,  nullable=True)

    status       = Column(Enum(TradeStatus), default=TradeStatus.OPEN)
    strategy     = Column(String, nullable=True)
    reason       = Column(String, nullable=True)

    pnl          = Column(Float,  nullable=True)
    pnl_pct      = Column(Float,  nullable=True)

    opened_at    = Column(DateTime, default=datetime.utcnow)
    closed_at    = Column(DateTime, nullable=True)

# ─── Portfolio Model ──────────────────────────────────────────────────────────

class Portfolio(Base):
    __tablename__ = "portfolio"

    id              = Column(Integer, primary_key=True, index=True)
    initial_balance = Column(Float,   default=100000.0)
    balance         = Column(Float,   default=100000.0)

    total_pnl      = Column(Float,   default=0.0)
    total_trades   = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades  = Column(Integer, default=0)

    crypto_pnl     = Column(Float, default=0.0)
    stock_pnl      = Column(Float, default=0.0)
    forex_pnl      = Column(Float, default=0.0)

    updated_at     = Column(DateTime, default=datetime.utcnow)

# ─── Bot Settings Model ───────────────────────────────────────────────────────

class BotSettings(Base):
    __tablename__ = "bot_settings"

    id                   = Column(Integer, primary_key=True, index=True)
    is_running           = Column(Boolean, default=False)

    max_risk_per_trade   = Column(Float,   default=2.0)
    max_open_trades      = Column(Integer, default=5)

    trade_crypto         = Column(Boolean, default=True)
    trade_stocks         = Column(Boolean, default=True)
    trade_forex          = Column(Boolean, default=True)

    strategy             = Column(String,  default="rsi")
    run_interval_minutes = Column(Integer, default=60)
    last_run             = Column(DateTime, nullable=True)

    created_at           = Column(DateTime, default=datetime.utcnow)