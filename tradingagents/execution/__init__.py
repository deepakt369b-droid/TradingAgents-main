"""Trading Execution Package for TradingAgents.

Provides unified trade execution across US Equities (Alpaca), Global Markets (IBKR),
Crypto (CCXT - Binance, Coinbase, KuCoin, Bybit), and Paper Trading sandbox.
"""

from .order_models import Order, OrderResult, OrderSide, OrderType, Position, AccountBalance
from .base_executor import BaseExecutor
from .paper_executor import PaperExecutor
from .executor_factory import create_executor
from .risk_guards import RiskGuards

__all__ = [
    "Order",
    "OrderResult",
    "OrderSide",
    "OrderType",
    "Position",
    "AccountBalance",
    "BaseExecutor",
    "PaperExecutor",
    "create_executor",
    "RiskGuards",
]
