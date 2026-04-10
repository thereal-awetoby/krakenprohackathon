# backend/brokers/alpaca_broker.py
import os
import logging
import requests

logger = logging.getLogger(__name__)

# ─── Alpaca Paper Trading Broker ──────────────────────────────────────────────
# Uses Alpaca's FREE paper trading API — 100% fake money, no real trades ever.
# Paper URL: https://paper-api.alpaca.markets
# Live URL:  https://api.alpaca.markets  ← we NEVER use this

class AlpacaBroker:

    def __init__(self):
        self.api_key    = os.getenv("ALPACA_API_KEY")
        self.secret_key = os.getenv("ALPACA_SECRET_KEY")
        self.base_url   = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

        # Headers used for every API request
        self.headers = {
            "APCA-API-KEY-ID":     self.api_key,
            "APCA-API-SECRET-KEY": self.secret_key,
            "Content-Type":        "application/json"
        }

        # Data URL is different from trading URL
        self.data_url = "https://data.alpaca.markets"

        if not self.api_key or not self.secret_key:
            logger.warning("Alpaca API keys not set in .env — broker will not work")

    # ─── Connection Check ──────────────────────────────────────────────────────

    def is_connected(self) -> bool:
        """Check if Alpaca API keys are valid and connected."""
        try:
            response = requests.get(
                f"{self.base_url}/v2/account",
                headers=self.headers,
                timeout=10
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Alpaca connection check failed: {e}")
            return False

    # ─── Account Info ──────────────────────────────────────────────────────────

    def get_account(self) -> dict:
        """Get paper trading account balance and info."""
        try:
            response = requests.get(
                f"{self.base_url}/v2/account",
                headers=self.headers,
                timeout=10
            )
            response.raise_for_status()
            account = response.json()

            return {
                "balance":         float(account.get("cash", 0)),
                "portfolio_value": float(account.get("portfolio_value", 0)),
                "buying_power":    float(account.get("buying_power", 0)),
                "status":          account.get("status", "unknown"),
                "currency":        "USD",
                "type":            "paper"       # always paper — never real money
            }

        except requests.exceptions.HTTPError as e:
            logger.error(f"Alpaca get_account HTTP error: {e}")
            return {}
        except Exception as e:
            logger.error(f"Alpaca get_account error: {e}")
            return {}

    # ─── Price Data ────────────────────────────────────────────────────────────

    def get_price_history(self, symbol: str, limit: int = 50) -> list:
        """
        Get historical daily closing prices for a stock symbol.
        Returns a list of floats (oldest to newest).
        Needs at least 35 prices for MACD to work correctly.
        """
        try:
            response = requests.get(
                f"{self.data_url}/v2/stocks/{symbol}/bars",
                headers=self.headers,
                params={
                    "timeframe": "1Day",
                    "limit":     limit,
                    "sort":      "asc"       # oldest first
                },
                timeout=15
            )
            response.raise_for_status()
            data = response.json()

            bars = data.get("bars", [])
            if not bars:
                logger.warning(f"No price history returned for {symbol}")
                return []

            prices = [float(bar["c"]) for bar in bars]   # "c" = closing price
            logger.info(f"Got {len(prices)} price bars for {symbol}")
            return prices

        except requests.exceptions.HTTPError as e:
            logger.error(f"Alpaca price history HTTP error for {symbol}: {e}")
            return []
        except Exception as e:
            logger.error(f"Alpaca get_price_history error for {symbol}: {e}")
            return []

    def get_current_price(self, symbol: str) -> float:
        """Get the latest trade price for a stock symbol."""
        try:
            response = requests.get(
                f"{self.data_url}/v2/stocks/{symbol}/trades/latest",
                headers=self.headers,
                timeout=10
            )
            response.raise_for_status()
            data  = response.json()
            price = float(data["trade"]["p"])   # "p" = price
            logger.info(f"Current price for {symbol}: ${price}")
            return price

        except requests.exceptions.HTTPError as e:
            logger.error(f"Alpaca get_current_price HTTP error for {symbol}: {e}")
            return 0.0
        except Exception as e:
            logger.error(f"Alpaca get_current_price error for {symbol}: {e}")
            return 0.0

    # ─── Order Placement ───────────────────────────────────────────────────────

    def place_buy(self, symbol: str, qty: float) -> dict:
        """
        Place a paper BUY market order.
        Uses fake money — no real purchase ever happens.
        """
        try:
            payload = {
                "symbol":        symbol,
                "qty":           str(round(qty, 6)),
                "side":          "buy",
                "type":          "market",
                "time_in_force": "day"      # expires end of trading day
            }

            response = requests.post(
                f"{self.base_url}/v2/orders",
                headers=self.headers,
                json=payload,
                timeout=10
            )
            response.raise_for_status()
            order = response.json()

            logger.info(f"Alpaca BUY order placed: {symbol} x{qty} | ID: {order.get('id')}")
            return {
                "order_id": order.get("id"),
                "status":   order.get("status"),
                "symbol":   symbol,
                "side":     "buy",
                "qty":      qty,
                "type":     "paper"
            }

        except requests.exceptions.HTTPError as e:
            logger.error(f"Alpaca place_buy HTTP error for {symbol}: {e.response.text}")
            return {"error": str(e), "symbol": symbol}
        except Exception as e:
            logger.error(f"Alpaca place_buy error for {symbol}: {e}")
            return {"error": str(e), "symbol": symbol}

    def place_sell(self, symbol: str, qty: float) -> dict:
        """
        Place a paper SELL market order.
        Uses fake money — no real sale ever happens.
        """
        try:
            payload = {
                "symbol":        symbol,
                "qty":           str(round(qty, 6)),
                "side":          "sell",
                "type":          "market",
                "time_in_force": "day"
            }

            response = requests.post(
                f"{self.base_url}/v2/orders",
                headers=self.headers,
                json=payload,
                timeout=10
            )
            response.raise_for_status()
            order = response.json()

            logger.info(f"Alpaca SELL order placed: {symbol} x{qty} | ID: {order.get('id')}")
            return {
                "order_id": order.get("id"),
                "status":   order.get("status"),
                "symbol":   symbol,
                "side":     "sell",
                "qty":      qty,
                "type":     "paper"
            }

        except requests.exceptions.HTTPError as e:
            logger.error(f"Alpaca place_sell HTTP error for {symbol}: {e.response.text}")
            return {"error": str(e), "symbol": symbol}
        except Exception as e:
            logger.error(f"Alpaca place_sell error for {symbol}: {e}")
            return {"error": str(e), "symbol": symbol}

    # ─── Positions ─────────────────────────────────────────────────────────────

    def get_open_positions(self) -> list:
        """Get all currently open paper positions."""
        try:
            response = requests.get(
                f"{self.base_url}/v2/positions",
                headers=self.headers,
                timeout=10
            )
            response.raise_for_status()
            positions = response.json()

            return [
                {
                    "symbol":     p.get("symbol"),
                    "qty":        float(p.get("qty", 0)),
                    "avg_price":  float(p.get("avg_entry_price", 0)),
                    "market_val": float(p.get("market_value", 0)),
                    "unrealized_pnl": float(p.get("unrealized_pl", 0))
                }
                for p in positions
            ]

        except Exception as e:
            logger.error(f"Alpaca get_open_positions error: {e}")
            return []

    def cancel_all_orders(self) -> bool:
        """Cancel all pending paper orders."""
        try:
            response = requests.delete(
                f"{self.base_url}/v2/orders",
                headers=self.headers,
                timeout=10
            )
            return response.status_code in (200, 207)
        except Exception as e:
            logger.error(f"Alpaca cancel_all_orders error: {e}")
            return False