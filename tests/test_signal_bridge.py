"""Tests for SignalBridge: rating -> deterministic target position -> RiskGuards
-> executor (Phase 4b). Uses PaperExecutor as the concrete executor since
SignalBridge is executor-agnostic and this exercises real order placement,
not a mock.
"""

import pytest

from tradingagents.execution.approval_gate import ApprovalGate
from tradingagents.execution.approval_store import ApprovalStore
from tradingagents.execution.live_gate import kill_switch_path
from tradingagents.execution.order_models import OrderSide, OrderStatus
from tradingagents.execution.paper_executor import PaperExecutor
from tradingagents.execution.risk_guards import RiskGuards
from tradingagents.execution.signal_bridge import SignalBridge


def _bridge(tmp_path, initial_cash=100000.0, risk_guards=None, target_pct=None):
    executor = PaperExecutor(initial_cash=initial_cash, data_dir=tmp_path)
    return SignalBridge(executor, data_dir=tmp_path, risk_guards=risk_guards, target_pct=target_pct), executor


@pytest.mark.unit
class TestSignalBridgeBasicSizing:
    def test_hold_places_no_order(self, tmp_path):
        bridge, executor = _bridge(tmp_path)
        result = bridge.execute_signal("AAPL", "2026-04-20", "thread-1", "Hold", reference_price=150.0)
        assert result is None
        assert executor.get_positions() == []

    def test_buy_targets_5pct_of_portfolio(self, tmp_path):
        bridge, executor = _bridge(tmp_path, initial_cash=100000.0)
        result = bridge.execute_signal("AAPL", "2026-04-20", "thread-1", "Buy", reference_price=150.0)
        assert result.status == OrderStatus.FILLED
        assert result.side == OrderSide.BUY
        # 5% of 100,000 = 5,000 -> 5000/150 shares
        assert result.quantity == pytest.approx(5000.0 / 150.0, rel=1e-6)

    def test_overweight_targets_smaller_position_than_buy(self, tmp_path):
        bridge, _ = _bridge(tmp_path / "buy", initial_cash=100000.0)
        buy_result = bridge.execute_signal("AAPL", "2026-04-20", "thread-1", "Buy", reference_price=150.0)
        bridge2, _ = _bridge(tmp_path / "ow", initial_cash=100000.0)
        ow_result = bridge2.execute_signal("MSFT", "2026-04-20", "thread-2", "Overweight", reference_price=150.0)
        assert ow_result.quantity < buy_result.quantity

    def test_sell_exits_full_position(self, tmp_path):
        executor = PaperExecutor(initial_cash=100000.0, data_dir=tmp_path)
        bridge = SignalBridge(executor, data_dir=tmp_path)
        bridge.execute_signal("AAPL", "2026-04-20", "thread-1", "Buy", reference_price=150.0)
        held_qty = executor.get_positions()[0].quantity

        result = bridge.execute_signal("AAPL", "2026-04-21", "thread-2", "Sell", reference_price=160.0)
        assert result.status == OrderStatus.FILLED
        assert result.side == OrderSide.SELL
        assert result.quantity == pytest.approx(held_qty)
        assert executor.get_positions() == []

    def test_underweight_trims_but_does_not_exit(self, tmp_path):
        executor = PaperExecutor(initial_cash=100000.0, data_dir=tmp_path)
        bridge = SignalBridge(executor, data_dir=tmp_path)
        bridge.execute_signal("AAPL", "2026-04-20", "thread-1", "Buy", reference_price=150.0)

        result = bridge.execute_signal("AAPL", "2026-04-21", "thread-2", "Underweight", reference_price=150.0)
        assert result.status == OrderStatus.FILLED
        assert result.side == OrderSide.SELL
        remaining = executor.get_positions()[0].quantity
        assert remaining > 0  # trimmed, not exited

    def test_already_at_target_places_no_order(self, tmp_path):
        executor = PaperExecutor(initial_cash=100000.0, data_dir=tmp_path)
        bridge = SignalBridge(executor, data_dir=tmp_path)
        bridge.execute_signal("AAPL", "2026-04-20", "thread-1", "Buy", reference_price=150.0)

        # Re-signaling "Buy" at the same price/equity should be a no-op --
        # already at the 5% target weight.
        result = bridge.execute_signal("AAPL", "2026-04-21", "thread-2", "Buy", reference_price=150.0)
        assert result is None

    def test_custom_target_pct_overrides_default(self, tmp_path):
        bridge, executor = _bridge(tmp_path, initial_cash=100000.0, target_pct={"Buy": 0.10})
        result = bridge.execute_signal("AAPL", "2026-04-20", "thread-1", "Buy", reference_price=150.0)
        assert result.quantity == pytest.approx(10000.0 / 150.0, rel=1e-6)


@pytest.mark.unit
class TestSignalBridgeIdempotency:
    def test_same_thread_id_does_not_double_submit(self, tmp_path):
        executor = PaperExecutor(initial_cash=100000.0, data_dir=tmp_path)
        bridge = SignalBridge(executor, data_dir=tmp_path)
        r1 = bridge.execute_signal("AAPL", "2026-04-20", "thread-1", "Buy", reference_price=150.0)
        r2 = bridge.execute_signal("AAPL", "2026-04-20", "thread-1", "Buy", reference_price=150.0)
        assert r1.order_id == r2.order_id
        # Only one fill's worth of shares held -- the "retry" was a no-op.
        assert executor.get_positions()[0].quantity == pytest.approx(5000.0 / 150.0, rel=1e-6)

    def test_survives_bridge_recreation_same_data_dir(self, tmp_path):
        executor = PaperExecutor(initial_cash=100000.0, data_dir=tmp_path)
        bridge1 = SignalBridge(executor, data_dir=tmp_path)
        r1 = bridge1.execute_signal("AAPL", "2026-04-20", "thread-1", "Buy", reference_price=150.0)

        bridge2 = SignalBridge(executor, data_dir=tmp_path)  # simulates a new worker tick
        r2 = bridge2.execute_signal("AAPL", "2026-04-20", "thread-1", "Buy", reference_price=150.0)
        assert r1.order_id == r2.order_id


@pytest.mark.unit
class TestSignalBridgeSafety:
    def test_kill_switch_blocks_order(self, tmp_path):
        executor = PaperExecutor(initial_cash=100000.0, data_dir=tmp_path)
        bridge = SignalBridge(executor, data_dir=tmp_path)
        kill_switch_path(tmp_path).touch()

        result = bridge.execute_signal("AAPL", "2026-04-20", "thread-1", "Buy", reference_price=150.0)
        assert result is None
        assert executor.get_positions() == []

    def test_risk_guard_rejection_returns_rejected_result_not_none(self, tmp_path):
        executor = PaperExecutor(initial_cash=100000.0, data_dir=tmp_path)
        guards = RiskGuards(max_position_pct=0.01)  # 1% cap, well under the 5% Buy target
        bridge = SignalBridge(executor, data_dir=tmp_path, risk_guards=guards)

        result = bridge.execute_signal("AAPL", "2026-04-20", "thread-1", "Buy", reference_price=150.0)
        assert result is not None
        assert result.status == OrderStatus.REJECTED
        assert executor.get_positions() == []

    def test_blacklisted_symbol_rejected(self, tmp_path):
        executor = PaperExecutor(initial_cash=100000.0, data_dir=tmp_path)
        guards = RiskGuards(blacklisted_symbols=["AAPL"])
        bridge = SignalBridge(executor, data_dir=tmp_path, risk_guards=guards)

        result = bridge.execute_signal("AAPL", "2026-04-20", "thread-1", "Buy", reference_price=150.0)
        assert result.status == OrderStatus.REJECTED
        assert "blacklisted" in result.message.lower()


@pytest.mark.unit
class TestSignalBridgeApprovalGate:
    def test_no_gate_submits_immediately(self, tmp_path):
        """Default (no approval_gate passed) behaves exactly like before
        approval existed -- a risk-checked order submits right away."""
        executor = PaperExecutor(initial_cash=100000.0, data_dir=tmp_path)
        bridge = SignalBridge(executor, data_dir=tmp_path)
        result = bridge.execute_signal("AAPL", "2026-04-20", "thread-1", "Buy", reference_price=150.0)
        assert result.status == OrderStatus.FILLED

    def test_enabled_gate_defers_order_and_writes_no_ledger_entry(self, tmp_path):
        executor = PaperExecutor(initial_cash=100000.0, data_dir=tmp_path)
        gate = ApprovalGate(ApprovalStore(tmp_path), enabled=True)
        bridge = SignalBridge(executor, data_dir=tmp_path, approval_gate=gate, platform="paper")

        result = bridge.execute_signal("AAPL", "2026-04-20", "thread-1", "Buy", reference_price=150.0)
        assert result.status == OrderStatus.PENDING_APPROVAL
        assert executor.get_positions() == []
        from tradingagents.execution.order_ledger import OrderLedger
        assert OrderLedger(tmp_path).get(result.order_id) is None

    def test_gate_only_asked_after_risk_guards_pass(self, tmp_path):
        """A risk-guard rejection must never reach the approval gate at
        all -- an operator should only ever be asked about orders that
        already passed every automated safety check."""
        executor = PaperExecutor(initial_cash=100000.0, data_dir=tmp_path)
        guards = RiskGuards(blacklisted_symbols=["AAPL"])
        store = ApprovalStore(tmp_path)
        gate = ApprovalGate(store, enabled=True)
        bridge = SignalBridge(executor, data_dir=tmp_path, risk_guards=guards, approval_gate=gate, platform="paper")

        result = bridge.execute_signal("AAPL", "2026-04-20", "thread-1", "Buy", reference_price=150.0)
        assert result.status == OrderStatus.REJECTED
        assert store.list_pending() == []

    def test_disabled_gate_submits_like_no_gate(self, tmp_path):
        executor = PaperExecutor(initial_cash=100000.0, data_dir=tmp_path)
        gate = ApprovalGate(ApprovalStore(tmp_path), enabled=False)
        bridge = SignalBridge(executor, data_dir=tmp_path, approval_gate=gate, platform="paper")

        result = bridge.execute_signal("AAPL", "2026-04-20", "thread-1", "Buy", reference_price=150.0)
        assert result.status == OrderStatus.FILLED

    def test_kill_switch_still_blocks_before_approval_gate(self, tmp_path):
        executor = PaperExecutor(initial_cash=100000.0, data_dir=tmp_path)
        gate = ApprovalGate(ApprovalStore(tmp_path), enabled=True)
        bridge = SignalBridge(executor, data_dir=tmp_path, approval_gate=gate, platform="paper")
        kill_switch_path(tmp_path).touch()

        result = bridge.execute_signal("AAPL", "2026-04-20", "thread-1", "Buy", reference_price=150.0)
        assert result is None
        assert ApprovalStore(tmp_path).list_pending() == []
