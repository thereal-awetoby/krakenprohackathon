# backend/agents/base_agent.py
import logging
from datetime import datetime
from strategies.rsi_strategy import rsi_signal, macd_signal, combined_signal
from strategies.ai_strategy import ai_signal
from models import Trade, Portfolio, BotSettings, MarketType, TradeStatus, BrokerName

logger = logging.getLogger(__name__)

class TradingAgent:

    def __init__(self, broker, market_type: MarketType, broker_name: BrokerName, strategy: str = "rsi"):
        self.broker      = broker
        self.market_type = market_type
        self.broker_name = broker_name
        self.strategy    = strategy

    # ─── Signal Analysis ───────────────────────────────────────────────────────

    async def analyze(self, symbol: str) -> dict:
        """
        Fetch price history and generate a trading signal.
        Returns a dict with action, reason, confidence, stop_loss_pct, take_profit_pct.
        """
        try:
            prices = self.broker.get_price_history(symbol)

            if not prices or len(prices) < 35:
                logger.warning(f"Not enough price data for {symbol} — skipping")
                return {"action": "hold", "reason": "Not enough price data", "confidence": 0.0}

            if self.strategy == "rsi":
                return rsi_signal(prices)
            elif self.strategy == "macd":
                return macd_signal(prices)
            elif self.strategy == "combined":
                return combined_signal(prices)
            elif self.strategy == "ai":
                return await ai_signal(symbol, prices, self.market_type.value)
            else:
                logger.warning(f"Unknown strategy '{self.strategy}' — defaulting to combined")
                return combined_signal(prices)

        except Exception as e:
            logger.error(f"analyze() error for {symbol}: {e}")
            return {"action": "hold", "reason": f"Analysis error: {e}", "confidence": 0.0}

    # ─── Position Sizing ───────────────────────────────────────────────────────

    def calculate_position_size(self, balance: float, price: float, risk_pct: float = 2.0) -> float:
        """
        Risk management — never risk more than X% of balance on one trade.
        Default is 2% which is standard for safe trading.
        """
        if price <= 0:
            return 0.0
        risk_amount = balance * (risk_pct / 100)
        quantity    = risk_amount / price
        return round(quantity, 6)

    # ─── Stop Loss & Take Profit ───────────────────────────────────────────────

    def calculate_levels(self, entry_price: float, signal: dict) -> tuple:
        """
        Calculate stop loss and take profit price levels from signal percentages.
        Falls back to 2% stop loss and 4% take profit if not in signal.
        """
        sl_pct = signal.get("stop_loss_pct",   2.0)
        tp_pct = signal.get("take_profit_pct", 4.0)

        stop_loss   = round(entry_price * (1 - sl_pct / 100), 6)
        take_profit = round(entry_price * (1 + tp_pct / 100), 6)

        return stop_loss, take_profit

    # ─── Main Agent Cycle ──────────────────────────────────────────────────────

    async def run_cycle(self, symbols: list, db_session) -> list:
        """
        Main loop — runs on a schedule.
        For each symbol: analyze → decide → place paper trade → save to DB.
        """

        # ── Load settings and portfolio from DB ───────────────────────────────
        settings  = db_session.query(BotSettings).first()
        portfolio = db_session.query(Portfolio).first()

        # Create defaults if first run
        if not settings:
            settings = BotSettings()
            db_session.add(settings)
            db_session.commit()

        if not portfolio:
            portfolio = Portfolio(balance=100000.0, initial_balance=100000.0)
            db_session.add(portfolio)
            db_session.commit()

        # ── Check if bot is enabled ───────────────────────────────────────────
        if not settings.is_running:
            logger.info("Bot is paused — skipping cycle")
            return []

        # ── Check open trade limit ────────────────────────────────────────────
        open_trade_count = db_session.query(Trade).filter(
            Trade.status == TradeStatus.OPEN
        ).count()

        if open_trade_count >= settings.max_open_trades:
            logger.info(f"Max open trades reached ({settings.max_open_trades}) — skipping new entries")
            # Still check exits below

        results = []

        for symbol in symbols:
            try:
                logger.info(f"── Analyzing {symbol} ({self.market_type.value}) ──")

                # ── Get signal ────────────────────────────────────────────────
                signal = await self.analyze(symbol)
                action     = signal.get("action", "hold")
                confidence = signal.get("confidence", 0.0)
                reason     = signal.get("reason", "")

                logger.info(f"{symbol} → {action.upper()} (confidence: {confidence:.2f}) | {reason}")

                # Skip low confidence and hold signals
                if action == "hold" or confidence < 0.5:
                    logger.info(f"Skipping {symbol} — {action} / confidence too low ({confidence:.2f})")
                    continue

                # ── Get current price ─────────────────────────────────────────
                current_price = self.broker.get_current_price(symbol)
                if current_price <= 0:
                    logger.warning(f"Invalid price for {symbol} — skipping")
                    continue

                # ── BUY Logic ─────────────────────────────────────────────────
                if action == "buy" and open_trade_count < settings.max_open_trades:

                    # Check we don't already have an open position in this symbol
                    existing = db_session.query(Trade).filter(
                        Trade.symbol == symbol,
                        Trade.status == TradeStatus.OPEN
                    ).first()

                    if existing:
                        logger.info(f"Already have open position in {symbol} — skipping buy")
                        continue

                    # Calculate quantity and levels
                    quantity                = self.calculate_position_size(
                                                portfolio.balance,
                                                current_price,
                                                settings.max_risk_per_trade
                                             )
                    stop_loss, take_profit  = self.calculate_levels(current_price, signal)
                    cost                    = quantity * current_price

                    # Check sufficient balance
                    if cost > portfolio.balance:
                        logger.warning(f"Insufficient balance for {symbol} — need ${cost:.2f}, have ${portfolio.balance:.2f}")
                        continue

                    # Place paper order
                    order = self.broker.place_buy(symbol, quantity)

                    if "error" in order:
                        logger.error(f"Buy order failed for {symbol}: {order['error']}")
                        continue

                    # Save trade to database
                    trade = Trade(
                        symbol      = symbol,
                        market_type = self.market_type,
                        broker      = self.broker_name,
                        side        = "buy",
                        quantity    = quantity,
                        entry_price = current_price,
                        stop_loss   = stop_loss,
                        take_profit = take_profit,
                        status      = TradeStatus.OPEN,
                        strategy    = self.strategy,
                        reason      = reason
                    )
                    db_session.add(trade)

                    # Update portfolio
                    portfolio.balance      -= cost
                    portfolio.total_trades += 1
                    open_trade_count       += 1

                    db_session.commit()
                    logger.info(f"✅ BUY {symbol} | qty={quantity} | price=${current_price} | cost=${cost:.2f}")

                    results.append({
                        "symbol":   symbol,
                        "action":   "BUY",
                        "price":    current_price,
                        "quantity": quantity,
                        "reason":   reason,
                        "broker":   self.broker_name.value
                    })

                # ── SELL Logic ────────────────────────────────────────────────
                elif action == "sell":

                    # Find open position for this symbol
                    open_trade = db_session.query(Trade).filter(
                        Trade.symbol == symbol,
                        Trade.status == TradeStatus.OPEN,
                        Trade.side   == "buy"
                    ).first()

                    if not open_trade:
                        logger.info(f"No open position in {symbol} to sell — skipping")
                        continue

                    # Place paper sell order
                    order = self.broker.place_sell(symbol, open_trade.quantity)

                    if "error" in order:
                        logger.error(f"Sell order failed for {symbol}: {order['error']}")
                        continue

                    # Calculate P&L
                    proceeds = current_price * open_trade.quantity
                    pnl      = (current_price - open_trade.entry_price) * open_trade.quantity
                    pnl_pct  = ((current_price - open_trade.entry_price) / open_trade.entry_price) * 100

                    # Update trade record
                    open_trade.exit_price = current_price
                    open_trade.status     = TradeStatus.CLOSED
                    open_trade.closed_at  = datetime.utcnow()
                    open_trade.pnl        = round(pnl, 4)
                    open_trade.pnl_pct    = round(pnl_pct, 4)

                    # Update portfolio
                    portfolio.balance    += proceeds
                    portfolio.total_pnl  += pnl

                    # Track per-market P&L
                    if self.market_type == MarketType.CRYPTO:
                        portfolio.crypto_pnl += pnl
                    elif self.market_type == MarketType.STOCK:
                        portfolio.stock_pnl  += pnl
                    elif self.market_type == MarketType.FOREX:
                        portfolio.forex_pnl  += pnl

                    # Track wins and losses
                    if pnl > 0:
                        portfolio.winning_trades += 1
                    else:
                        portfolio.losing_trades  += 1

                    portfolio.updated_at = datetime.utcnow()
                    db_session.commit()

                    emoji = "✅" if pnl > 0 else "❌"
                    logger.info(f"{emoji} SELL {symbol} | pnl=${pnl:.2f} ({pnl_pct:.2f}%)")

                    results.append({
                        "symbol":   symbol,
                        "action":   "SELL",
                        "price":    current_price,
                        "pnl":      round(pnl, 4),
                        "pnl_pct":  round(pnl_pct, 2),
                        "reason":   reason,
                        "broker":   self.broker_name.value
                    })

            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}")
                db_session.rollback()
                continue

        # ── Update last_run time ──────────────────────────────────────────────
        settings.last_run = datetime.utcnow()
        db_session.commit()

        logger.info(f"Cycle complete — {len(results)} trades executed")
        return results