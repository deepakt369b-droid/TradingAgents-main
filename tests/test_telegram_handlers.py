"""Tests for telegram_handlers: callback parsing, chat-id allowlist
enforcement, and command dispatch. No network -- TelegramClient is a fake
that just records calls."""

import pytest

from tradingagents.execution.approval_store import ApprovalStore
from tradingagents.execution.live_gate import kill_switch_path
from tradingagents.notifications.telegram_handlers import (
    format_decision_message,
    handle_command,
    handle_callback_query,
    handle_update,
)


class _FakeClient:
    def __init__(self):
        self.answered = []
        self.edited = []
        self.sent = []

    def answer_callback_query(self, callback_query_id, text=None):
        self.answered.append((callback_query_id, text))

    def edit_message_text(self, chat_id, message_id, text, reply_markup=None, parse_mode="Markdown"):
        self.edited.append((chat_id, message_id, text))

    def send_message(self, chat_id, text, reply_markup=None, parse_mode="Markdown"):
        self.sent.append((chat_id, text))


def _config(tmp_path, allowed=("111",)):
    return {
        "data_cache_dir": str(tmp_path),
        "telegram_allowed_chat_ids": ",".join(allowed),
        "execution_platform": "paper",
    }


def _seed_proposal(store, approval_id="ta-1"):
    return store.create(
        approval_id=approval_id, ticker="AAPL", trade_date="2026-04-20", thread_id="thread-1",
        rating="Buy", side="buy", quantity=10.0, reference_price=150.0, asset_type="stock",
        platform="paper", proposal={
            "symbol": "AAPL", "side": "buy", "quantity": 10.0, "ticker": "AAPL",
            "trade_date": "2026-04-20", "rating": "Buy", "reference_price": 150.0, "platform": "paper",
        },
        timeout_minutes=60.0,
    )


@pytest.mark.unit
class TestFormatDecisionMessage:
    def test_approved_and_rejected_render_different_text(self):
        proposal = {"ticker": "AAPL", "side": "buy", "quantity": 10.0, "reference_price": 150.0, "rating": "Buy"}
        approved = format_decision_message(proposal, "approved")
        rejected = format_decision_message(proposal, "rejected")
        assert "APPROVED" in approved
        assert "REJECTED" in rejected
        assert approved != rejected


@pytest.mark.unit
class TestCallbackAuthorization:
    def test_unauthorized_chat_id_is_ignored(self, tmp_path):
        store = ApprovalStore(tmp_path)
        _seed_proposal(store)
        client = _FakeClient()
        config = _config(tmp_path, allowed=("111",))
        update = {
            "callback_query": {
                "id": "cbq-1", "data": "appr:ta-1",
                "message": {"chat": {"id": 999}, "message_id": 5},
            }
        }
        handle_callback_query(update, client, store, config)
        assert store.get("ta-1")["status"] == "pending"  # untouched
        assert client.answered[0][1] == "Not authorized."

    def test_authorized_approve_transitions_and_strips_buttons(self, tmp_path):
        store = ApprovalStore(tmp_path)
        _seed_proposal(store)
        client = _FakeClient()
        config = _config(tmp_path, allowed=("111",))
        update = {
            "callback_query": {
                "id": "cbq-1", "data": "appr:ta-1",
                "message": {"chat": {"id": 111}, "message_id": 5},
            }
        }
        handle_callback_query(update, client, store, config)
        assert store.get("ta-1")["status"] == "approved"
        assert len(client.edited) == 1
        assert "APPROVED" in client.edited[0][2]

    def test_authorized_reject_transitions_and_shows_rejected(self, tmp_path):
        store = ApprovalStore(tmp_path)
        _seed_proposal(store)
        client = _FakeClient()
        config = _config(tmp_path, allowed=("111",))
        update = {
            "callback_query": {
                "id": "cbq-1", "data": "rej:ta-1",
                "message": {"chat": {"id": 111}, "message_id": 5},
            }
        }
        handle_callback_query(update, client, store, config)
        assert store.get("ta-1")["status"] == "rejected"
        assert "REJECTED" in client.edited[0][2]

    def test_double_tap_second_call_shows_already_decided(self, tmp_path):
        store = ApprovalStore(tmp_path)
        _seed_proposal(store)
        client = _FakeClient()
        config = _config(tmp_path, allowed=("111",))
        update = {
            "callback_query": {
                "id": "cbq-1", "data": "appr:ta-1",
                "message": {"chat": {"id": 111}, "message_id": 5},
            }
        }
        handle_callback_query(update, client, store, config)
        handle_callback_query(update, client, store, config)
        assert len(client.edited) == 2
        assert "already" in client.edited[1][2]

    def test_malformed_callback_data_is_ignored_gracefully(self, tmp_path):
        store = ApprovalStore(tmp_path)
        client = _FakeClient()
        config = _config(tmp_path, allowed=("111",))
        update = {
            "callback_query": {
                "id": "cbq-1", "data": "not-a-valid-format",
                "message": {"chat": {"id": 111}, "message_id": 5},
            }
        }
        handle_callback_query(update, client, store, config)
        assert client.answered[0][1] == "Unrecognized action."


@pytest.mark.unit
class TestCommandDispatch:
    def test_start_replies_even_when_unauthorized(self, tmp_path):
        store = ApprovalStore(tmp_path)
        client = _FakeClient()
        config = _config(tmp_path, allowed=())
        update = {"message": {"chat": {"id": 999}, "text": "/start"}}
        handle_command(update, client, store, config)
        assert len(client.sent) == 1
        assert "999" in client.sent[0][1]

    def test_pending_command_requires_authorization(self, tmp_path):
        store = ApprovalStore(tmp_path)
        client = _FakeClient()
        config = _config(tmp_path, allowed=())
        update = {"message": {"chat": {"id": 999}, "text": "/pending"}}
        handle_command(update, client, store, config)
        assert client.sent[0][1] == "Not authorized."

    def test_kill_creates_kill_switch_file(self, tmp_path):
        store = ApprovalStore(tmp_path)
        client = _FakeClient()
        config = _config(tmp_path, allowed=("111",))
        update = {"message": {"chat": {"id": 111}, "text": "/kill"}}
        handle_command(update, client, store, config)
        assert kill_switch_path(tmp_path).exists()

    def test_resume_clears_kill_switch_file(self, tmp_path):
        store = ApprovalStore(tmp_path)
        client = _FakeClient()
        config = _config(tmp_path, allowed=("111",))
        kill_switch_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
        kill_switch_path(tmp_path).touch()

        update = {"message": {"chat": {"id": 111}, "text": "/resume"}}
        handle_command(update, client, store, config)
        assert not kill_switch_path(tmp_path).exists()

    def test_pending_lists_open_proposals(self, tmp_path):
        store = ApprovalStore(tmp_path)
        _seed_proposal(store)
        client = _FakeClient()
        config = _config(tmp_path, allowed=("111",))
        update = {"message": {"chat": {"id": 111}, "text": "/pending"}}
        handle_command(update, client, store, config)
        assert "AAPL" in client.sent[0][1]


@pytest.mark.unit
class TestHandleUpdateRouting:
    def test_routes_callback_query(self, tmp_path):
        store = ApprovalStore(tmp_path)
        _seed_proposal(store)
        client = _FakeClient()
        config = _config(tmp_path, allowed=("111",))
        update = {
            "callback_query": {
                "id": "cbq-1", "data": "appr:ta-1",
                "message": {"chat": {"id": 111}, "message_id": 5},
            }
        }
        handle_update(update, client, store, config)
        assert store.get("ta-1")["status"] == "approved"

    def test_malformed_update_does_not_raise(self, tmp_path):
        store = ApprovalStore(tmp_path)
        client = _FakeClient()
        config = _config(tmp_path)
        handle_update({"totally": "unexpected"}, client, store, config)  # no exception

    def test_non_command_message_is_ignored(self, tmp_path):
        store = ApprovalStore(tmp_path)
        client = _FakeClient()
        config = _config(tmp_path, allowed=("111",))
        update = {"message": {"chat": {"id": 111}, "text": "just chatting"}}
        handle_update(update, client, store, config)
        assert client.sent == []
