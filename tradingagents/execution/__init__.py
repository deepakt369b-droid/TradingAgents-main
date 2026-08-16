"""Trading Execution Package for TradingAgents.

Provides unified trade execution across US Equities (Alpaca), Global Markets (IBKR),
Crypto (CCXT - Binance, Coinbase, KuCoin, Bybit), and Paper Trading sandbox.
"""

from .order_models import Order, OrderResult, OrderSide, OrderType, Position, AccountBalance
from .base_executor import BaseExecutor
from .paper_executor import PaperExecutor
from .executor_factory import create_executor
from .risk_guards import RiskGuards
from .live_gate import is_kill_switch_active, is_live_trading_enabled, kill_switch_path
from .idempotency import derive_client_order_id
from .order_ledger import OrderLedger
from .signal_bridge import SignalBridge

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
    "is_kill_switch_active",
    "is_live_trading_enabled",
    "kill_switch_path",
    "derive_client_order_id",
    "OrderLedger",
    "SignalBridge",
]
