"""Tests for ApprovalStore: transitions, double-tap idempotency, expiry."""

import time

import pytest

from tradingagents.execution.approval_store import ApprovalStore


def _create(store, approval_id="ta-1", timeout_minutes=60.0, **overrides):
    kwargs = dict(
        approval_id=approval_id,
        ticker="AAPL",
        trade_date="2026-04-20",
        thread_id="thread-1",
        rating="Buy",
        side="buy",
        quantity=10.0,
        reference_price=150.0,
        asset_type="stock",
        platform="paper",
        proposal={"symbol": "AAPL", "side": "buy", "quantity": 10.0},
        timeout_minutes=timeout_minutes,
    )
    kwargs.update(overrides)
    return store.create(**kwargs)


@pytest.mark.unit
class TestApprovalStoreCreate:
    def test_create_returns_pending_row(self, tmp_path):
        store = ApprovalStore(tmp_path)
        row = _create(store)
        assert row["status"] == "pending"
        assert row["ticker"] == "AAPL"
        assert row["proposal"]["symbol"] == "AAPL"

    def test_create_is_idempotent_on_approval_id(self, tmp_path):
        store = ApprovalStore(tmp_path)
        row1 = _create(store)
        row2 = _create(store, quantity=999.0)  # different args, same id
        assert row1["created_at"] == row2["created_at"]
        assert row2["quantity"] == 10.0  # first write wins, not the retry's

    def test_get_missing_returns_none(self, tmp_path):
        store = ApprovalStore(tmp_path)
        assert store.get("nope") is None


@pytest.mark.unit
class TestApprovalStoreTransitions:
    def test_approve_moves_pending_to_approved(self, tmp_path):
        store = ApprovalStore(tmp_path)
        _create(store)
        row = store.approve("ta-1", decided_by="telegram:1")
        assert row["status"] == "approved"
        assert row["decided_by"] == "telegram:1"

    def test_reject_moves_pending_to_rejected(self, tmp_path):
        store = ApprovalStore(tmp_path)
        _create(store)
        row = store.reject("ta-1", decided_by="telegram:1")
        assert row["status"] == "rejected"

    def test_double_approve_is_noop_on_second_call(self, tmp_path):
        store = ApprovalStore(tmp_path)
        _create(store)
        first = store.approve("ta-1", decided_by="telegram:1")
        second = store.approve("ta-1", decided_by="telegram:2")
        assert first is not None
        assert second is None  # already approved -- the double-tap does nothing
        assert store.get("ta-1")["decided_by"] == "telegram:1"

    def test_reject_after_approve_is_noop(self, tmp_path):
        store = ApprovalStore(tmp_path)
        _create(store)
        store.approve("ta-1", decided_by="telegram:1")
        result = store.reject("ta-1", decided_by="telegram:2")
        assert result is None
        assert store.get("ta-1")["status"] == "approved"

    def test_mark_executed_requires_approved_first(self, tmp_path):
        store = ApprovalStore(tmp_path)
        _create(store)
        # Still PENDING -- mark_executed should not apply.
        assert store.mark_executed("ta-1") is None
        store.approve("ta-1", decided_by="telegram:1")
        row = store.mark_executed("ta-1")
        assert row["status"] == "executed"

    def test_mark_failed_records_reason(self, tmp_path):
        store = ApprovalStore(tmp_path)
        _create(store)
        store.approve("ta-1", decided_by="telegram:1")
        row = store.mark_failed("ta-1", "risk guard rejected")
        assert row["status"] == "failed"
        assert row["proposal"]["failure_reason"] == "risk guard rejected"


@pytest.mark.unit
class TestApprovalStoreQueries:
    def test_list_pending_excludes_decided(self, tmp_path):
        store = ApprovalStore(tmp_path)
        _create(store, approval_id="ta-1")
        _create(store, approval_id="ta-2")
        store.approve("ta-2", decided_by="telegram:1")
        pending = store.list_pending()
        assert [r["approval_id"] for r in pending] == ["ta-1"]

    def test_list_approved_only_returns_approved(self, tmp_path):
        store = ApprovalStore(tmp_path)
        _create(store, approval_id="ta-1")
        _create(store, approval_id="ta-2")
        store.approve("ta-1", decided_by="telegram:1")
        approved = store.list_approved()
        assert [r["approval_id"] for r in approved] == ["ta-1"]

    def test_list_recent_orders_newest_first(self, tmp_path):
        store = ApprovalStore(tmp_path)
        _create(store, approval_id="ta-1")
        time.sleep(0.01)
        _create(store, approval_id="ta-2")
        recent = store.list_recent()
        assert recent[0]["approval_id"] == "ta-2"


@pytest.mark.unit
class TestApprovalStoreExpiry:
    def test_expire_overdue_moves_pending_past_deadline(self, tmp_path):
        store = ApprovalStore(tmp_path)
        _create(store, timeout_minutes=-1.0)  # already expired on creation
        expired = store.expire_overdue()
        assert [r["approval_id"] for r in expired] == ["ta-1"]
        assert store.get("ta-1")["status"] == "expired"
        assert store.get("ta-1")["decided_by"] == "system:timeout"

    def test_expire_overdue_never_touches_approved(self, tmp_path):
        store = ApprovalStore(tmp_path)
        _create(store, timeout_minutes=-1.0)
        store.approve("ta-1", decided_by="telegram:1")
        expired = store.expire_overdue()
        assert expired == []
        assert store.get("ta-1")["status"] == "approved"

    def test_not_yet_overdue_stays_pending(self, tmp_path):
        store = ApprovalStore(tmp_path)
        _create(store, timeout_minutes=60.0)
        expired = store.expire_overdue()
        assert expired == []
        assert store.get("ta-1")["status"] == "pending"
