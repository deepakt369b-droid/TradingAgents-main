"""Thin REST client for the Telegram Bot API.

Deliberately a plain ``requests``-based HTTP wrapper, not a bot framework
(``python-telegram-bot``/``aiogram``): the only operations this system needs
are "send a message with two inline buttons," "acknowledge a button tap,"
and "strip the buttons off a decided message" -- three POST calls the Bot
API exposes directly. Pulling in a framework's event loop and dispatcher
would mean either a second long-running process or wiring FastAPI's asyncio
loop through a sync-first codebase for no functional gain.

Mirrors ``integrations/ai_trader_client.py``'s contract: unconfigured (no
token) makes every method a documented no-op, and a Telegram-side failure is
logged, never raised -- a notification integration failing must never take
down the trading pipeline it's reporting on.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 10.0
_API_BASE = "https://api.telegram.org/bot"


class TelegramClient:
    """Sync wrapper around the subset of the Telegram Bot API this app uses.

    ``bot_token`` is the token from @BotFather. All methods are no-ops
    (return None) when ``bot_token`` is empty, so this is safe to construct
    and call unconditionally with an unconfigured config.
    """

    def __init__(self, bot_token: str | None = None, timeout: float = _DEFAULT_TIMEOUT):
        self.bot_token = bot_token or ""
        self.timeout = timeout

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token)

    def _url(self, method: str) -> str:
        return f"{_API_BASE}{self.bot_token}/{method}"

    def _post(self, method: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        if not self.is_configured:
            logger.debug("TelegramClient not configured; skipping %s.", method)
            return None
        try:
            resp = requests.post(self._url(method), json=payload, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            logger.warning("TelegramClient: %s failed: %s", method, exc)
            return None

    def send_message(
        self,
        chat_id: str,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str = "Markdown",
    ) -> dict[str, Any] | None:
        """Send a message, optionally with an inline keyboard.

        Returns the parsed ``sendMessage`` response (contains
        ``result.message_id``, needed later to edit/strip the keyboard), or
        None if unconfigured or the request failed.
        """
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return self._post("sendMessage", payload)

    def edit_message_text(
        self,
        chat_id: str,
        message_id: str,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str = "Markdown",
    ) -> dict[str, Any] | None:
        """Edit an existing message -- used to strip the Approve/Reject
        buttons and show the decision, so a message can never be acted on
        twice from the Telegram side."""
        payload: dict[str, Any] = {
            "chat_id": chat_id, "message_id": message_id,
            "text": text, "parse_mode": parse_mode,
        }
        payload["reply_markup"] = reply_markup or {"inline_keyboard": []}
        return self._post("editMessageText", payload)

    def answer_callback_query(
        self, callback_query_id: str, text: str | None = None
    ) -> dict[str, Any] | None:
        """Acknowledge a button tap. Telegram shows a loading spinner on the
        button until this is called (or ~10s pass), so this must be called
        promptly -- before any slower work like re-checking risk guards."""
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        return self._post("answerCallbackQuery", payload)

    def set_webhook(self, url: str, secret_token: str | None = None) -> dict[str, Any] | None:
        payload: dict[str, Any] = {"url": url}
        if secret_token:
            payload["secret_token"] = secret_token
        return self._post("setWebhook", payload)

    def get_updates(self, offset: int | None = None, timeout: int = 0) -> dict[str, Any] | None:
        """Long-poll fallback for local dev, where there's no public URL for
        a webhook. Not used when a webhook is configured."""
        payload: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            payload["offset"] = offset
        return self._post("getUpdates", payload)


def approval_keyboard(approval_id: str) -> dict[str, Any]:
    """Build the Approve/Reject inline keyboard for one proposal.

    ``callback_data`` is capped at 64 bytes by Telegram, so this sends only
    the approval id (already a short ``ta-<24 hex chars>`` id from
    ``idempotency.derive_client_order_id``), never the proposal payload.
    """
    return {
        "inline_keyboard": [[
            {"text": "✅ Approve", "callback_data": f"appr:{approval_id}"},
            {"text": "❌ Reject", "callback_data": f"rej:{approval_id}"},
        ]]
    }
