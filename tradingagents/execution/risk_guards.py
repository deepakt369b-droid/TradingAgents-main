"""Pre-Trade Risk Guards & Portfolio Protection Circuit Breaker."""

from __future__ import annotations

import logging
from typing import Tuple
from .order_models import AccountBalance, Order, Position

logger = logging.getLogger(__name__)


class RiskGuards:
    """Pre-trade risk validator protecting portfolio capital."""

    def __init__(
        self,
        max_position_pct: float = 0.05,        # max 5% of portfolio per asset
        max_daily_loss_pct: float = 0.02,      # 2% daily loss circuit breaker
        max_open_positions: int = 10,
        blacklisted_symbols: list[str] | None = None,
    ):
        self.max_position_pct = max_position_pct
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_open_positions = max_open_positions
        self.blacklisted_symbols = set(blacklisted_symbols or [])

    def validate_order(
        self,
        order: Order,
        account: AccountBalance,
        positions: list[Position],
        estimated_price: float = 100.0,
    ) -> Tuple[bool, str]:
        """Validate if an order complies with risk rules before submitting."""

        # 1. Blacklist check
        if order.symbol.upper() in self.blacklisted_symbols:
            return False, f"Symbol '{order.symbol}' is blacklisted by risk rules."

        # 2. Maximum open positions limit
        if len(positions) >= self.max_open_positions and order.symbol not in [p.symbol for p in positions]:
            return False, f"Open positions limit reached ({self.max_open_positions}). Order rejected."

        # 3. Position size limit (% of total portfolio)
        trade_value = order.quantity * (order.price or estimated_price)
        max_allowed_value = account.portfolio_value * self.max_position_pct

        if trade_value > max_allowed_value and account.portfolio_value > 0:
            return False, (
                f"Order value (${trade_value:.2f}) exceeds maximum position limit of "
                f"{self.max_position_pct * 100:.1f}% of portfolio (${max_allowed_value:.2f})."
            )

        # 4. Daily Drawdown Circuit Breaker
        if account.unrealized_pnl < -(account.portfolio_value * self.max_daily_loss_pct):
            logger.critical("RISK CIRCUIT BREAKER TRIPPED! Daily drawdown exceeds limit (%.1f%%).", self.max_daily_loss_pct * 100)
            return False, "Daily loss limit circuit breaker tripped! All new trades suspended."

        return True, "Order validated successfully."
