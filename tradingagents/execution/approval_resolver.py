"""Out-of-band submission of approved trade proposals.

Approval decisions arrive asynchronously -- a Telegram button tap or a
browser click, both handled on a request path that has no reason to know
about brokers, risk guards, or the order ledger. ``resolve_pending`` is the
single place, run on a periodic poll (see ``app/worker.py`` and
``app/server.py``), that turns an APPROVED proposal into an actual order.
Keeping submission out of the approval-handling code path is also what
keeps it single-writer -- see ``approval_gate.GateResult``'s docstring for
why ``ApprovalGate`` itself never submits, and why a retried
``SignalBridge.execute_signal`` call must not either.

Risk guards run again here, not just once in ``SignalBridge``: account
balances move while an operator is deliberating, so an order that was safe
to *propose* an hour ago might not be safe to *submit* now.
"""

from __future__ import annotations

import logging
from typing import Any

from .approval_store import ApprovalStore
from .executor_factory import create_executor
from .order_ledger import OrderLedger
from .order_models import Order, OrderSide, OrderType
from .risk_guards import RiskGuards

logger = logging.getLogger(__name__)


def _order_from_proposal(proposal: dict[str, Any]) -> Order:
    return Order(
        symbol=proposal["symbol"],
        side=OrderSide(proposal["side"]),
        quantity=proposal["quantity"],
        order_type=OrderType(proposal.get("order_type", "market")),
        price=proposal.get("price"),
        stop_price=proposal.get("stop_price"),
        asset_type=proposal.get("asset_type", "stock"),
        client_order_id=proposal.get("client_order_id"),
    )


def _edit_decision_message(notifier: Any, row: dict, text: str) -> None:
    if notifier is None or not row.get("chat_id") or not row.get("message_id"):
        return
    try:
        notifier.edit_message_text(
            str(row["chat_id"]), str(row["message_id"]), text,
            reply_markup={"inline_keyboard": []},
        )
    except Exception:
        logger.exception("Failed to edit Telegram message for approval %s.", row["approval_id"])


def _submit_one(store: ApprovalStore, notifier: Any, config: dict, row: dict) -> str:
    """Submit one APPROVED proposal. Returns 'executed' or 'failed'."""
    approval_id = row["approval_id"]
    try:
        order = _order_from_proposal(row["proposal"])
        platform = row["platform"]
        executor = create_executor(platform, config=config)

        account = executor.get_account_balance()
        positions = executor.get_positions()
        valid, reason = RiskGuards().validate_order(
            order, account, positions, estimated_price=row["reference_price"],
        )
        if not valid:
            store.mark_failed(approval_id, reason)
            _edit_decision_message(
                notifier, row, f"⚠️ Approved but re-validation failed: {reason}",
            )
            return "failed"

        result = executor.place_order(order)
        OrderLedger(config["data_cache_dir"]).record(
            approval_id, row["ticker"], row["trade_date"], row["side"],
            platform=platform, order_result=result.model_dump(mode="json"),
        )
        store.mark_executed(approval_id)
        filled = result.filled_quantity or result.quantity
        _edit_decision_message(
            notifier, row,
            f"✅ EXECUTED\n\n{row['ticker']} {row['side'].upper()} {filled:.4f} "
            f"(status={result.status.value})",
        )
        return "executed"
    except Exception as exc:
        logger.exception("Failed to submit approved order %s.", approval_id)
        store.mark_failed(approval_id, str(exc))
        _edit_decision_message(notifier, row, f"⚠️ Approved but submission failed: {exc}")
        return "failed"


def resolve_pending(
    config: dict, store: ApprovalStore | None = None, notifier: Any | None = None,
) -> dict[str, int]:
    """Expire overdue proposals and submit every APPROVED one.

    Idempotent and safe to call on a short interval (see the 30s worker/
    server jobs): a crash mid-call just means the same rows are picked up
    again next tick, since nothing moves out of PENDING/APPROVED until its
    terminal state is durably written.

    Returns ``{"expired": n, "executed": n, "failed": n}`` for observability
    and tests.
    """
    if notifier is None:
        from tradingagents.notifications.telegram_client import TelegramClient
        notifier = TelegramClient(config.get("telegram_bot_token"))

    data_dir = config["data_cache_dir"]
    store = store or ApprovalStore(data_dir)

    counts = {"expired": 0, "executed": 0, "failed": 0}

    for row in store.expire_overdue():
        counts["expired"] += 1
        _edit_decision_message(
            notifier, row, "⌛ EXPIRED -- no order was placed (unanswered in time).",
        )

    for row in store.list_approved():
        outcome = _submit_one(store, notifier, config, row)
        counts[outcome] += 1

    return counts
