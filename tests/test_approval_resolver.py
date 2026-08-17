"""Tests for approval_resolver.resolve_pending: expiry never executes, and
risk guards are re-checked at submission time (not just at proposal time)."""

import pytest

from tradingagents.execution.approval_gate import ApprovalGate
from tradingagents.execution.approval_resolver import resolve_pending
from tradingagents.execution.approval_store import ApprovalStore
from tradingagents.execution.order_ledger import OrderLedger
from tradingagents.execution.order_models import Order, OrderSide
from tradingagents.execution.paper_executor import PaperExecutor
from tradingagents.execution.signal_bridge import SignalBridge


class _FakeNotifier:
    is_configured = True

    def __init__(self):
        self.edits = []

    def edit_message_text(self, chat_id, message_id, text, reply_markup=None, parse_mode="Markdown"):
        self.edits.append((chat_id, message_id, text))
        return {"ok": True}


def _config(tmp_path, platform="paper"):
    return {"data_cache_dir": str(tmp_path), "execution_platform": platform}


def _propose_via_bridge(tmp_path, config, side="Buy", ticker="AAPL", price=150.0):
    """Drive a proposal through the same path production code uses
    (SignalBridge -> ApprovalGate), so the resolver is exercised against a
    realistically-shaped stored proposal rather than a hand-built dict."""
    executor = PaperExecutor(initial_cash=100000.0, data_dir=tmp_path)
    store = ApprovalStore(tmp_path)
    gate = ApprovalGate(store, enabled=True)
    bridge = SignalBridge(executor, data_dir=tmp_path, approval_gate=gate, platform=config["execution_platform"])
    result = bridge.execute_signal(ticker, "2026-04-20", "thread-1", side, reference_price=price)
    assert result.status.value == "pending_approval"
    return store, executor


@pytest.mark.unit
class TestResolvePendingExpiry:
    def test_expired_proposal_is_never_submitted(self, tmp_path):
        config = _config(tmp_path)
        store, executor = _propose_via_bridge(tmp_path, config)
        # Force it overdue by rewriting expires_at through the same store API.
        row = store.list_pending()[0]
        # Simulate elapsed time by forcing the deadline into the past
        # directly in the DB (ApprovalStore has no public "backdate" API).
        import sqlite3
        conn = sqlite3.connect(str(tmp_path / "execution" / "approvals.db"))
        conn.execute("UPDATE approvals SET expires_at = 0 WHERE approval_id = ?", (row["approval_id"],))
        conn.commit()
        conn.close()

        counts = resolve_pending(config, store=store, notifier=None)
        assert counts["expired"] == 1
        assert counts["executed"] == 0
        assert executor.get_positions() == []
        assert store.get(row["approval_id"])["status"] == "expired"

    def test_expiry_edits_telegram_message_when_attached(self, tmp_path):
        config = _config(tmp_path)
        store, _ = _propose_via_bridge(tmp_path, config)
        row = store.list_pending()[0]
        store.attach_message(row["approval_id"], "12345", "999")

        import sqlite3
        conn = sqlite3.connect(str(tmp_path / "execution" / "approvals.db"))
        conn.execute("UPDATE approvals SET expires_at = 0 WHERE approval_id = ?", (row["approval_id"],))
        conn.commit()
        conn.close()

        notifier = _FakeNotifier()
        resolve_pending(config, store=store, notifier=notifier)
        assert len(notifier.edits) == 1
        assert notifier.edits[0][0] == "12345"


@pytest.mark.unit
class TestResolvePendingSubmission:
    def test_approved_proposal_is_submitted_and_ledgered(self, tmp_path):
        config = _config(tmp_path)
        store, executor = _propose_via_bridge(tmp_path, config)
        row = store.list_pending()[0]
        store.approve(row["approval_id"], decided_by="telegram:1")

        counts = resolve_pending(config, store=store, notifier=None)
        assert counts["executed"] == 1
        assert executor.get_positions()[0].symbol == "AAPL"
        ledger = OrderLedger(tmp_path)
        assert ledger.get(row["approval_id"]) is not None
        assert store.get(row["approval_id"])["status"] == "executed"

    def test_approved_but_now_unsafe_order_is_marked_failed_not_submitted(self, tmp_path, monkeypatch):
        """Balances can move between proposal and approval -- the resolver
        must re-validate against RiskGuards, not just trust the earlier
        pass."""
        config = _config(tmp_path)
        store, executor = _propose_via_bridge(tmp_path, config)
        row = store.list_pending()[0]
        store.approve(row["approval_id"], decided_by="telegram:1")

        from tradingagents.execution import risk_guards as risk_guards_module

        def _always_reject(self, order, account, positions, estimated_price=100.0):
            return False, "simulated drawdown circuit breaker"

        monkeypatch.setattr(risk_guards_module.RiskGuards, "validate_order", _always_reject)

        counts = resolve_pending(config, store=store, notifier=None)
        assert counts["failed"] == 1
        assert counts["executed"] == 0
        assert executor.get_positions() == []
        row_after = store.get(row["approval_id"])
        assert row_after["status"] == "failed"
        assert "simulated drawdown" in row_after["proposal"]["failure_reason"]

    def test_pending_proposal_not_yet_approved_is_left_alone(self, tmp_path):
        config = _config(tmp_path)
        store, executor = _propose_via_bridge(tmp_path, config)
        counts = resolve_pending(config, store=store, notifier=None)
        assert counts == {"expired": 0, "executed": 0, "failed": 0}
        assert executor.get_positions() == []

    def test_resolve_is_idempotent_on_repeated_calls(self, tmp_path):
        config = _config(tmp_path)
        store, executor = _propose_via_bridge(tmp_path, config)
        row = store.list_pending()[0]
        store.approve(row["approval_id"], decided_by="telegram:1")

        first = resolve_pending(config, store=store, notifier=None)
        second = resolve_pending(config, store=store, notifier=None)
        assert first["executed"] == 1
        assert second == {"expired": 0, "executed": 0, "failed": 0}
        # Only one fill's worth of shares -- no double submission on replay.
        assert len(executor.get_positions()) == 1
