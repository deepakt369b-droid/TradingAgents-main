"""Deterministic bridge from an analysis run's rating to a broker order.

rating + account equity + config -> target position (non-LLM) -> RiskGuards
-> executor. The LLM must never be the last thing before order submission:
sizing here is a fixed lookup table on the 5-tier rating
(``agents.utils.rating.RATINGS_5_TIER``), never parsed out of a model's free
-text reasoning (``TraderProposal.position_sizing`` is a string like "5% of
portfolio" meant for a human reader, and ``PortfolioDecision`` carries no
quantity at all).
"""

from __future__ import annotations

import logging
from typing import Any

from .approval_gate import ApprovalGate
from .base_executor import BaseExecutor
from .idempotency import derive_client_order_id
from .live_gate import is_kill_switch_active
from .order_ledger import OrderLedger
from .order_models import Order, OrderResult, OrderSide, OrderStatus, OrderType
from .risk_guards import RiskGuards

logger = logging.getLogger(__name__)

# Target portfolio weight per 5-tier rating. None = no rebalancing action at
# all (Hold means "leave the position exactly as it is", not "target 0%").
# Buy/Overweight are long targets; Underweight/Sell trim or exit. These are
# defaults, overridable via config["position_target_pct"] (a dict with the
# same keys) for a different risk appetite.
DEFAULT_TARGET_PCT: dict[str, float | None] = {
    "Buy": 0.05,
    "Overweight": 0.025,
    "Hold": None,
    "Underweight": 0.01,
    "Sell": 0.0,
}

# Below this fraction of portfolio value, a rebalancing delta is treated as
# noise (rounding, stale price) rather than a real trade -- avoids placing
# a $3 order because the target and current weight differ by a hair.
MIN_TRADE_VALUE = 25.0


class SignalBridge:
    """Turns a completed run's rating into an order, or a documented no-op."""

    def __init__(
        self,
        executor: BaseExecutor,
        data_dir: str,
        risk_guards: RiskGuards | None = None,
        target_pct: dict[str, float | None] | None = None,
        approval_gate: ApprovalGate | None = None,
        platform: str | None = None,
    ):
        self.executor = executor
        self.data_dir = data_dir
        self.risk_guards = risk_guards or RiskGuards()
        self.target_pct = {**DEFAULT_TARGET_PCT, **(target_pct or {})}
        self.ledger = OrderLedger(data_dir)
        # None means "no approval gate at all" (always submit immediately),
        # distinct from an ApprovalGate constructed with enabled=False --
        # both behave the same today, but keeping the attribute optional
        # lets a caller that never wired Telegram skip importing it.
        self.approval_gate = approval_gate
        self.platform = platform or type(executor).__name__

    def execute_signal(
        self,
        ticker: str,
        trade_date: str,
        thread_id: str,
        rating: str,
        reference_price: float,
        asset_type: str = "stock",
    ) -> OrderResult | None:
        """Place (or skip) an order for one completed analysis run.

        ``reference_price`` is the caller-supplied current market price for
        ``ticker`` -- this bridge is a pure sizing/routing/safety layer, not
        a market-data fetcher, so it takes price as an input rather than
        querying one itself. ``thread_id`` should be the same one the
        checkpointer/run-registry use for this ticker+date (see
        ``graph.checkpointer.thread_id``), so the derived client_order_id is
        stable across a resumed run or a retried worker tick.

        Returns the ``OrderResult`` if an order was placed (or already had
        been -- idempotent), or ``None`` if no action was taken (Hold,
        already at target weight, kill switch active, or risk-guard
        rejection -- all logged with the specific reason).
        """
        if is_kill_switch_active(self.data_dir):
            logger.warning(
                "Kill switch active -- skipping order for %s on %s (rating=%s).",
                ticker, trade_date, rating,
            )
            return None

        # Idempotency check runs FIRST, before any position/target
        # computation: a genuine retry (resumed run, retried worker tick)
        # must always return the originally recorded result, even if the
        # position has since converged to target and a fresh computation
        # would see delta≈0 and no side to determine (see idempotency.py's
        # docstring for why client_order_id doesn't encode side).
        client_order_id = derive_client_order_id(thread_id, ticker, trade_date)
        existing = self.ledger.get(client_order_id)
        if existing is not None:
            logger.info(
                "Order for %s on %s already placed (client_order_id=%s); skipping resubmission.",
                ticker, trade_date, client_order_id,
            )
            return OrderResult(**existing)

        target = self.target_pct.get(rating)
        if target is None:
            logger.info("No rebalancing action for %s on %s (rating=%s).", ticker, trade_date, rating)
            return None

        account = self.executor.get_account_balance()
        positions = self.executor.get_positions()
        current_position = next((p for p in positions if p.symbol == ticker), None)
        current_value = current_position.quantity * reference_price if current_position else 0.0

        target_value = target * account.portfolio_value
        delta_value = target_value - current_value

        if abs(delta_value) < MIN_TRADE_VALUE:
            logger.info(
                "%s on %s already within target weight (delta=$%.2f); no order placed.",
                ticker, trade_date, delta_value,
            )
            return None

        side = OrderSide.BUY if delta_value > 0 else OrderSide.SELL
        quantity = abs(delta_value) / reference_price
        # A SELL can never exceed the held quantity -- rounding on the
        # target-value side must not manufacture a short position.
        if side == OrderSide.SELL and current_position:
            quantity = min(quantity, current_position.quantity)

        order = Order(
            symbol=ticker,
            side=side,
            quantity=quantity,
            order_type=OrderType.MARKET,
            asset_type=asset_type,
            client_order_id=client_order_id,
        )

        valid, reason = self.risk_guards.validate_order(
            order, account, positions, estimated_price=reference_price,
        )
        if not valid:
            logger.warning(
                "Risk guard rejected order for %s on %s: %s", ticker, trade_date, reason,
            )
            return OrderResult(
                order_id=client_order_id, symbol=ticker, side=side,
                status=OrderStatus.REJECTED, quantity=quantity, message=reason,
            )

        # Human-in-the-loop gate, deliberately the last check before
        # submission: only orders that already passed idempotency, sizing,
        # and risk guards are ever surfaced for approval, so a Telegram tap
        # only has to answer "do I want this trade," not "is this safe."
        if self.approval_gate is not None:
            gate_result = self.approval_gate.request(
                approval_id=client_order_id, order=order, ticker=ticker,
                trade_date=trade_date, thread_id=thread_id, rating=rating,
                reference_price=reference_price, platform=self.platform,
            )
            if gate_result.outcome == "pending":
                logger.info(
                    "Order for %s on %s awaiting approval (approval_id=%s); not yet submitted.",
                    ticker, trade_date, client_order_id,
                )
                return OrderResult(
                    order_id=client_order_id, symbol=ticker, side=side,
                    status=OrderStatus.PENDING_APPROVAL, quantity=quantity,
                    message="Awaiting operator approval.",
                )
            if gate_result.outcome == "rejected":
                logger.info(
                    "Order for %s on %s was rejected or expired at approval (approval_id=%s).",
                    ticker, trade_date, client_order_id,
                )
                return OrderResult(
                    order_id=client_order_id, symbol=ticker, side=side,
                    status=OrderStatus.REJECTED, quantity=quantity,
                    message="Rejected by operator (or expired unanswered).",
                )
            # outcome == "approved" -- falls through to submission below.

        result = self.executor.place_order(order)
        self.ledger.record(
            client_order_id, ticker, trade_date, side.value,
            platform=type(self.executor).__name__, order_result=result.model_dump(mode="json"),
        )
        logger.info(
            "Order placed for %s on %s: %s %.4f @ ~$%.2f (status=%s, client_order_id=%s).",
            ticker, trade_date, side.value, quantity, reference_price, result.status.value, client_order_id,
        )
        return result
