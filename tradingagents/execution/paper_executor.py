"""Paper Trading Executor for safe local simulation with zero real money risk."""

from __future__ import annotations

import uuid
import time
import logging
from .base_executor import BaseExecutor
from .order_models import AccountBalance, Order, OrderResult, OrderSide, OrderStatus, Position

logger = logging.getLogger(__name__)


class PaperExecutor(BaseExecutor):
    """Simulated paper trading executor."""

    def __init__(self, initial_cash: float = 100000.0, config: dict | None = None):
        super().__init__(config)
        self.cash = initial_cash
        self.positions: dict[str, Position] = {}
        self.orders: dict[str, OrderResult] = {}

    def place_order(self, order: Order) -> OrderResult:
        order_id = f"paper-{uuid.uuid4().hex[:8]}"
        # Estimate execution price from latest price or order price or default
        exec_price = order.price if order.price else 100.0
        total_cost = exec_price * order.quantity

        if order.side == OrderSide.BUY:
            if self.cash < total_cost:
                logger.warning("PaperExecutor: Insufficient buying power for order %s", order.symbol)
                return OrderResult(
                    order_id=order_id,
                    symbol=order.symbol,
                    side=order.side,
                    status=OrderStatus.REJECTED,
                    quantity=order.quantity,
                    message="Insufficient funds in paper account",
                )

            self.cash -= total_cost
            if order.symbol in self.positions:
                existing = self.positions[order.symbol]
                new_qty = existing.quantity + order.quantity
                avg_price = (existing.average_entry_price * existing.quantity + total_cost) / new_qty
                self.positions[order.symbol] = Position(
                    symbol=order.symbol,
                    quantity=new_qty,
                    average_entry_price=avg_price,
                    current_price=exec_price,
                    unrealized_pnl=0.0,
                )
            else:
                self.positions[order.symbol] = Position(
                    symbol=order.symbol,
                    quantity=order.quantity,
                    average_entry_price=exec_price,
                    current_price=exec_price,
                    unrealized_pnl=0.0,
                )

        elif order.side == OrderSide.SELL:
            current_pos = self.positions.get(order.symbol)
            if not current_pos or current_pos.quantity < order.quantity:
                return OrderResult(
                    order_id=order_id,
                    symbol=order.symbol,
                    side=order.side,
                    status=OrderStatus.REJECTED,
                    quantity=order.quantity,
                    message="Insufficient position to sell",
                )

            self.cash += total_cost
            new_qty = current_pos.quantity - order.quantity
            if new_qty <= 0:
                del self.positions[order.symbol]
            else:
                self.positions[order.symbol].quantity = new_qty

        result = OrderResult(
            order_id=order_id,
            symbol=order.symbol,
            side=order.side,
            status=OrderStatus.FILLED,
            quantity=order.quantity,
            filled_quantity=order.quantity,
            filled_price=exec_price,
            message="Paper order executed successfully",
        )
        self.orders[order_id] = result
        logger.info("PaperExecutor: Executed %s %f %s at $%.2f", order.side.value, order.quantity, order.symbol, exec_price)
        return result

    def get_positions(self) -> list[Position]:
        return list(self.positions.values())

    def get_account_balance(self) -> AccountBalance:
        positions_value = sum(p.quantity * p.current_price for p in self.positions.values())
        return AccountBalance(
            cash=self.cash,
            buying_power=self.cash,
            portfolio_value=self.cash + positions_value,
        )

    def cancel_order(self, order_id: str) -> bool:
        if order_id in self.orders:
            self.orders[order_id].status = OrderStatus.CANCELLED
            return True
        return False

    def get_order_status(self, order_id: str) -> OrderStatus:
        if order_id in self.orders:
            return self.orders[order_id].status
        return OrderStatus.REJECTED
