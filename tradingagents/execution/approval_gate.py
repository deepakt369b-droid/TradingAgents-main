"""Human-in-the-loop gate between a risk-checked order and broker submission.

Sits in ``SignalBridge.execute_signal`` after risk guards pass and before
``executor.place_order`` runs. When approval is required, this only ever
*writes a proposal and notifies* -- it never blocks waiting for a decision,
since the caller (a scheduled worker tick, or a WebSocket-driven UI run)
must return promptly either way. The actual submission happens later, out
of band, via ``approval_resolver.resolve_pending`` once the proposal's
status has moved to APPROVED (see that module for why this is a separate
poll loop rather than a callback).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .approval_store import ApprovalStore
from .order_models import Order

logger = logging.getLogger(__name__)


@dataclass
class GateResult:
    # "approved": gate disabled entirely -- no proposal row is ever created,
    #   so it is safe for the caller to submit inline, right here.
    # "pending": awaiting a decision, OR already APPROVED/EXECUTED but not
    #   yet submitted by this call -- once a proposal has entered the
    #   approval lifecycle, ``approval_resolver.resolve_pending`` is the
    #   ONLY code path allowed to call ``executor.place_order`` for it. A
    #   caller must never submit on an "approved" row itself: that would
    #   let a retried worker tick race the resolver into a double
    #   submission (the ledger idempotency check that normally prevents
    #   this hasn't fired yet, because nothing has been recorded to the
    #   ledger during the pending-approval window).
    # "rejected": rejected or expired -- never submit.
    outcome: str
    approval_id: str


class ApprovalGate:
    """Requires operator sign-off (via Telegram or the UI) before an order
    reaches a broker, unless approval is disabled in config."""

    def __init__(
        self,
        store: ApprovalStore,
        notifier: Any | None = None,
        chat_id: str | None = None,
        timeout_minutes: float = 60.0,
        enabled: bool = True,
    ):
        self.store = store
        self.notifier = notifier
        self.chat_id = chat_id
        self.timeout_minutes = timeout_minutes
        self.enabled = enabled

    def request(
        self,
        approval_id: str,
        order: Order,
        ticker: str,
        trade_date: str,
        thread_id: str,
        rating: str,
        reference_price: float,
        platform: str,
    ) -> GateResult:
        if not self.enabled:
            return GateResult(outcome="approved", approval_id=approval_id)

        # The stored proposal carries both the raw order fields (needed by
        # the resolver to reconstruct an Order for submission) and the
        # display fields (needed by telegram_handlers to render/re-render
        # the message) in one dict, so callers never have to reassemble
        # context from separate columns.
        proposal = order.model_dump(mode="json") | {
            "ticker": ticker, "trade_date": trade_date, "rating": rating,
            "reference_price": reference_price, "platform": platform,
        }
        row = self.store.create(
            approval_id=approval_id,
            ticker=ticker,
            trade_date=trade_date,
            thread_id=thread_id,
            rating=rating,
            side=order.side.value,
            quantity=order.quantity,
            reference_price=reference_price,
            asset_type=order.asset_type,
            platform=platform,
            proposal=proposal,
            timeout_minutes=self.timeout_minutes,
        )

        # create() is idempotent -- a pre-existing row (retry) is returned
        # as-is rather than re-notified. Only notify on a genuinely new
        # PENDING row, not on a replay of an already-decided one.
        from .approval_store import PENDING
        if row["status"] == PENDING and row.get("chat_id") is None and self.notifier is not None:
            self._notify(row)

        if row["status"] in ("rejected", "expired", "failed"):
            return GateResult(outcome="rejected", approval_id=approval_id)
        # PENDING, APPROVED, and EXECUTED all resolve to "pending" here --
        # submission for a decided proposal belongs solely to the resolver.
        # See GateResult's docstring for why this is a single-writer rule.
        return GateResult(outcome="pending", approval_id=approval_id)

    def _notify(self, row: dict) -> None:
        from tradingagents.notifications.telegram_client import approval_keyboard
        from tradingagents.notifications.telegram_handlers import format_proposal_message

        if not self.chat_id or not getattr(self.notifier, "is_configured", False):
            return
        try:
            resp = self.notifier.send_message(
                self.chat_id,
                format_proposal_message(row["proposal"]),
                reply_markup=approval_keyboard(row["approval_id"]),
            )
            if resp and resp.get("ok"):
                message_id = str(resp["result"]["message_id"])
                self.store.attach_message(row["approval_id"], str(self.chat_id), message_id)
        except Exception:
            logger.exception("Failed to send Telegram approval notification for %s.", row["approval_id"])
