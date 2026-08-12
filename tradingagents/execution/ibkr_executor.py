"""Interactive Brokers (IBKR) Executor for Global Markets & FX."""

from __future__ import annotations

import os
import logging
from .base_executor import BaseExecutor
from .order_models import AccountBalance, Order, OrderResult, OrderSide, OrderStatus, Position

logger = logging.getLogger(__name__)


class IBKRExecutor(BaseExecutor):
    """Execution driver for Interactive Brokers TWS API via ib_insync."""

    def __init__(self, host: str = "127.0.0.1", port: int = 7497, client_id: int = 1, config: dict | None = None):
        super().__init__(config)
        self.host = os.environ.get("IBKR_HOST", host)
        self.port = int(os.environ.get("IBKR_PORT", str(port)))
        self.client_id = int(os.environ.get("IBKR_CLIENT_ID", str(client_id)))
        self._ib = None

    def _get_ib(self):
        if self._ib is None:
            try:
                from ib_insync import IB
                self._ib = IB()
                self._ib.connect(self.host, self.port, clientId=self.client_id)
                logger.info("Connected to Interactive Brokers TWS Gateway at %s:%d", self.host, self.port)
            except ImportError:
                raise ImportError("ib_insync is required for IBKR execution. Install with: pip install ib_insync")
        return self._ib

    def place_order(self, order: Order) -> OrderResult:
        ib = self._get_ib()
        from ib_insync import Stock, MarketOrder, LimitOrder

        contract = Stock(order.symbol, "SMART", "USD")
        ib.qualifyContracts(contract)

        action = "BUY" if order.side == OrderSide.BUY else "SELL"
        if order.order_type == "limit" and order.price:
            ib_order = LimitOrder(action, order.quantity, order.price)
        else:
            ib_order = MarketOrder(action, order.quantity)

        trade = ib.placeOrder(contract, ib_order)
        return OrderResult(
            order_id=str(trade.order.orderId),
            symbol=order.symbol,
            side=order.side,
            status=OrderStatus.PENDING,
            quantity=order.quantity,
            message="Submitted to IBKR TWS Gateway",
        )

    def get_positions(self) -> list[Position]:
        ib = self._get_ib()
        raw = ib.positions()
        positions = []
        for p in raw:
            positions.append(
                Position(
                    symbol=p.contract.symbol,
                    quantity=float(p.position),
                    average_entry_price=float(p.avgCost),
                    current_price=float(p.avgCost),
                    unrealized_pnl=0.0,
                    asset_type="global_equity",
                )
            )
        return positions

    def get_account_balance(self) -> AccountBalance:
        ib = self._get_ib()
        summary = {item.tag: item.value for item in ib.accountSummary()}
        cash = float(summary.get("TotalCashValue", 0.0))
        buying_power = float(summary.get("BuyingPower", 0.0))
        net_val = float(summary.get("NetLiquidation", cash))
        return AccountBalance(
            cash=cash,
            buying_power=buying_power,
            portfolio_value=net_val,
        )

    def cancel_order(self, order_id: str) -> bool:
        ib = self._get_ib()
        for trade in ib.openTrades():
            if str(trade.order.orderId) == order_id:
                ib.cancelOrder(trade.order)
                return True
        return False

    def get_order_status(self, order_id: str) -> OrderStatus:
        ib = self._get_ib()
        for trade in ib.trades():
            if str(trade.order.orderId) == order_id:
                st = trade.orderStatus.status.lower()
                if st == "filled":
                    return OrderStatus.FILLED
                if st in ("cancelled", "inactive"):
                    return OrderStatus.CANCELLED
                return OrderStatus.PENDING
        return OrderStatus.REJECTED
