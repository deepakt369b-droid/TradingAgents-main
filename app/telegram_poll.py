"""Local-dev fallback for receiving Telegram updates without a public URL.

Production (Coolify, or any deployment with a real HTTPS domain) should use
the webhook route instead (``POST /api/telegram/webhook``, registered via
Telegram's ``setWebhook`` -- see the setup guide). This script exists only
because a webhook requires Telegram to reach you over the public internet,
which a laptop running ``uvicorn`` on localhost cannot offer. It long-polls
``getUpdates`` instead and feeds each update through the exact same
``handle_update`` dispatcher the webhook route uses, so behavior (approve/
reject, /kill, /status, ...) is identical either way.

Safe to run even if a webhook is ALSO registered -- update handling is
idempotent (approving/rejecting an already-decided proposal is a no-op) --
but there is no reason to run both at once, and Telegram will not deliver
the same update to both a webhook and getUpdates simultaneously (setting a
webhook disables getUpdates delivery until the webhook is removed).

Run: ``python -m app.telegram_poll``
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_OFFSET_FILENAME = "telegram_poll_offset.json"
_POLL_TIMEOUT_SECONDS = 25


def _offset_path(data_dir: str) -> Path:
    return Path(data_dir) / _OFFSET_FILENAME


def _load_offset(data_dir: str) -> int | None:
    path = _offset_path(data_dir)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("offset")
    except (OSError, json.JSONDecodeError):
        return None


def _save_offset(data_dir: str, offset: int) -> None:
    path = _offset_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"offset": offset}), encoding="utf-8")


def poll_once(client, store, config: dict) -> int:
    """Fetch and handle one batch of updates. Returns how many were processed."""
    from tradingagents.notifications.telegram_handlers import handle_update

    data_dir = config["data_cache_dir"]
    offset = _load_offset(data_dir)
    resp = client.get_updates(offset=offset, timeout=_POLL_TIMEOUT_SECONDS)
    if not resp or not resp.get("ok"):
        return 0

    updates = resp.get("result", [])
    for update in updates:
        handle_update(update, client, store, config)
        _save_offset(data_dir, update["update_id"] + 1)
    return len(updates)


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    from app.config_store import apply_to_environment
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.execution import ApprovalStore
    from tradingagents.notifications import TelegramClient

    apply_to_environment()
    config = DEFAULT_CONFIG
    client = TelegramClient(config.get("telegram_bot_token"), timeout=_POLL_TIMEOUT_SECONDS + 10)
    if not client.is_configured:
        logger.error(
            "TELEGRAM_BOT_TOKEN is not set (via .env or the web UI's Telegram "
            "settings) -- nothing to poll. Set it, then re-run."
        )
        return

    store = ApprovalStore(config["data_cache_dir"])
    logger.info("Polling Telegram for updates (Ctrl+C to stop)...")
    while True:
        try:
            n = poll_once(client, store, config)
            if n:
                logger.info("Processed %d Telegram update(s).", n)
        except KeyboardInterrupt:
            break
        except Exception:
            logger.exception("Telegram poll iteration failed; retrying in 5s.")
            time.sleep(5)


if __name__ == "__main__":
    main()
