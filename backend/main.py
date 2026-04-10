# backend/main.py
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from database import get_db, engine
from models import Base, MarketType, BrokerName
from agents.base_agent import TradingAgent
from brokers.alpaca_broker import AlpacaBroker
from brokers.binance_broker import BinanceBroker
from brokers.alphavantage_broker import ForexBroker
import routers.trades as trades_router
import routers.portfolio as portfolio_router
import routers.settings as settings_router

# ─── Logging Setup ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# ─── Symbols To Trade ─────────────────────────────────────────────────────────

CRYPTO_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]   # Binance Testnet

STOCK_SYMBOLS  = ["AAPL", "TSLA", "NVDA", "MSFT", "AMZN"]       # Alpaca Paper

FOREX_PAIRS    = [                                                # Alpha Vantage
    ("EUR", "USD"),
    ("GBP", "USD"),
    ("USD", "JPY"),
    ("AUD", "USD"),
]

# ─── Scheduler ────────────────────────────────────────────────────────────────
scheduler = AsyncIOScheduler()

# ─── App Lifespan (startup + shutdown) ────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs on startup and shutdown.
    Replaces the deprecated @app.on_event("startup") pattern.
    """

    # ── Create all database tables if they don't exist ────────────────────────
    logger.info("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables ready ✅")

    # ── Initialize brokers ────────────────────────────────────────────────────
    logger.info("Initializing brokers...")
    binance = BinanceBroker()    # Crypto  — Binance Testnet (fake money)
    alpaca  = AlpacaBroker()     # Stocks  — Alpaca Paper (fake money)
    forex   = ForexBroker()      # Forex   — Alpha Vantage + simulated (fake money)

    # ── Check broker connections ──────────────────────────────────────────────
    if binance.is_connected():
        logger.info("Binance Testnet connected ✅")
    else:
        logger.warning("Binance Testnet connection failed ⚠️ — check your API keys in .env")

    if alpaca.is_connected():
        logger.info("Alpaca Paper connected ✅")
    else:
        logger.warning("Alpaca Paper connection failed ⚠️ — check your API keys in .env")

    # ── Initialize trading agents ─────────────────────────────────────────────
    logger.info("Initializing trading agents...")

    crypto_agent = TradingAgent(
        broker      = binance,
        market_type = MarketType.CRYPTO,
        broker_name = BrokerName.BINANCE,
        strategy    = "combined"    # RSI + MACD + Bollinger Bands
    )

    stock_agent = TradingAgent(
        broker      = alpaca,
        market_type = MarketType.STOCK,
        broker_name = BrokerName.ALPACA,
        strategy    = "combined"
    )

    forex_agent = TradingAgent(
        broker      = forex,
        market_type = MarketType.FOREX,
        broker_name = BrokerName.ALPHAVANTAGE,
        strategy    = "combined"
    )

    # ── Get a DB session for the agents ───────────────────────────────────────
    db = next(get_db())

    # ── Forex helper — flattens pairs to symbol strings for the agent ─────────
    async def run_forex_cycle():
        forex_symbols = [f"{base}{quote}" for base, quote in FOREX_PAIRS]
        await forex_agent.run_cycle(forex_symbols, db)

    # ── Schedule agent cycles ─────────────────────────────────────────────────
    scheduler.add_job(
        lambda: crypto_agent.run_cycle(CRYPTO_SYMBOLS, db),
        trigger  = "interval",
        hours    = 1,
        id       = "crypto_cycle",
        name     = "Crypto Trading Cycle (Binance Testnet)"
    )

    scheduler.add_job(
        lambda: stock_agent.run_cycle(STOCK_SYMBOLS, db),
        trigger  = "interval",
        hours    = 1,
        id       = "stock_cycle",
        name     = "Stock Trading Cycle (Alpaca Paper)"
    )

    scheduler.add_job(
        run_forex_cycle,
        trigger  = "interval",
        hours    = 4,      # Forex moves slower — check every 4 hours
        id       = "forex_cycle",
        name     = "Forex Trading Cycle (Alpha Vantage)"
    )

    scheduler.start()
    logger.info("Scheduler started ✅ — agents running every hour")
    logger.info("🤖 Autonomous Trading Bot is LIVE (paper trading only)")

    yield   # ← app runs here

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("Shutting down scheduler...")
    scheduler.shutdown()
    logger.info("Bot stopped 🛑")

# ─── FastAPI App ──────────────────────────────────────────────────────────────
app = FastAPI(
    title       = "Autonomous Trading Bot API",
    description = "Paper trading bot for Crypto, Stocks & Forex",
    version     = "2.0.0",
    lifespan    = lifespan
)

# ─── CORS — allows the React frontend to talk to this API ─────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins  = ["*"],   # in production, replace * with your frontend URL
    allow_methods  = ["*"],
    allow_headers  = ["*"],
)

# ─── Routers ──────────────────────────────────────────────────────────────────
app.include_router(trades_router.router,    prefix="/api/trades",    tags=["Trades"])
app.include_router(portfolio_router.router, prefix="/api/portfolio", tags=["Portfolio"])
app.include_router(settings_router.router,  prefix="/api/settings",  tags=["Settings"])

# ─── Base Routes ──────────────────────────────────────────────────────────────

@app.get("/", tags=["Health"])
def root():
    return {
        "status":  "Autonomous Trading Bot running",
        "version": "2.0.0",
        "markets": {
            "crypto": "Binance Testnet (fake money)",
            "stocks": "Alpaca Paper (fake money)",
            "forex":  "Alpha Vantage + simulated (fake money)"
        },
        "docs": "/docs"   # Swagger UI auto-generated at this URL
    }

@app.get("/api/health", tags=["Health"])
def health():
    """Check if the API is running."""
    return {"status": "ok"}

@app.get("/api/scheduler", tags=["Health"])
def scheduler_status():
    """Check what scheduled jobs are running."""
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id":       job.id,
            "name":     job.name,
            "next_run": str(job.next_run_time)
        })
    return {
        "scheduler_running": scheduler.running,
        "jobs": jobs
    }