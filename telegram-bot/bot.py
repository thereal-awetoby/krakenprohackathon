# telegram-bot/bot.py
import os
import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)
from dotenv import load_dotenv

load_dotenv()

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level  = logging.INFO,
    format = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────
API_BASE  = os.getenv("API_BASE_URL", "http://localhost:8000/api")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN not set in .env file")

# ─── API Helpers ──────────────────────────────────────────────────────────────

def api_get(endpoint: str) -> dict:
    """Make a GET request to the trading bot API."""
    try:
        r = requests.get(f"{API_BASE}{endpoint}", timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        logger.error(f"Cannot connect to API at {API_BASE}")
        return {"error": "Cannot connect to trading bot API. Is it running?"}
    except Exception as e:
        logger.error(f"api_get error on {endpoint}: {e}")
        return {"error": str(e)}

def api_post(endpoint: str, data: dict = None) -> dict:
    """Make a POST request to the trading bot API."""
    try:
        r = requests.post(f"{API_BASE}{endpoint}", json=data, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        return {"error": "Cannot connect to trading bot API. Is it running?"}
    except Exception as e:
        logger.error(f"api_post error on {endpoint}: {e}")
        return {"error": str(e)}

# ─── Keyboard Layouts ─────────────────────────────────────────────────────────

def main_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💼 Portfolio",     callback_data="portfolio"),
            InlineKeyboardButton("📈 Open Trades",   callback_data="open_trades")
        ],
        [
            InlineKeyboardButton("📜 History",       callback_data="history"),
            InlineKeyboardButton("📊 Stats",         callback_data="stats")
        ],
        [
            InlineKeyboardButton("⚙️ Settings",      callback_data="settings"),
            InlineKeyboardButton("🌍 Markets",       callback_data="markets")
        ],
        [
            InlineKeyboardButton("▶️ Start Bot",     callback_data="start_bot"),
            InlineKeyboardButton("⏸ Stop Bot",       callback_data="stop_bot")
        ],
        [
            InlineKeyboardButton("🔄 Refresh",       callback_data="refresh"),
            InlineKeyboardButton("🏠 Main Menu",     callback_data="main_menu")
        ]
    ])

def strategy_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 RSI",           callback_data="strategy_rsi"),
            InlineKeyboardButton("📉 MACD",          callback_data="strategy_macd")
        ],
        [
            InlineKeyboardButton("🔀 Combined",      callback_data="strategy_combined"),
            InlineKeyboardButton("🤖 AI (GPT)",      callback_data="strategy_ai")
        ],
        [
            InlineKeyboardButton("🔙 Back",          callback_data="settings")
        ]
    ])

def markets_keyboard(settings: dict):
    """Keyboard showing current market on/off states."""
    crypto_icon = "✅" if settings.get("trade_crypto") else "❌"
    stocks_icon = "✅" if settings.get("trade_stocks") else "❌"
    forex_icon  = "✅" if settings.get("trade_forex")  else "❌"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{crypto_icon} Crypto (Binance Testnet)",  callback_data="toggle_crypto")],
        [InlineKeyboardButton(f"{stocks_icon} Stocks (Alpaca Paper)",     callback_data="toggle_stocks")],
        [InlineKeyboardButton(f"{forex_icon}  Forex  (Alpha Vantage)",    callback_data="toggle_forex")],
        [InlineKeyboardButton("🔙 Back",                                  callback_data="main_menu")]
    ])

# ─── Format Helpers ───────────────────────────────────────────────────────────

def format_portfolio(pf: dict) -> str:
    if "error" in pf:
        return f"❌ Error: {pf['error']}"

    by_market = pf.get("by_market", {})
    return (
        f"💼 *Portfolio Summary*\n"
        f"{'─' * 28}\n"
        f"💰 Balance:        `${pf.get('balance', 0):>12,.2f}`\n"
        f"📈 Total P&L:      `${pf.get('total_pnl', 0):>12,.2f}`\n"
        f"📊 Return:         `{pf.get('return_pct', 0):>11.2f}%`\n"
        f"🏆 Win Rate:       `{pf.get('win_rate', 0):>11.1f}%`\n"
        f"🔢 Total Trades:   `{pf.get('total_trades', 0):>12}`\n"
        f"📂 Open Positions: `{pf.get('open_positions', 0):>12}`\n"
        f"{'─' * 28}\n"
        f"*By Market:*\n"
        f"  🪙 Crypto: `${by_market.get('crypto', 0):,.2f}`\n"
        f"  📋 Stocks: `${by_market.get('stocks', 0):,.2f}`\n"
        f"  💱 Forex:  `${by_market.get('forex',  0):,.2f}`"
    )

def format_settings(s: dict) -> str:
    if "error" in s:
        return f"❌ Error: {s['error']}"

    status   = "▶️ Running" if s.get("is_running") else "⏸ Stopped"
    last_run = s.get("last_run", "Never") or "Never"
    if last_run != "Never":
        last_run = last_run[:16].replace("T", " ")

    return (
        f"⚙️ *Bot Settings*\n"
        f"{'─' * 28}\n"
        f"Status:       {status}\n"
        f"Strategy:     `{s.get('strategy', 'combined').upper()}`\n"
        f"Max Risk:     `{s.get('max_risk_per_trade', 2)}% per trade`\n"
        f"Max Trades:   `{s.get('max_open_trades', 5)} open at once`\n"
        f"Interval:     `every {s.get('run_interval_minutes', 60)} mins`\n"
        f"Last Run:     `{last_run}`\n"
        f"{'─' * 28}\n"
        f"🪙 Crypto:  {'✅ Active' if s.get('trade_crypto') else '❌ Off'}\n"
        f"📋 Stocks:  {'✅ Active' if s.get('trade_stocks') else '❌ Off'}\n"
        f"💱 Forex:   {'✅ Active' if s.get('trade_forex')  else '❌ Off'}"
    )

# ─── Commands ─────────────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Main entry point — shows the main menu."""
    await update.message.reply_text(
        "🤖 *Autonomous Trading Bot*\n\n"
        "Paper trading across Crypto, Stocks & Forex.\n"
        "All trades use *fake money only* — nothing is real.\n\n"
        "Choose an option below 👇",
        parse_mode   = "Markdown",
        reply_markup = main_keyboard()
    )

async def portfolio_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show portfolio summary."""
    pf  = api_get("/portfolio/")
    msg = format_portfolio(pf)
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_keyboard())

async def open_trades_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show all open positions."""
    data   = api_get("/trades/open")
    trades = data.get("trades", []) if isinstance(data, dict) else []

    if not trades:
        await update.message.reply_text(
            "📭 No open positions right now.",
            reply_markup=main_keyboard()
        )
        return

    msg = f"📈 *Open Positions* ({data.get('count', 0)} total)\n{'─' * 28}\n"
    for t in trades[:8]:
        msg += (
            f"• *{t['symbol']}* `{t.get('market_type', '').upper()}`\n"
            f"  {t['side'].upper()} | Entry: `${t['entry_price']:,.4f}`\n"
            f"  Qty: `{t['quantity']}` | SL: `${t.get('stop_loss', 0):,.4f}`\n"
            f"  Strategy: `{t.get('strategy', 'N/A')}`\n\n"
        )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_keyboard())

async def history_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show recent closed trades."""
    data   = api_get("/trades/history")
    trades = data.get("trades", []) if isinstance(data, dict) else []

    if not trades:
        await update.message.reply_text(
            "📭 No completed trades yet.",
            reply_markup=main_keyboard()
        )
        return

    msg = f"📜 *Recent Trade History*\n{'─' * 28}\n"
    for t in trades[:8]:
        pnl   = t.get("pnl") or 0
        emoji = "✅" if pnl > 0 else "❌"
        msg  += (
            f"{emoji} *{t['symbol']}* | {t['side'].upper()}\n"
            f"  P&L: `${pnl:,.2f}` ({t.get('pnl_pct', 0):+.1f}%)\n"
            f"  Strategy: `{t.get('strategy', 'N/A')}`\n\n"
        )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_keyboard())

async def stats_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show trading stats summary."""
    data = api_get("/trades/stats/summary")

    if "error" in data:
        await update.message.reply_text(f"❌ {data['error']}")
        return

    best  = data.get("best_trade")
    worst = data.get("worst_trade")
    bm    = data.get("by_market", {})

    msg = (
        f"📊 *Trading Statistics*\n"
        f"{'─' * 28}\n"
        f"Total Trades:   `{data.get('total_trades', 0)}`\n"
        f"Open Now:       `{data.get('open_positions', 0)}`\n"
        f"Wins:           `{data.get('winning_trades', 0)}`\n"
        f"Losses:         `{data.get('losing_trades', 0)}`\n"
        f"Win Rate:       `{data.get('win_rate', 0):.1f}%`\n"
        f"Total P&L:      `${data.get('total_pnl', 0):,.2f}`\n"
        f"Average P&L:    `${data.get('average_pnl', 0):,.2f}`\n"
        f"{'─' * 28}\n"
    )

    if best:
        msg += f"🏆 Best Trade:  *{best['symbol']}* `+${best['pnl']:,.2f}`\n"
    if worst:
        msg += f"💔 Worst Trade: *{worst['symbol']}* `${worst['pnl']:,.2f}`\n"

    msg += (
        f"{'─' * 28}\n"
        f"*By Market:*\n"
        f"  🪙 Crypto: `{bm.get('crypto', {}).get('trades', 0)} trades` | "
        f"`${bm.get('crypto', {}).get('pnl', 0):,.2f}`\n"
        f"  📋 Stocks: `{bm.get('stocks', {}).get('trades', 0)} trades` | "
        f"`${bm.get('stocks', {}).get('pnl', 0):,.2f}`\n"
        f"  💱 Forex:  `{bm.get('forex',  {}).get('trades', 0)} trades` | "
        f"`${bm.get('forex',  {}).get('pnl', 0):,.2f}`"
    )

    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_keyboard())

async def settings_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show bot settings."""
    s   = api_get("/settings/")
    msg = format_settings(s)
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=strategy_keyboard())

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show available commands."""
    msg = (
        "🤖 *Available Commands*\n"
        "{'─' * 28}\n"
        "/start       — Main menu\n"
        "/portfolio   — Portfolio summary\n"
        "/trades      — Open positions\n"
        "/history     — Trade history\n"
        "/stats       — Performance stats\n"
        "/settings    — Bot settings\n"
        "/help        — This message\n\n"
        "*This bot uses paper money only.*\n"
        "No real trades are ever placed."
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

# ─── Button Callback Handler ──────────────────────────────────────────────────

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data

    # ── Main Menu ─────────────────────────────────────────────────────────────
    if data in ("main_menu", "refresh"):
        await query.edit_message_text(
            "🤖 *Autonomous Trading Bot*\n\n"
            "Paper trading across Crypto, Stocks & Forex.\n"
            "Choose an option below 👇",
            parse_mode   = "Markdown",
            reply_markup = main_keyboard()
        )

    # ── Portfolio ─────────────────────────────────────────────────────────────
    elif data == "portfolio":
        pf  = api_get("/portfolio/")
        msg = format_portfolio(pf)
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=main_keyboard())

    # ── Open Trades ───────────────────────────────────────────────────────────
    elif data == "open_trades":
        result = api_get("/trades/open")
        trades = result.get("trades", []) if isinstance(result, dict) else []

        if not trades:
            msg = "📭 No open positions right now."
        else:
            msg = f"📈 *Open Positions* ({result.get('count', 0)})\n{'─' * 24}\n"
            for t in trades[:6]:
                pnl_line = ""
                msg += (
                    f"• *{t['symbol']}* `{t.get('market_type','').upper()}`\n"
                    f"  {t['side'].upper()} @ `${t['entry_price']:,.4f}`\n"
                    f"  Qty: `{t['quantity']}` | SL: `${t.get('stop_loss',0):,.4f}`\n\n"
                )

        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=main_keyboard())

    # ── Trade History ─────────────────────────────────────────────────────────
    elif data == "history":
        result = api_get("/trades/history")
        trades = result.get("trades", []) if isinstance(result, dict) else []

        if not trades:
            msg = "📭 No completed trades yet."
        else:
            msg = f"📜 *Recent History*\n{'─' * 24}\n"
            for t in trades[:6]:
                pnl   = t.get("pnl") or 0
                emoji = "✅" if pnl > 0 else "❌"
                msg  += (
                    f"{emoji} *{t['symbol']}* {t['side'].upper()}\n"
                    f"  P&L: `${pnl:,.2f}` ({t.get('pnl_pct', 0):+.1f}%)\n\n"
                )

        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=main_keyboard())

    # ── Stats ─────────────────────────────────────────────────────────────────
    elif data == "stats":
        d     = api_get("/trades/stats/summary")
        best  = d.get("best_trade")
        worst = d.get("worst_trade")

        msg = (
            f"📊 *Stats*\n{'─' * 24}\n"
            f"Trades:    `{d.get('total_trades', 0)}`\n"
            f"Win Rate:  `{d.get('win_rate', 0):.1f}%`\n"
            f"Total P&L: `${d.get('total_pnl', 0):,.2f}`\n"
            f"Avg P&L:   `${d.get('average_pnl', 0):,.2f}`\n"
        )
        if best:
            msg += f"🏆 Best: *{best['symbol']}* `+${best['pnl']:,.2f}`\n"
        if worst:
            msg += f"💔 Worst: *{worst['symbol']}* `${worst['pnl']:,.2f}`\n"

        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=main_keyboard())

    # ── Settings ──────────────────────────────────────────────────────────────
    elif data == "settings":
        s   = api_get("/settings/")
        msg = format_settings(s)
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=strategy_keyboard())

    # ── Markets ───────────────────────────────────────────────────────────────
    elif data == "markets":
        s   = api_get("/settings/")
        msg = (
            f"🌍 *Markets*\n{'─' * 24}\n"
            f"Toggle markets on/off below.\n"
            f"Changes take effect on next cycle."
        )
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=markets_keyboard(s))

    # ── Toggle Markets ────────────────────────────────────────────────────────
    elif data in ("toggle_crypto", "toggle_stocks", "toggle_forex"):
        market_map = {
            "toggle_crypto": "crypto",
            "toggle_stocks": "stocks",
            "toggle_forex":  "forex"
        }
        market = market_map[data]
        result = api_post(f"/settings/markets/{market}/toggle")
        state  = "enabled ✅" if result.get("enabled") else "disabled ❌"

        s   = api_get("/settings/")
        msg = f"🌍 *Markets* — {market.capitalize()} {state}\n{'─' * 24}\nToggle markets on/off below."
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=markets_keyboard(s))

    # ── Start Bot ─────────────────────────────────────────────────────────────
    elif data == "start_bot":
        s = api_get("/settings/")
        if s.get("is_running"):
            await query.edit_message_text(
                "ℹ️ Bot is already running ▶️",
                reply_markup=main_keyboard()
            )
        else:
            result = api_post("/settings/toggle")
            await query.edit_message_text(
                "▶️ *Bot Started!*\nThe agent will begin trading on its next cycle.",
                parse_mode   = "Markdown",
                reply_markup = main_keyboard()
            )

    # ── Stop Bot ──────────────────────────────────────────────────────────────
    elif data == "stop_bot":
        s = api_get("/settings/")
        if not s.get("is_running"):
            await query.edit_message_text(
                "ℹ️ Bot is already stopped ⏸",
                reply_markup=main_keyboard()
            )
        else:
            result = api_post("/settings/toggle")
            await query.edit_message_text(
                "⏸ *Bot Stopped!*\nNo new trades will be placed.",
                parse_mode   = "Markdown",
                reply_markup = main_keyboard()
            )

    # ── Strategy Change ───────────────────────────────────────────────────────
    elif data.startswith("strategy_"):
        strategy = data.replace("strategy_", "")
        result   = api_post(f"/settings/strategy/{strategy}")

        strategy_desc = {
            "rsi":      "RSI — Buys oversold, sells overbought",
            "macd":     "MACD — Trades on crossover signals",
            "combined": "Combined — RSI + MACD + Bollinger Bands ⭐",
            "ai":       "AI — GPT-powered decisions"
        }

        msg = (
            f"✅ *Strategy Updated!*\n\n"
            f"Now using: `{strategy.upper()}`\n"
            f"_{strategy_desc.get(strategy, '')}_"
        )
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=main_keyboard())

# ─── Unknown Message Handler ──────────────────────────────────────────────────

async def unknown_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle any text that isn't a command."""
    await update.message.reply_text(
        "Use /start to open the menu, or /help to see all commands.",
        reply_markup=main_keyboard()
    )

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    if not BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN not found in .env")

    app = Application.builder().token(BOT_TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler("start",     start))
    app.add_handler(CommandHandler("portfolio", portfolio_cmd))
    app.add_handler(CommandHandler("trades",    open_trades_cmd))
    app.add_handler(CommandHandler("history",   history_cmd))
    app.add_handler(CommandHandler("stats",     stats_cmd))
    app.add_handler(CommandHandler("settings",  settings_cmd))
    app.add_handler(CommandHandler("help",      help_cmd))

    # Button callback handler
    app.add_handler(CallbackQueryHandler(button_handler))

    # Catch-all for unknown text
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_message))

    logger.info("🤖 Telegram bot is running...")
    print("🤖 Telegram bot is running! Open Telegram and type /start")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()