"""Tests for PaperExecutor's SQLite persistence and client_order_id idempotency
(Phase 4a: state used to be in-memory only and was lost on every container
restart/redeploy, destroying the paper track record the live-trading
promotion gate depends on)."""

import pytest

from tradingagents.execution.order_models import Order, OrderSide, OrderStatus
from tradingagents.execution.paper_executor import PaperExecutor


@pytest.mark.unit
class TestPaperExecutorPersistence:
    def test_state_survives_a_new_executor_instance(self, tmp_path):
        # Simulates a container restart: a brand-new PaperExecutor pointed
        # at the same data_dir must see the prior instance's state.
        first = PaperExecutor(initial_cash=10000.0, data_dir=tmp_path)
        first.place_order(Order(symbol="AAPL", side=OrderSide.BUY, quantity=10, price=150.0))

        second = PaperExecutor(initial_cash=10000.0, data_dir=tmp_path)
        acc = second.get_account_balance()
        assert acc.cash == 10000.0 - 1500.0
        positions = second.get_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "AAPL"
        assert positions[0].quantity == 10

    def test_initial_cash_only_applies_on_first_creation(self, tmp_path):
        # A restart must NOT reset cash back to initial_cash -- that would
        # silently erase realized P&L on every redeploy.
        first = PaperExecutor(initial_cash=10000.0, data_dir=tmp_path)
        first.place_order(Order(symbol="AAPL", side=OrderSide.BUY, quantity=10, price=150.0))

        second = PaperExecutor(initial_cash=99999.0, data_dir=tmp_path)  # different value
        assert second.get_account_balance().cash == 10000.0 - 1500.0

    def test_sell_updates_persisted_position(self, tmp_path):
        executor = PaperExecutor(initial_cash=10000.0, data_dir=tmp_path)
        executor.place_order(Order(symbol="AAPL", side=OrderSide.BUY, quantity=10, price=150.0))
        executor.place_order(Order(symbol="AAPL", side=OrderSide.SELL, quantity=4, price=160.0))

        reopened = PaperExecutor(data_dir=tmp_path)
        positions = reopened.get_positions()
        assert len(positions) == 1
        assert positions[0].quantity == 6

    def test_sell_to_zero_removes_position(self, tmp_path):
        executor = PaperExecutor(initial_cash=10000.0, data_dir=tmp_path)
        executor.place_order(Order(symbol="AAPL", side=OrderSide.BUY, quantity=10, price=150.0))
        executor.place_order(Order(symbol="AAPL", side=OrderSide.SELL, quantity=10, price=160.0))
        assert executor.get_positions() == []

    def test_order_status_persists_across_instances(self, tmp_path):
        first = PaperExecutor(initial_cash=10000.0, data_dir=tmp_path)
        result = first.place_order(Order(symbol="AAPL", side=OrderSide.BUY, quantity=10, price=150.0))

        second = PaperExecutor(data_dir=tmp_path)
        assert second.get_order_status(result.order_id) == OrderStatus.FILLED


@pytest.mark.unit
class TestPaperExecutorIdempotency:
    def test_duplicate_client_order_id_does_not_double_charge(self, tmp_path):
        executor = PaperExecutor(initial_cash=10000.0, data_dir=tmp_path)
        order = Order(
            symbol="AAPL", side=OrderSide.BUY, quantity=10, price=150.0,
            client_order_id="ta-abc123",
        )
        first_result = executor.place_order(order)
        second_result = executor.place_order(order)  # simulated retry / resumed re-submission

        assert first_result.order_id == second_result.order_id == "ta-abc123"
        # Only ONE fill's worth of cash was deducted, not two.
        assert executor.get_account_balance().cash == 10000.0 - 1500.0
        assert executor.get_positions()[0].quantity == 10

    def test_different_client_order_ids_both_execute(self, tmp_path):
        executor = PaperExecutor(initial_cash=10000.0, data_dir=tmp_path)
        executor.place_order(Order(
            symbol="AAPL", side=OrderSide.BUY, quantity=10, price=150.0,
            client_order_id="ta-order-1",
        ))
        executor.place_order(Order(
            symbol="AAPL", side=OrderSide.BUY, quantity=5, price=150.0,
            client_order_id="ta-order-2",
        ))
        assert executor.get_positions()[0].quantity == 15

    def test_idempotency_check_survives_new_instance(self, tmp_path):
        # The dedup must work even after a restart -- it's checking a
        # persisted ledger, not an in-memory dict.
        first = PaperExecutor(initial_cash=10000.0, data_dir=tmp_path)
        order = Order(
            symbol="AAPL", side=OrderSide.BUY, quantity=10, price=150.0,
            client_order_id="ta-abc123",
        )
        first.place_order(order)

        second = PaperExecutor(data_dir=tmp_path)
        second.place_order(order)  # retry after "restart"
        assert second.get_account_balance().cash == 10000.0 - 1500.0

    def test_no_client_order_id_never_dedups(self, tmp_path):
        # Without an explicit client_order_id, each call is treated as a
        # genuinely new order (auto-generated UUID-based IDs) -- this is the
        # caller's responsibility to set for idempotency, not implicit.
        executor = PaperExecutor(initial_cash=100000.0, data_dir=tmp_path)
        order = Order(symbol="AAPL", side=OrderSide.BUY, quantity=1, price=100.0)
        r1 = executor.place_order(order)
        r2 = executor.place_order(order)
        assert r1.order_id != r2.order_id
        assert executor.get_positions()[0].quantity == 2
