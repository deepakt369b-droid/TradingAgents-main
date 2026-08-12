"""Abstract Base Class for Trade Execution Platform Integrations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from .order_models import AccountBalance, Order, OrderResult, OrderStatus, Position


class BaseExecutor(ABC):
    """Abstract base class for brokerage/exchange execution drivers."""

    def __init__(self, config: dict | None = None):
        self.config = config or {}

    @abstractmethod
    def place_order(self, order: Order) -> OrderResult:
        """Place a new buy/sell order on the platform."""
        pass

    @abstractmethod
    def get_positions(self) -> list[Position]:
        """Fetch active positions."""
        pass

    @abstractmethod
    def get_account_balance(self) -> AccountBalance:
        """Fetch cash and portfolio value."""
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an active pending order."""
        pass

    @abstractmethod
    def get_order_status(self, order_id: str) -> OrderStatus:
        """Fetch current order status by ID."""
        pass
