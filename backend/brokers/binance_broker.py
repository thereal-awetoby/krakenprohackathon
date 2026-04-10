# backend/brokers/binance_broker.py
import os
import logging
import requests
import hmac
import hashlib
import time

logger = logging.getLogger(__name__)

# ─── Binance Testnet Broker ───────────────────────────────────────────────────
# Uses Binance TESTNET — 100% fake money, no real trades ever.
# Testnet URL: https://testnet.binance.vision
# Live URL:    https://api.binance.com  ← we NEVER use this

class BinanceBroker:

    def __init__(self):
        self.api_key    = os.getenv("BINANCE_API_KEY")
        self.secret_key = os.getenv("BINANCE_SECRET_KEY")

        # TESTNET base URL — fake money only
        self.base_url   = "https://testnet.binance.vision/api"

        self.headers = {
            "X-MBX-APIKEY": self.api_key
        }

        if not self.api_key or not self.secret_key:
            logger.warning("Binance API keys not set in .env — broker will not work")

    # ─── Signature (required by Binance for orders) ───────────────────────────

    def _sign(self, params: dict) -> dict:
        """
        Binance requires every order request to be signed with your secret key.
        This is handled automatically — you never need to touch this.
        """
        params["timestamp"] = int(time.time() * 1000)
        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        signature = hmac.new(
            self.secret_key.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        params["signature"] = signature
        return params

    # ─── Connection Check ──────────────────────────────────────────────────────

    def is_connected(self) -> bool:
        """Ping Binance testnet to check connection."""
        try:
            response = requests.get(
                f"{self.base_url}/v3/ping",
                timeout=10
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Binance connection check failed: {e}")
            return False

    # ─── Account Info ──────────────────────────────────────────────────────────

    def get_account(self) -> dict:
        """Get testnet account balances."""
        try:
            params = self._sign({})
            response = requests.get(
                f"{self.base_url}/v3/account",
                headers=self.headers,
                params=params,
                timeout=10
            )
            response.raise_for_status()
            data = response.json()

            # Filter to only non-zero balances
            balances = {
                b["asset"]: float(b["free"])
                for b in data.get("balances", [])
                if float(b["free"]) > 0
            }

            return {
                "balances": balances,
                "type":     "testnet"    # always testnet — never real money
            }

        except Exception as e:
            logger.error(f"Binance get_account error: {e}")
            return {}

    # ─── Price Data ────────────────────────────────────────────────────────────

    def get_price_history(self, symbol: str, limit: int = 50) -> list:
        """
        Get historical hourly closing prices for a crypto symbol.
        Symbol format: BTCUSDT, ETHUSDT, SOLUSDT
        Returns a list of floats (oldest to newest).
        """
        try:
            response = requests.get(
                f"{self.base_url}/v3/klines",
                params={
                    "symbol":   symbol,
                    "interval": "1h",     # 1 hour candles
                    "limit":    limit
                },
                timeout=15
            )
            response.raise_for_status()
            klines = response.json()

            if not klines:
                logger.warning(f"No price history returned for {symbol}")
                return []

            # Index 4 = closing price in Binance kline format
            prices = [float(k[4]) for k in klines]
            logger.info(f"Got {len(prices)} price bars for {symbol}")
            return prices

        except Exception as e:
            logger.error(f"Binance get_price_history error for {symbol}: {e}")
            return []

    def get_current_price(self, symbol: str) -> float:
        """Get the latest price for a crypto symbol."""
        try:
            response = requests.get(
                f"{self.base_url}/v3/ticker/price",
                params={"symbol": symbol},
                timeout=10
            )
            response.raise_for_status()
            price = float(response.json()["price"])
            logger.info(f"Current price for {symbol}: ${price}")
            return price

        except Exception as e:
            logger.error(f"Binance get_current_price error for {symbol}: {e}")
            return 0.0

    # ─── Order Placement ───────────────────────────────────────────────────────

    def place_buy(self, symbol: str, quantity: float) -> dict:
        """
        Place a testnet BUY market order.
        Uses fake money — no real crypto is ever purchased.
        """
        try:
            params = self._sign({
                "symbol":    symbol,
                "side":      "BUY",
                "type":      "MARKET",
                "quantity":  round(quantity, 6)
            })

            response = requests.post(
                f"{self.base_url}/v3/order",
                headers=self.headers,
                params=params,
                timeout=10
            )
            response.raise_for_status()
            order = response.json()

            logger.info(f"Binance BUY order placed: {symbol} x{quantity} | ID: {order.get('orderId')}")
            return {
                "order_id": order.get("orderId"),
                "status":   order.get("status"),
                "symbol":   symbol,
                "side":     "buy",
                "quantity": quantity,
                "type":     "testnet"
            }

        except requests.exceptions.HTTPError as e:
            logger.error(f"Binance place_buy HTTP error for {symbol}: {e.response.text}")
            return {"error": str(e), "symbol": symbol}
        except Exception as e:
            logger.error(f"Binance place_buy error for {symbol}: {e}")
            return {"error": str(e), "symbol": symbol}

    def place_sell(self, symbol: str, quantity: float) -> dict:
        """
        Place a testnet SELL market order.
        Uses fake money — no real crypto is ever sold.
        """
        try:
            params = self._sign({
                "symbol":   symbol,
                "side":     "SELL",
                "type":     "MARKET",
                "quantity": round(quantity, 6)
            })

            response = requests.post(
                f"{self.base_url}/v3/order",
                headers=self.headers,
                params=params,
                timeout=10
            )
            response.raise_for_status()
            order = response.json()

            logger.info(f"Binance SELL order placed: {symbol} x{quantity} | ID: {order.get('orderId')}")
            return {
                "order_id": order.get("orderId"),
                "status":   order.get("status"),
                "symbol":   symbol,
                "side":     "sell",
                "quantity": quantity,
                "type":     "testnet"
            }

        except requests.exceptions.HTTPError as e:
            logger.error(f"Binance place_sell HTTP error for {symbol}: {e.response.text}")
            return {"error": str(e), "symbol": symbol}
        except Exception as e:
            logger.error(f"Binance place_sell error for {symbol}: {e}")
            return {"error": str(e), "symbol": symbol}

    # ─── Open Orders ───────────────────────────────────────────────────────────

    def get_open_orders(self, symbol: str = None) -> list:
        """Get all open testnet orders, optionally filtered by symbol."""
        try:
            params = self._sign({"symbol": symbol} if symbol else {})
            response = requests.get(
                f"{self.base_url}/v3/openOrders",
                headers=self.headers,
                params=params,
                timeout=10
            )
            response.raise_for_status()
            return response.json()

        except Exception as e:
            logger.error(f"Binance get_open_orders error: {e}")
            return []

    def cancel_all_orders(self, symbol: str) -> bool:
        """Cancel all open orders for a symbol."""
        try:
            params = self._sign({"symbol": symbol})
            response = requests.delete(
                f"{self.base_url}/v3/openOrders",
                headers=self.headers,
                params=params,
                timeout=10
            )
            return response.status_code == 200

        except Exception as e:
            logger.error(f"Binance cancel_all_orders error: {e}")
            return False