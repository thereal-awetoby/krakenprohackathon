from dotenv import load_dotenv
from pathlib import Path
load_dotenv(dotenv_path=Path(__file__).parent / ".env")

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from database import SessionLocal, engine
from models import Base, MarketType
from Agent.base_agent import HybridTradingAgent
from Brokers.Alphacotrader import AlpacaBroker
from Brokers.Bybit import BybitBroker
from Strategies.rsi_strategies import get_triple_confirmation_signal
from Strategies.ai_strategy import get_hybrid_ai_signal
import Routers.traders as trades_router
import Routers.portfolio as portfolio_router
import Routers.setting as settings_router
import asyncio
import httpx

app = FastAPI(title="Autonomous Hybrid AI Trading Bot")

# 1. CORS for your React Dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. Database Initialization
Base.metadata.create_all(bind=engine)

# 3. Router Integration
app.include_router(trades_router.router, prefix="/api/trades")
app.include_router(portfolio_router.router, prefix="/api/portfolio")
app.include_router(settings_router.router, prefix="/api/settings")

# 4. Scheduling Logic
scheduler = AsyncIOScheduler()

CRYPTO_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT",
]
STOCK_SYMBOLS  = ["AAPL", "TSLA", "NVDA", "MSFT"]

async def run_hybrid_cycles():
    db = SessionLocal()
    try:
        crypto_broker = BybitBroker()
        alpaca        = AlpacaBroker()
        crypto_agent  = HybridTradingAgent(crypto_broker, MarketType.CRYPTO)
        stock_agent   = HybridTradingAgent(alpaca, MarketType.STOCK)
        await crypto_agent.run_cycle(CRYPTO_SYMBOLS, db)
        await stock_agent.run_cycle(STOCK_SYMBOLS, db)
    finally:
        db.close()


def run_trade_monitor():
    """
    Runs every minute. Checks every open trade against live prices.
    Closes trades automatically when TP or SL is hit and credits balance back.
    Separate from the hourly analysis cycle so trade closure is near real-time.
    """
    db = SessionLocal()
    try:
        crypto_broker = BybitBroker()
        crypto_agent  = HybridTradingAgent(crypto_broker, MarketType.CRYPTO)
        crypto_agent.monitor_open_trades(db)
    finally:
        db.close()

@app.on_event("startup")
async def start_scheduler():
    import os
    google_key = os.getenv("GOOGLE_API_KEY")
    if google_key:
        print(f"✅ GOOGLE_API_KEY loaded ({google_key[:8]}...)")
    else:
        print("❌ GOOGLE_API_KEY NOT FOUND — check your .env path")

    # Hourly: run full analysis cycle and place new trades
    scheduler.add_job(run_hybrid_cycles, "interval", hours=1, id="main_hybrid_cycle")

    # Every 10 seconds: check open trades against live prices, close on TP/SL hit
    # 10s gives near real-time closure with minimal API load
    scheduler.add_job(run_trade_monitor, "interval", seconds=10, id="trade_monitor")

    scheduler.start()
    print("✅ Scheduler started — analysis every 1h, trade monitor every 1min")

@app.get("/")
def root():
    return {"status": "Hybrid AI Bot Active", "logic": "TripleConfirmation + MonteCarlo + GPT-4o"}

@app.get("/api/health")
def health():
    return {"status": "ok"}


# ─── DEBUG: Manually trigger monitor + see what it finds ─────────────────────
# Call this from browser: http://127.0.0.1:8000/api/monitor/run
@app.get("/api/monitor/run")
def trigger_monitor():
    """
    Manually fires the trade monitor and returns a full diagnostic report.
    Use this to debug why trades aren't closing.
    """
    db = SessionLocal()
    try:
        from models import Trade, Portfolio, TradeStatus
        from sqlalchemy import or_

        # Fetch ALL trades regardless of status to see what's in DB
        all_trades = db.query(Trade).all()
        open_trades = [t for t in all_trades if t.status == TradeStatus.OPEN]

        report = {
            "total_trades":     len(all_trades),
            "open_trades":      len(open_trades),
            "trades": []
        }

        broker = BybitBroker()

        for trade in open_trades:
            live_price = broker.get_current_price(trade.symbol)
            tp_hit = trade.take_profit and live_price >= trade.take_profit if trade.side == 'buy' else (trade.take_profit and live_price <= trade.take_profit)
            sl_hit = trade.stop_loss  and live_price <= trade.stop_loss  if trade.side == 'buy' else (trade.stop_loss  and live_price >= trade.stop_loss)

            report["trades"].append({
                "id":          trade.id,
                "symbol":      trade.symbol,
                "side":        trade.side,
                "status":      str(trade.status),
                "entry":       trade.entry_price,
                "take_profit": trade.take_profit,
                "stop_loss":   trade.stop_loss,
                "live_price":  live_price,
                "tp_hit":      bool(tp_hit),
                "sl_hit":      bool(sl_hit),
                "notional":    getattr(trade, 'notional', None) or round((trade.entry_price or 0) * (trade.quantity or 0), 2),
            })

        # Now actually run the monitor
        crypto_broker = BybitBroker()
        crypto_agent  = HybridTradingAgent(crypto_broker, MarketType.CRYPTO)
        crypto_agent.monitor_open_trades(db)

        report["monitor_ran"] = True
        return report

    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}
    finally:
        db.close()

# ─── On-demand Analysis Endpoint ─────────────────────────────────────────────
# The frontend calls this BEFORE placing any order.
# Accepts an optional `interval` param so the user can switch timeframes
# from the UI (1m / 15m / 1h / 4h / 1D) without touching backend code.
#
# Recommended interval: "60" (1-hour candles).
# "1" (1-minute) will produce low MC scores due to tiny per-candle sigma.
@app.get("/api/analyse")
async def analyse_symbol(
    symbol:   str = Query(...,  description="Bybit symbol e.g. BTCUSDT"),
    interval: str = Query("60", description="Candle interval: 1 | 15 | 60 | 240 | D")
):
    # Whitelist of intervals Bybit accepts for linear perpetuals
    VALID_INTERVALS = {"1", "3", "5", "15", "30", "60", "120", "240", "360", "720", "D", "W", "M"}
    if interval not in VALID_INTERVALS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid interval '{interval}'. Must be one of: {sorted(VALID_INTERVALS)}"
        )

    try:
        broker = BybitBroker()

        # Fetch candles using the frontend-selected timeframe
        prices = broker.get_price_history(symbol, interval=interval, limit=200)

        if not prices or len(prices) < 30:
            raise HTTPException(
                status_code=422,
                detail=f"Not enough candles for {symbol} at interval={interval} — got {len(prices)}, need 30+"
            )

        # Step 1: Math Engine (RSI + MACD + Bollinger + Slope)
        math_signal = get_triple_confirmation_signal(prices)

        # Step 2: Stats Engine (Monte Carlo) + optional Gemini AI
        final_signal = await get_hybrid_ai_signal(
            symbol=symbol,
            prices=prices,
            market_type="crypto",
            triple_conf=math_signal,
            interval=interval
        )

        # Guarantee all keys exist so the frontend never crashes
        final_signal.setdefault("suggested_tp_pct", 2.0)
        final_signal.setdefault("suggested_sl_pct", 1.0)
        final_signal.setdefault("mc_probability",   0.0)

        # Echo the price used so frontend can compute TP/SL dollar values
        # without a separate price fetch
        final_signal["current_price"] = prices[-1]
        final_signal["math_signal"]   = math_signal
        final_signal["interval"]      = interval

        return final_signal

    except HTTPException:
        raise
    except Exception as e:
        return {
            "action":           "hold",
            "reason":           f"Analysis error: {str(e)}",
            "confidence":       0.0,
            "mc_probability":   0.0,
            "suggested_tp_pct": 2.0,
            "suggested_sl_pct": 1.0,
            "current_price":    0.0,
            "math_signal":      {},
            "interval":         interval
        }


# ─── Price endpoint — fallback for frontend TP/SL calculation ────────────────
@app.get("/api/price")
async def get_price(symbol: str = Query(..., description="e.g. BTCUSDT")):
    """Simple price fetch used by frontend when activeInstrument is unavailable."""
    try:
        broker = BybitBroker()
        price  = broker.get_current_price(symbol)
        if price == 0:
            raise HTTPException(status_code=503, detail="Price unavailable")
        return {"symbol": symbol, "price": price}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ─── Live News Endpoint ──────────────────────────────────────────────────────
# Uses rss2json.com to convert RSS → JSON. No API key needed.
# asyncio imported at top level to avoid event loop conflicts with FastAPI.
@app.get("/api/news")
async def get_market_news():
    import re as _re
    import datetime as _dt
    import urllib.parse
    from datetime import timezone

    FEEDS = [
        {"url": "https://www.coindesk.com/arc/outboundfeeds/rss/",   "tag": "Crypto",  "source": "CoinDesk"},
        {"url": "https://cointelegraph.com/rss",                      "tag": "Crypto",  "source": "CoinTelegraph"},
        {"url": "https://decrypt.co/feed",                            "tag": "Crypto",  "source": "Decrypt"},
        {"url": "https://www.forexlive.com/feed/news",                "tag": "Forex",   "source": "ForexLive"},
        {"url": "https://www.marketwatch.com/rss/topstories",         "tag": "Stocks",  "source": "MarketWatch"},
        {"url": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC&region=US&lang=en-US", "tag": "Stocks", "source": "Yahoo Finance"},
        {"url": "https://feeds.bbci.co.uk/news/business/rss.xml",     "tag": "Macro",   "source": "BBC Business"},
        {"url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664", "tag": "Macro", "source": "CNBC Markets"},
    ]

    BULL = {"surge","rally","rise","gain","high","bull","soar","jump","record","recover","boost","grow","climb"}
    BEAR = {"drop","fall","crash","slump","low","bear","sink","decline","loss","fear","sell","plunge","warn","tumble"}

    def sentiment(text):
        w = set(text.lower().split())
        return "bullish" if len(w&BULL)>len(w&BEAR) else "bearish" if len(w&BEAR)>len(w&BULL) else "neutral"

    def parse_age(pub):
        try:
            dt   = _dt.datetime.strptime(pub[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            diff = int((_dt.datetime.now(timezone.utc) - dt).total_seconds())
            if diff < 3600:  return f"{max(1,diff//60)}m ago"
            if diff < 86400: return f"{diff//3600}h ago"
            return f"{diff//86400}d ago"
        except:
            return "recently"

    def clean(text):
        return _re.sub(r"<[^>]+>", "", text or "").strip()

    BASE = "https://api.rss2json.com/v1/api.json?rss_url="

    articles = []

    # Sequential fetches — avoids any asyncio.gather issues inside FastAPI
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        for feed in FEEDS:
            try:
                encoded = urllib.parse.quote(feed["url"], safe="")
                r = await client.get(f"{BASE}{encoded}")
                if r.status_code != 200:
                    continue
                data = r.json()
                if data.get("status") != "ok":
                    continue
                for item in data.get("items", [])[:2]:
                    title = clean(item.get("title", ""))
                    desc  = clean(item.get("description", ""))[:140]
                    pub   = item.get("pubDate", "")
                    if not title:
                        continue
                    articles.append({
                        "title":     title,
                        "tag":       feed["tag"],
                        "source":    feed["source"],
                        "time":      parse_age(pub),
                        "summary":   desc if desc != title else "",
                        "sentiment": sentiment(title + " " + desc),
                    })
            except Exception as e:
                print(f"[News] {feed['source']} error: {e}")
                continue

    if not articles:
        raise HTTPException(status_code=503, detail="All RSS feeds unavailable — check network connectivity")

    # Sort freshest first
    def age_minutes(a):
        t = a["time"]
        try:
            if "m ago" in t: return int(t.replace("m ago","").strip())
            if "h ago" in t: return int(t.replace("h ago","").strip()) * 60
        except: pass
        return 99999

    articles.sort(key=age_minutes)
    return articles[:12]
# ─── Alpaca: Stock Price ──────────────────────────────────────────────────────
# GET /api/stock/price?symbol=AAPL
# Returns live price + 24h change using Alpaca paper trading credentials
@app.get("/api/stock/price")
async def get_stock_price(symbol: str = Query(..., description="e.g. AAPL")):
    try:
        from Brokers.Alphacotrader import AlpacaBroker
        broker = AlpacaBroker()
        broker._check()
        price = broker.get_latest_price(symbol.upper())
        if price == 0:
            raise HTTPException(status_code=503, detail=f"No price for {symbol}")

        # Get previous close for change %
        try:
            history    = broker.get_price_history(symbol.upper(), limit=2, timeframe="1Day")
            prev_close = history[-2] if len(history) >= 2 else price
            change_pct = ((price - prev_close) / prev_close) * 100
        except:
            change_pct = 0.0

        return {
            "symbol":     symbol.upper(),
            "price":      price,
            "change_pct": round(change_pct, 2),
            "type":       "stock"
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Alpaca price error: {str(e)}")


# ─── Alpaca: Stock Candles ────────────────────────────────────────────────────
# GET /api/stock/candles?symbol=AAPL&interval=1h
# Returns [{time, open, high, low, close}] in chronological order
# interval: 1m | 5m | 15m | 1h | 4h | 1d
@app.get("/api/stock/candles")
async def get_stock_candles(
    symbol:   str = Query(..., description="e.g. AAPL"),
    interval: str = Query("1h",  description="1m|5m|15m|1h|4h|1d"),
    limit:    int = Query(100,   description="Number of bars")
):
    # Map frontend interval labels to Alpaca timeframe strings
    INTERVAL_MAP = {
        "1m": "1Min", "5m": "5Min", "15m": "15Min",
        "1h": "1Hour", "4h": "4Hour", "1d": "1Day",
        # Also accept the Bybit-style values from the interval selector
        "1": "1Min", "15": "15Min", "60": "1Hour", "240": "4Hour", "D": "1Day"
    }
    tf = INTERVAL_MAP.get(interval, "1Hour")

    try:
        from Brokers.Alphacotrader import AlpacaBroker
        broker = AlpacaBroker()
        broker._check()
        bars   = broker.api.get_bars(symbol, tf, limit=limit).df

        if bars.empty:
            raise HTTPException(status_code=503, detail=f"No bars returned for {symbol}")

        candles = []
        for ts, row in bars.iterrows():
            try:
                # ts is a pandas Timestamp — convert to unix int
                unix = int(ts.timestamp())
                candles.append({
                    "time":  unix,
                    "open":  float(row["open"]),
                    "high":  float(row["high"]),
                    "low":   float(row["low"]),
                    "close": float(row["close"]),
                })
            except Exception:
                continue

        return candles   # already chronological from Alpaca

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Alpaca candles error: {str(e)}")


# ─── Alpaca: Multiple Stock Prices (sidebar batch) ───────────────────────────
# GET /api/stock/prices?symbols=AAPL,TSLA,NVDA
@app.get("/api/stock/prices")
async def get_stock_prices(symbols: str = Query(..., description="Comma-separated symbols")):
    try:
        from Brokers.Alphacotrader import AlpacaBroker
        broker      = AlpacaBroker()
        symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        result      = {}

        for symbol in symbol_list:
            try:
                price = broker.get_latest_price(symbol)
                try:
                    history    = broker.get_price_history(symbol, limit=2, timeframe="1Day")
                    prev_close = history[-2] if len(history) >= 2 else price
                    change_pct = round(((price - prev_close) / prev_close) * 100, 2)
                except:
                    change_pct = 0.0
                result[symbol] = {"price": price, "change_pct": change_pct}
            except Exception as e:
                result[symbol] = {"price": 0, "change_pct": 0, "error": str(e)}

        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Stock Analysis Endpoint ─────────────────────────────────────────────────
@app.get("/api/stock/analyse")
async def analyse_stock(
    symbol:   str = Query(..., description="e.g. AAPL"),
    interval: str = Query("60", description="1|15|60|240|D")
):
    from Strategies.rsi_strategies import get_triple_confirmation_signal
    from Strategies.ai_strategy import get_hybrid_ai_signal

    INTERVAL_MAP = {
        "1m":"1Min","5m":"5Min","15m":"15Min","1h":"1Hour","4h":"4Hour","1d":"1Day",
        "1":"1Min","15":"15Min","60":"1Hour","240":"4Hour","D":"1Day"
    }
    tf = INTERVAL_MAP.get(interval, "1Hour")

    try:
        from Brokers.Alphacotrader import AlpacaBroker
        broker = AlpacaBroker()
        broker._check()  # raises clearly if not connected

        prices = broker.get_price_history(symbol.upper(), limit=200, timeframe=tf)

        if len(prices) < 30:
            raise HTTPException(
                status_code=422,
                detail=f"Not enough bars for {symbol} at {tf} — got {len(prices)}, need 30+. "
                       f"Check ALPACA_BASE_URL has no inline comments in .env"
            )

        math_signal  = get_triple_confirmation_signal(prices)
        final_signal = await get_hybrid_ai_signal(
            symbol=symbol, prices=prices,
            market_type="stock", triple_conf=math_signal, interval=interval
        )

        final_signal.setdefault("suggested_tp_pct", 2.0)
        final_signal.setdefault("suggested_sl_pct", 1.0)
        final_signal.setdefault("mc_probability",   0.0)

        current_price = broker.get_latest_price(symbol.upper()) or prices[-1]
        final_signal["current_price"] = current_price
        final_signal["math_signal"]   = math_signal
        final_signal["interval"]      = interval
        final_signal["market_type"]   = "stock"
        return final_signal

    except HTTPException:
        raise
    except Exception as e:
        return {
            "action": "hold",
            "reason": f"Stock analysis error: {str(e)}",
            "confidence": 0.0, "mc_probability": 0.0,
            "suggested_tp_pct": 2.0, "suggested_sl_pct": 1.0,
            "current_price": 0.0, "math_signal": {}, "interval": interval, "market_type": "stock"
        }



# ─── Live Instruments Endpoint ───────────────────────────────────────────────
@app.get("/api/instruments")
async def get_instruments():
    url = "https://api.bytick.com/v5/market/tickers?category=linear"

    # Top liquid crypto pairs — MATIC renamed to POL on Bybit
    SYMBOLS_TO_TRACK = {
        "BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","DOGEUSDT",
        "ADAUSDT","AVAXUSDT","DOTUSDT","POLUSDT","LINKUSDT","UNIUSDT",
        "LTCUSDT","ATOMUSDT","NEARUSDT","APTUSDT","ARBUSDT","OPUSDT",
        "INJUSDT","SUIUSDT","TONUSDT","FETUSDT","RENDERUSDT","WLDUSDT",
    }

    try:
        async with httpx.AsyncClient(timeout=8.0, trust_env=False) as client:
            response = await client.get(url)

        if response.status_code != 200:
            raise Exception(f"Bybit returned {response.status_code}")

        data        = response.json()
        all_tickers = data.get("result", {}).get("list", [])

        filtered = []
        for item in all_tickers:
            symbol = item.get("symbol", "")
            if symbol not in SYMBOLS_TO_TRACK:
                continue
            try:
                last_price = float(item.get("lastPrice", 0) or 0)
                change_pct = float(item.get("price24hPcnt", 0) or 0) * 100
                volume     = float(item.get("volume24h", 0) or 0)
                filtered.append({
                    "pair":     symbol.replace("USDT", "/USDT"),
                    "symbol":   symbol,
                    "price":    f"{last_price:,.2f}",
                    "change":   f"{change_pct:+.2f}%",
                    "vol":      f"{volume/1_000_000:.1f}M" if volume >= 1_000_000 else f"{volume/1000:.1f}K",
                    "momentum": "Strong Buy" if change_pct > 1 else "Buy" if change_pct > 0 else "Sell" if change_pct < -1 else "Neutral"
                })
            except Exception:
                continue

        # Sort by volume descending
        filtered.sort(key=lambda x: float(x["vol"].replace("M","000").replace("K","").replace(",","")), reverse=True)
        return filtered

    except Exception as e:
        print(f"[Instruments] Error: {e}")
        return []