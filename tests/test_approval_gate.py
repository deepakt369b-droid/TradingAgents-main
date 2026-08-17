"""Tests for ApprovalGate: disabled = auto-approve inline; enabled = always
defer to the resolver (see GateResult's docstring in approval_gate.py for
why "approved" is reserved solely for the disabled-gate case)."""

import pytest

from tradingagents.execution.approval_gate import ApprovalGate
from tradingagents.execution.approval_store import ApprovalStore
from tradingagents.execution.order_models import Order, OrderSide


def _order():
    return Order(symbol="AAPL", side=OrderSide.BUY, quantity=10.0, asset_type="stock")


class _FakeNotifier:
    is_configured = True

    def __init__(self):
        self.sent = []

    def send_message(self, chat_id, text, reply_markup=None, parse_mode="Markdown"):
        self.sent.append((chat_id, text, reply_markup))
        return {"ok": True, "result": {"message_id": 42}}


@pytest.mark.unit
class TestApprovalGateDisabled:
    def test_disabled_gate_approves_without_writing_a_row(self, tmp_path):
        store = ApprovalStore(tmp_path)
        gate = ApprovalGate(store, enabled=False)
        result = gate.request(
            approval_id="ta-1", order=_order(), ticker="AAPL", trade_date="2026-04-20",
            thread_id="thread-1", rating="Buy", reference_price=150.0, platform="paper",
        )
        assert result.outcome == "approved"
        assert store.get("ta-1") is None


@pytest.mark.unit
class TestApprovalGateEnabled:
    def test_new_proposal_is_pending_and_notifies(self, tmp_path):
        store = ApprovalStore(tmp_path)
        notifier = _FakeNotifier()
        gate = ApprovalGate(store, notifier=notifier, chat_id="12345", enabled=True)
        result = gate.request(
            approval_id="ta-1", order=_order(), ticker="AAPL", trade_date="2026-04-20",
            thread_id="thread-1", rating="Buy", reference_price=150.0, platform="paper",
        )
        assert result.outcome == "pending"
        row = store.get("ta-1")
        assert row["status"] == "pending"
        assert len(notifier.sent) == 1
        assert row["chat_id"] == "12345"

    def test_retry_on_pending_row_does_not_renotify(self, tmp_path):
        store = ApprovalStore(tmp_path)
        notifier = _FakeNotifier()
        gate = ApprovalGate(store, notifier=notifier, chat_id="12345", enabled=True)
        gate.request(
            approval_id="ta-1", order=_order(), ticker="AAPL", trade_date="2026-04-20",
            thread_id="thread-1", rating="Buy", reference_price=150.0, platform="paper",
        )
        gate.request(
            approval_id="ta-1", order=_order(), ticker="AAPL", trade_date="2026-04-20",
            thread_id="thread-1", rating="Buy", reference_price=150.0, platform="paper",
        )
        assert len(notifier.sent) == 1

    def test_approved_row_still_returns_pending_never_approved(self, tmp_path):
        """Single-writer rule: once a proposal is APPROVED, only the resolver
        may submit it -- a retried SignalBridge call must not fall through
        to place_order itself (see GateResult's docstring)."""
        store = ApprovalStore(tmp_path)
        gate = ApprovalGate(store, enabled=True)
        gate.request(
            approval_id="ta-1", order=_order(), ticker="AAPL", trade_date="2026-04-20",
            thread_id="thread-1", rating="Buy", reference_price=150.0, platform="paper",
        )
        store.approve("ta-1", decided_by="telegram:1")

        result = gate.request(
            approval_id="ta-1", order=_order(), ticker="AAPL", trade_date="2026-04-20",
            thread_id="thread-1", rating="Buy", reference_price=150.0, platform="paper",
        )
        assert result.outcome == "pending"

    def test_rejected_row_returns_rejected(self, tmp_path):
        store = ApprovalStore(tmp_path)
        gate = ApprovalGate(store, enabled=True)
        gate.request(
            approval_id="ta-1", order=_order(), ticker="AAPL", trade_date="2026-04-20",
            thread_id="thread-1", rating="Buy", reference_price=150.0, platform="paper",
        )
        store.reject("ta-1", decided_by="telegram:1")

        result = gate.request(
            approval_id="ta-1", order=_order(), ticker="AAPL", trade_date="2026-04-20",
            thread_id="thread-1", rating="Buy", reference_price=150.0, platform="paper",
        )
        assert result.outcome == "rejected"

    def test_expired_row_returns_rejected(self, tmp_path):
        store = ApprovalStore(tmp_path)
        gate = ApprovalGate(store, enabled=True, timeout_minutes=-1.0)
        gate.request(
            approval_id="ta-1", order=_order(), ticker="AAPL", trade_date="2026-04-20",
            thread_id="thread-1", rating="Buy", reference_price=150.0, platform="paper",
        )
        store.expire_overdue()

        result = gate.request(
            approval_id="ta-1", order=_order(), ticker="AAPL", trade_date="2026-04-20",
            thread_id="thread-1", rating="Buy", reference_price=150.0, platform="paper",
        )
        assert result.outcome == "rejected"

    def test_no_notifier_does_not_raise(self, tmp_path):
        store = ApprovalStore(tmp_path)
        gate = ApprovalGate(store, notifier=None, enabled=True)
        result = gate.request(
            approval_id="ta-1", order=_order(), ticker="AAPL", trade_date="2026-04-20",
            thread_id="thread-1", rating="Buy", reference_price=150.0, platform="paper",
        )
        assert result.outcome == "pending"
