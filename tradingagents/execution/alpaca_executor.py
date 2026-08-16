"""Alpaca Markets Executor for Commission-Free US Equities & Options."""

from __future__ import annotations

import os
import logging
from .base_executor import BaseExecutor
from .live_gate import is_live_trading_enabled
from .order_models import AccountBalance, Order, OrderResult, OrderSide, OrderStatus, Position

logger = logging.getLogger(__name__)


class AlpacaExecutor(BaseExecutor):
    """Execution driver for Alpaca Markets REST API."""

    def __init__(self, api_key: str | None = None, secret_key: str | None = None, paper: bool = True, config: dict | None = None):
        super().__init__(config)
        self.api_key = api_key or os.environ.get("ALPACA_API_KEY")
        self.secret_key = secret_key or os.environ.get("ALPACA_SECRET_KEY")
        # Paper-first gate: a caller can request paper=False, but that's only
        # honored when the user has explicitly opted into live trading via
        # TRADINGAGENTS_LIVE_TRADING_ENABLED (#4a) -- `paper` alone is not
        # trusted as the sole guard against accidentally trading real money.
        self.paper = paper or not is_live_trading_enabled()
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from alpaca.trading.client import TradingClient
                if not self.api_key or not self.secret_key:
                    raise ValueError("ALPACA_API_KEY and ALPACA_SECRET_KEY must be set.")
                self._client = TradingClient(self.api_key, self.secret_key, paper=self.paper)
                logger.info("Initialized Alpaca TradingClient (paper=%s).", self.paper)
            except ImportError:
                raise ImportError("alpaca-py is required for Alpaca execution. Install with: pip install alpaca-py")
        return self._client

    def place_order(self, order: Order) -> OrderResult:
        client = self._get_client()
        from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
        from alpaca.trading.enums import OrderSide as AlpacaOrderSide, TimeInForce

        side = AlpacaOrderSide.BUY if order.side == OrderSide.BUY else AlpacaOrderSide.SELL

        # client_order_id is forwarded as defense-in-depth idempotency:
        # Alpaca rejects a duplicate within its own dedup window. Correctness
        # does not depend on this -- the caller's OrderLedger check (see
        # execution/order_ledger.py) is authoritative.
        common_kwargs = dict(
            symbol=order.symbol,
            qty=order.quantity,
            side=side,
            time_in_force=TimeInForce.DAY,
        )
        if order.client_order_id:
            common_kwargs["client_order_id"] = order.client_order_id

        if order.order_type == "limit" and order.price:
            req = LimitOrderRequest(limit_price=order.price, **common_kwargs)
        else:
            req = MarketOrderRequest(**common_kwargs)

        alpaca_order = client.submit_order(req)
        return OrderResult(
            order_id=str(alpaca_order.id),
            symbol=order.symbol,
            side=order.side,
            status=OrderStatus.PENDING if alpaca_order.status == "new" else OrderStatus.FILLED,
            quantity=float(alpaca_order.qty),
            message=f"Alpaca order submitted (status: {alpaca_order.status})",
        )

    def get_positions(self) -> list[Position]:
        client = self._get_client()
        raw_positions = client.get_all_positions()
        positions = []
        for p in raw_positions:
            positions.append(
                Position(
                    symbol=p.symbol,
                    quantity=float(p.qty),
                    average_entry_price=float(p.avg_entry_price),
                    current_price=float(p.current_price),
                    unrealized_pnl=float(p.unrealized_pl),
                    asset_type="stock",
                )
            )
        return positions

    def get_account_balance(self) -> AccountBalance:
        client = self._get_client()
        acc = client.get_account()
        return AccountBalance(
            currency=acc.currency,
            cash=float(acc.cash),
            buying_power=float(acc.buying_power),
            portfolio_value=float(acc.portfolio_value),
        )

    def cancel_order(self, order_id: str) -> bool:
        client = self._get_client()
        try:
            client.cancel_order_by_id(order_id)
            return True
        except Exception as exc:
            logger.warning("Alpaca cancel_order error: %s", exc)
            return False

    def get_order_status(self, order_id: str) -> OrderStatus:
        client = self._get_client()
        try:
            o = client.get_order_by_id(order_id)
            if o.status in ("filled",):
                return OrderStatus.FILLED
            if o.status in ("canceled", "expired"):
                return OrderStatus.CANCELLED
            if o.status in ("rejected",):
                return OrderStatus.REJECTED
            return OrderStatus.PENDING
        except Exception:
            return OrderStatus.REJECTED
