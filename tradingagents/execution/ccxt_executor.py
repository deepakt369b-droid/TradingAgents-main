"""CCXT Unified Crypto Exchange Executor (Binance, Coinbase, KuCoin, Bybit)."""

from __future__ import annotations

import os
import logging
from .base_executor import BaseExecutor
from .live_gate import is_live_trading_enabled
from .order_models import AccountBalance, Order, OrderResult, OrderSide, OrderStatus, Position

logger = logging.getLogger(__name__)


class CCXTExecutor(BaseExecutor):
    """Unified execution driver for 100+ crypto exchanges using CCXT."""

    def __init__(
        self,
        exchange_id: str = "binance",
        api_key: str | None = None,
        secret_key: str | None = None,
        config: dict | None = None,
    ):
        super().__init__(config)
        self.exchange_id = os.environ.get("CCXT_EXCHANGE", exchange_id).lower()
        self.api_key = api_key or os.environ.get("CCXT_API_KEY")
        self.secret_key = secret_key or os.environ.get("CCXT_SECRET_KEY")
        self._exchange = None

    def _get_exchange(self):
        if self._exchange is None:
            try:
                import ccxt
                if not hasattr(ccxt, self.exchange_id):
                    raise ValueError(f"Unsupported CCXT exchange: {self.exchange_id}")
                exchange_class = getattr(ccxt, self.exchange_id)
                self._exchange = exchange_class({
                    "apiKey": self.api_key or "",
                    "secret": self.secret_key or "",
                    "enableRateLimit": True,
                })
                # Paper-first gate: sandbox/testnet unless the user has
                # explicitly opted into live trading (TRADINGAGENTS_LIVE_
                # TRADING_ENABLED). Without this, the moment CCXT_API_KEY is
                # set this trades real money on the live exchange (#4a).
                live = is_live_trading_enabled()
                if hasattr(self._exchange, "set_sandbox_mode"):
                    self._exchange.set_sandbox_mode(not live)
                elif not live:
                    raise RuntimeError(
                        f"CCXT exchange '{self.exchange_id}' has no sandbox mode and "
                        "TRADINGAGENTS_LIVE_TRADING_ENABLED is not set -- refusing to "
                        "construct a live-trading-capable client. Set the env var "
                        "explicitly to trade live on this exchange."
                    )
                logger.info(
                    "Initialized CCXT exchange instance for '%s' (live=%s).",
                    self.exchange_id, live,
                )
            except ImportError:
                raise ImportError("ccxt package is required for crypto execution. Install with: pip install ccxt")
        return self._exchange

    def place_order(self, order: Order) -> OrderResult:
        ex = self._get_exchange()
        side = order.side.value
        symbol = order.symbol
        if "/" not in symbol and "USDT" in symbol:
            symbol = symbol.replace("USDT", "/USDT")

        # Forward client_order_id as defense-in-depth idempotency (most
        # exchanges CCXT wraps accept "clientOrderId" in params and reject a
        # duplicate within their own dedup window); correctness does not
        # depend on this, the caller's OrderLedger check is authoritative.
        params = {"clientOrderId": order.client_order_id} if order.client_order_id else {}

        if order.order_type == "limit" and order.price:
            res = ex.create_limit_order(symbol, side, order.quantity, order.price, params)
        else:
            res = ex.create_market_order(symbol, side, order.quantity, params=params)

        return OrderResult(
            order_id=str(res.get("id")),
            symbol=order.symbol,
            side=order.side,
            status=OrderStatus.FILLED if res.get("status") == "closed" else OrderStatus.PENDING,
            quantity=float(res.get("amount", order.quantity)),
            filled_quantity=float(res.get("filled", 0.0)),
            filled_price=float(res.get("price", 0.0)) if res.get("price") else None,
            message=f"CCXT {self.exchange_id} order placed successfully",
        )

    def get_positions(self) -> list[Position]:
        ex = self._get_exchange()
        positions = []
        try:
            bal = ex.fetch_balance()
            total = bal.get("total", {})
            for sym, qty in total.items():
                if qty > 0:
                    positions.append(
                        Position(
                            symbol=f"{sym}/USDT",
                            quantity=float(qty),
                            average_entry_price=0.0,
                            current_price=0.0,
                            unrealized_pnl=0.0,
                            asset_type="crypto",
                        )
                    )
        except Exception as exc:
            logger.warning("CCXT get_positions error: %s", exc)
        return positions

    def get_account_balance(self) -> AccountBalance:
        ex = self._get_exchange()
        try:
            bal = ex.fetch_balance()
            free_usdt = float(bal.get("free", {}).get("USDT", 0.0))
            total_usdt = float(bal.get("total", {}).get("USDT", free_usdt))
            return AccountBalance(
                currency="USDT",
                cash=free_usdt,
                buying_power=free_usdt,
                portfolio_value=total_usdt,
            )
        except Exception:
            return AccountBalance(cash=0.0, buying_power=0.0, portfolio_value=0.0)

    def cancel_order(self, order_id: str) -> bool:
        ex = self._get_exchange()
        try:
            ex.cancel_order(order_id)
            return True
        except Exception:
            return False

    def get_order_status(self, order_id: str) -> OrderStatus:
        ex = self._get_exchange()
        try:
            o = ex.fetch_order(order_id)
            st = o.get("status")
            if st == "closed":
                return OrderStatus.FILLED
            if st == "canceled":
                return OrderStatus.CANCELLED
            return OrderStatus.PENDING
        except Exception:
            return OrderStatus.REJECTED
