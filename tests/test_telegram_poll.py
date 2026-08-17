"""Tests for the local-dev Telegram polling fallback (app/telegram_poll.py):
offset persistence across calls, so a restart doesn't reprocess or drop
updates."""

import pytest

from app.telegram_poll import _load_offset, _save_offset, poll_once
from tradingagents.execution.approval_store import ApprovalStore


class _FakeClient:
    def __init__(self, batches):
        self._batches = list(batches)
        self.calls = []

    def get_updates(self, offset=None, timeout=0):
        self.calls.append(offset)
        if not self._batches:
            return {"ok": True, "result": []}
        return {"ok": True, "result": self._batches.pop(0)}


def _config(tmp_path):
    return {"data_cache_dir": str(tmp_path), "telegram_allowed_chat_ids": "111"}


@pytest.mark.unit
class TestOffsetPersistence:
    def test_offset_starts_unset(self, tmp_path):
        assert _load_offset(str(tmp_path)) is None

    def test_save_then_load_roundtrips(self, tmp_path):
        _save_offset(str(tmp_path), 42)
        assert _load_offset(str(tmp_path)) == 42


@pytest.mark.unit
class TestPollOnce:
    def test_processes_updates_and_advances_offset(self, tmp_path):
        config = _config(tmp_path)
        store = ApprovalStore(tmp_path)
        batch = [{"update_id": 5, "message": {"chat": {"id": 111}, "text": "/status"}}]
        client = _FakeClient([batch])

        n = poll_once(client, store, config)
        assert n == 1
        assert _load_offset(str(tmp_path)) == 6  # next offset = last update_id + 1

    def test_second_poll_uses_saved_offset(self, tmp_path):
        config = _config(tmp_path)
        store = ApprovalStore(tmp_path)
        client = _FakeClient([
            [{"update_id": 5, "message": {"chat": {"id": 111}, "text": "/status"}}],
            [],
        ])
        poll_once(client, store, config)
        poll_once(client, store, config)
        assert client.calls == [None, 6]

    def test_no_updates_leaves_offset_untouched(self, tmp_path):
        config = _config(tmp_path)
        store = ApprovalStore(tmp_path)
        client = _FakeClient([[]])
        n = poll_once(client, store, config)
        assert n == 0
        assert _load_offset(str(tmp_path)) is None

    def test_failed_response_is_handled_gracefully(self, tmp_path):
        config = _config(tmp_path)
        store = ApprovalStore(tmp_path)

        class _BadClient:
            def get_updates(self, offset=None, timeout=0):
                return None

        n = poll_once(_BadClient(), store, config)
        assert n == 0
