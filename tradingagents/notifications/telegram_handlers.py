"""Dispatch for incoming Telegram updates (webhook or long-poll).

Kept as plain functions over data (an update dict in, a list of client calls
made) rather than a class wired to a live bot, so this is unit-testable
without a network -- construct a fake update dict, call ``handle_update``,
and assert on what the fake ``TelegramClient``/``ApprovalStore`` recorded.

Security is enforced here, not at the FastAPI route: every update is
checked against the configured chat-id allowlist before anything else runs.
A webhook secret-token check (the ``X-Telegram-Bot-Api-Secret-Token``
header) is the route's job since it's HTTP-transport-specific; this module
additionally never trusts the chat id on its own, because a leaked bot
token would otherwise let anyone who finds the bot approve trades.
"""

from __future__ import annotations

import logging
from typing import Any

from tradingagents.execution.approval_store import ApprovalStore
from tradingagents.execution.live_gate import is_kill_switch_active, kill_switch_path

from .telegram_client import TelegramClient

logger = logging.getLogger(__name__)


def _allowed_chat_ids(config: dict) -> set[str]:
    raw = config.get("telegram_allowed_chat_ids") or []
    if isinstance(raw, str):
        raw = [c.strip() for c in raw.split(",") if c.strip()]
    return {str(c) for c in raw}


def _is_authorized(chat_id: Any, config: dict) -> bool:
    allowed = _allowed_chat_ids(config)
    # Empty allowlist means "not yet bound to a chat" -- /start is still
    # answered (it's how the operator discovers their chat id to add to the
    # allowlist), but every other command/callback is refused.
    return str(chat_id) in allowed


_STATUS_ICONS = {
    "approved": "✅ APPROVED -- submitting shortly.",
    "rejected": "❌ REJECTED",
    "expired": "⌛ EXPIRED -- no order was placed (unanswered in time).",
}


def format_decision_message(proposal: dict, status: str) -> str:
    """Render the post-decision message that replaces a proposal's buttons.

    ``status`` is explicit (not inferred from ``decided_by``) because both a
    reject and an approve can come from the same "telegram:<chat_id>"
    actor -- inferring from who decided rather than what they decided
    previously mislabeled every reject as "APPROVED".
    """
    icon = _STATUS_ICONS.get(status, status.upper())
    return (
        f"{icon}\n\n"
        f"*{proposal['ticker']}* {proposal['side'].upper()} "
        f"{proposal['quantity']:.4f} @ ~${proposal['reference_price']:.2f}\n"
        f"Rating: {proposal['rating']}"
    )


def format_proposal_message(proposal: dict) -> str:
    return (
        f"🔔 *Trade proposal* -- awaiting approval\n\n"
        f"*{proposal['ticker']}* ({proposal['asset_type']}) on *{proposal['platform']}*\n"
        f"Rating: *{proposal['rating']}*\n"
        f"Side: *{proposal['side'].upper()}*\n"
        f"Quantity: {proposal['quantity']:.4f}\n"
        f"Reference price: ${proposal['reference_price']:.2f}\n"
        f"Trade date: {proposal['trade_date']}\n\n"
        f"Reply with the buttons below, or it auto-expires and is skipped."
    )


def handle_callback_query(
    update: dict, client: TelegramClient, store: ApprovalStore, config: dict
) -> None:
    cq = update["callback_query"]
    callback_id = cq["id"]
    chat_id = cq["message"]["chat"]["id"]
    message_id = cq["message"]["message_id"]
    data = cq.get("data", "")

    if not _is_authorized(chat_id, config):
        client.answer_callback_query(callback_id, "Not authorized.")
        logger.warning("Telegram callback from unauthorized chat_id=%s ignored.", chat_id)
        return

    if ":" not in data:
        client.answer_callback_query(callback_id, "Unrecognized action.")
        return
    action, approval_id = data.split(":", 1)

    if action == "appr":
        row = store.approve(approval_id, decided_by=f"telegram:{chat_id}")
        status, ack = "approved", "Approved -- submitting shortly."
    elif action == "rej":
        row = store.reject(approval_id, decided_by=f"telegram:{chat_id}")
        status, ack = "rejected", "Rejected."
    else:
        client.answer_callback_query(callback_id, "Unrecognized action.")
        return

    client.answer_callback_query(callback_id, ack)

    if row is None:
        # Already decided -- a double-tap, or it expired between render and
        # tap. Row is None so re-fetch to show the current state honestly.
        row = store.get(approval_id)
        if row is None:
            return
        client.edit_message_text(
            str(chat_id), str(message_id),
            f"(already {row['status']})\n\n" + format_decision_message(row["proposal"], row["status"]),
        )
        return

    client.edit_message_text(
        str(chat_id), str(message_id), format_decision_message(row["proposal"], status),
    )


def handle_command(update: dict, client: TelegramClient, store: ApprovalStore, config: dict) -> None:
    msg = update["message"]
    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()
    command = text.split()[0].split("@")[0] if text else ""

    if command == "/start":
        client.send_message(
            str(chat_id),
            f"Your chat id is `{chat_id}`. Add it to `TELEGRAM_ALLOWED_CHAT_IDS` "
            "to receive and act on trade proposals from this bot.",
        )
        return

    if not _is_authorized(chat_id, config):
        client.send_message(str(chat_id), "Not authorized.")
        logger.warning("Telegram command from unauthorized chat_id=%s ignored.", chat_id)
        return

    if command == "/pending":
        pending = store.list_pending()
        if not pending:
            client.send_message(str(chat_id), "No pending trade proposals.")
            return
        lines = [
            f"• {p['ticker']} {p['side'].upper()} {p['quantity']:.4f} (rating: {p['rating']})"
            for p in pending
        ]
        client.send_message(str(chat_id), "*Pending proposals:*\n" + "\n".join(lines))

    elif command == "/kill":
        data_dir = config.get("data_cache_dir")
        path = kill_switch_path(data_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("halted via telegram /kill", encoding="utf-8")
        client.send_message(str(chat_id), "🛑 Kill switch ACTIVATED. No new orders will be placed.")

    elif command == "/resume":
        data_dir = config.get("data_cache_dir")
        path = kill_switch_path(data_dir)
        if path.exists():
            path.unlink()
        client.send_message(str(chat_id), "✅ Kill switch cleared. Trading resumed.")

    elif command == "/status":
        data_dir = config.get("data_cache_dir")
        halted = is_kill_switch_active(data_dir)
        client.send_message(
            str(chat_id),
            f"Platform: {config.get('execution_platform', 'paper')}\n"
            f"Kill switch: {'🛑 ACTIVE' if halted else '✅ clear'}\n"
            f"Pending approvals: {len(store.list_pending())}",
        )

    elif command == "/help":
        client.send_message(
            str(chat_id),
            "/pending -- list proposals awaiting approval\n"
            "/status -- platform, kill switch, pending count\n"
            "/kill -- halt all new order submission\n"
            "/resume -- clear the kill switch\n"
            "/help -- this message",
        )


def handle_update(update: dict, client: TelegramClient, store: ApprovalStore, config: dict) -> None:
    """Route one Telegram update dict to the right handler. Never raises --
    a malformed update is logged and dropped, since this sits on the
    request path of a public webhook."""
    try:
        if "callback_query" in update:
            handle_callback_query(update, client, store, config)
        elif "message" in update and (update["message"].get("text") or "").startswith("/"):
            handle_command(update, client, store, config)
    except Exception:
        logger.exception("Failed to handle Telegram update: %s", update)
