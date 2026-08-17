"""Data models for Order Execution, Positions, and Account Balances."""

from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderStatus(str, Enum):
    PENDING = "pending"
    PENDING_APPROVAL = "pending_approval"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class Order(BaseModel):
    symbol: str
    side: OrderSide
    quantity: float
    order_type: OrderType = OrderType.MARKET
    price: Optional[float] = None
    stop_price: Optional[float] = None
    asset_type: str = "stock"  # stock, crypto, forex, global_equity
    client_order_id: Optional[str] = None


class OrderResult(BaseModel):
    order_id: str
    symbol: str
    side: OrderSide
    status: OrderStatus
    quantity: float
    filled_quantity: float = 0.0
    filled_price: Optional[float] = None
    commission: float = 0.0
    message: str = ""
    timestamp: float = Field(default_factory=lambda: __import__("time").time())


class Position(BaseModel):
    symbol: str
    quantity: float
    average_entry_price: float
    current_price: float
    unrealized_pnl: float
    asset_type: str = "stock"


class AccountBalance(BaseModel):
    currency: str = "USD"
    cash: float
    buying_power: float
    portfolio_value: float
    unrealized_pnl: float = 0.0
