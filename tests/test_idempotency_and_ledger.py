"""Tests for deterministic client_order_id derivation and the order ledger (Phase 4a)."""

import pytest

from tradingagents.execution.idempotency import derive_client_order_id
from tradingagents.execution.order_ledger import OrderLedger


@pytest.mark.unit
class TestDeriveClientOrderId:
    def test_deterministic(self):
        a = derive_client_order_id("thread-1", "AAPL", "2026-04-20")
        b = derive_client_order_id("thread-1", "AAPL", "2026-04-20")
        assert a == b

    def test_differs_by_thread_id(self):
        a = derive_client_order_id("thread-1", "AAPL", "2026-04-20")
        b = derive_client_order_id("thread-2", "AAPL", "2026-04-20")
        assert a != b

    def test_differs_by_ticker(self):
        a = derive_client_order_id("thread-1", "AAPL", "2026-04-20")
        b = derive_client_order_id("thread-1", "MSFT", "2026-04-20")
        assert a != b

    def test_differs_by_date(self):
        a = derive_client_order_id("thread-1", "AAPL", "2026-04-20")
        b = derive_client_order_id("thread-1", "AAPL", "2026-04-21")
        assert a != b

    def test_not_keyed_by_side(self):
        # Deliberately NOT differentiated by side (see idempotency.py's
        # docstring): one thread_id = one decision = one order, and
        # SignalBridge needs to check the ledger before it knows the side.
        a = derive_client_order_id("thread-1", "AAPL", "2026-04-20")
        b = derive_client_order_id("thread-1", "AAPL", "2026-04-20")
        assert a == b

    def test_case_insensitive_ticker(self):
        a = derive_client_order_id("thread-1", "aapl", "2026-04-20")
        b = derive_client_order_id("thread-1", "AAPL", "2026-04-20")
        assert a == b

    def test_starts_with_stable_prefix(self):
        assert derive_client_order_id("t", "AAPL", "2026-04-20").startswith("ta-")


@pytest.mark.unit
class TestOrderLedger:
    def test_get_returns_none_when_never_recorded(self, tmp_path):
        ledger = OrderLedger(tmp_path)
        assert ledger.get("ta-nonexistent") is None

    def test_record_then_get_roundtrips(self, tmp_path):
        ledger = OrderLedger(tmp_path)
        result = {"order_id": "ta-abc", "symbol": "AAPL", "side": "buy", "status": "filled", "quantity": 10.0}
        ledger.record("ta-abc", "AAPL", "2026-04-20", "buy", "PaperExecutor", result)
        assert ledger.get("ta-abc") == result

    def test_record_overwrites_on_conflict(self, tmp_path):
        ledger = OrderLedger(tmp_path)
        ledger.record("ta-abc", "AAPL", "2026-04-20", "buy", "PaperExecutor", {"status": "pending"})
        ledger.record("ta-abc", "AAPL", "2026-04-20", "buy", "PaperExecutor", {"status": "filled"})
        assert ledger.get("ta-abc") == {"status": "filled"}

    def test_persists_across_instances(self, tmp_path):
        first = OrderLedger(tmp_path)
        first.record("ta-abc", "AAPL", "2026-04-20", "buy", "PaperExecutor", {"status": "filled"})
        second = OrderLedger(tmp_path)
        assert second.get("ta-abc") == {"status": "filled"}
