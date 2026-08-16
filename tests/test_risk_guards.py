"""Tests for RiskGuards.validate_order (Phase 4a/4b).

Includes a regression test for a bug found while wiring RiskGuards into
SignalBridge: the position-size cap was blocking SELL orders that reduced
or exited an oversized position -- exactly backwards, since a guard meant
to prevent oversized exposure should never block the trade that reduces it.
"""

import pytest

from tradingagents.execution.order_models import AccountBalance, Order, OrderSide, Position
from tradingagents.execution.risk_guards import RiskGuards


def _account(portfolio_value=100000.0, unrealized_pnl=0.0):
    return AccountBalance(
        cash=portfolio_value, buying_power=portfolio_value,
        portfolio_value=portfolio_value, unrealized_pnl=unrealized_pnl,
    )


@pytest.mark.unit
class TestPositionSizeLimit:
    def test_buy_within_limit_passes(self):
        guards = RiskGuards(max_position_pct=0.05)
        order = Order(symbol="AAPL", side=OrderSide.BUY, quantity=10, price=100.0)  # $1000, 1%
        valid, _ = guards.validate_order(order, _account(), [])
        assert valid is True

    def test_buy_over_limit_rejected(self):
        guards = RiskGuards(max_position_pct=0.05)
        order = Order(symbol="TSLA", side=OrderSide.BUY, quantity=100, price=200.0)  # $20,000, 20%
        valid, reason = guards.validate_order(order, _account(), [])
        assert valid is False
        assert "exceeds maximum position limit" in reason

    def test_sell_over_limit_value_is_never_rejected_on_size_alone(self):
        # Regression: exiting an oversized position (e.g. one that grew past
        # the cap through price appreciation) must not be blocked by the
        # position-size guard -- that would trap the account in the exact
        # position this guard exists to prevent.
        guards = RiskGuards(max_position_pct=0.05)
        held = [Position(
            symbol="NVDA", quantity=100, average_entry_price=100.0,
            current_price=300.0, unrealized_pnl=20000.0,
        )]
        order = Order(symbol="NVDA", side=OrderSide.SELL, quantity=100, price=300.0)  # $30,000, 30%
        valid, reason = guards.validate_order(order, _account(), held)
        assert valid is True
        assert reason == "Order validated successfully."

    def test_sell_still_blocked_by_blacklist(self):
        # The SELL exemption is specific to the position-size check -- other
        # guards (blacklist, circuit breaker) still apply to sells.
        guards = RiskGuards(blacklisted_symbols=["NVDA"])
        order = Order(symbol="NVDA", side=OrderSide.SELL, quantity=10, price=300.0)
        valid, reason = guards.validate_order(order, _account(), [])
        assert valid is False
        assert "blacklisted" in reason.lower()


@pytest.mark.unit
class TestOtherGuards:
    def test_max_open_positions_blocks_new_symbol(self):
        guards = RiskGuards(max_open_positions=1)
        held = [Position(symbol="AAPL", quantity=1, average_entry_price=100, current_price=100, unrealized_pnl=0)]
        order = Order(symbol="MSFT", side=OrderSide.BUY, quantity=1, price=100.0)
        valid, reason = guards.validate_order(order, _account(), held)
        assert valid is False
        assert "Open positions limit" in reason

    def test_max_open_positions_allows_adding_to_existing_symbol(self):
        guards = RiskGuards(max_open_positions=1, max_position_pct=1.0)
        held = [Position(symbol="AAPL", quantity=1, average_entry_price=100, current_price=100, unrealized_pnl=0)]
        order = Order(symbol="AAPL", side=OrderSide.BUY, quantity=1, price=100.0)
        valid, _ = guards.validate_order(order, _account(), held)
        assert valid is True

    def test_daily_loss_circuit_breaker_blocks_all_trades(self):
        guards = RiskGuards(max_daily_loss_pct=0.02)
        account = _account(portfolio_value=100000.0, unrealized_pnl=-3000.0)  # -3% > 2% limit
        order = Order(symbol="AAPL", side=OrderSide.BUY, quantity=1, price=100.0)
        valid, reason = guards.validate_order(order, account, [])
        assert valid is False
        assert "circuit breaker" in reason.lower()
