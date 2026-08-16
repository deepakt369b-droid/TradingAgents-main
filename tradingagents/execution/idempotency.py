"""Deterministic client order IDs for idempotent order submission.

LangGraph restarts a node from the top on resume (see the project's resume
work), and a worker tick can itself be retried after a crash between "the
graph finished" and "the order was recorded." Deriving the order ID
deterministically from what the decision is *about* -- not a random UUID --
means a duplicate submission attempt produces the identical ID every time,
so the local order ledger (and, as defense in depth, the broker's own
duplicate-ID rejection where it supports one) can recognize and skip it
instead of double-submitting.
"""

from __future__ import annotations

import hashlib


def derive_client_order_id(thread_id: str, ticker: str, trade_date: str) -> str:
    """Return a stable, broker-safe client order ID for one decision.

    Keyed on the same ``thread_id`` the checkpoint/run-registry already use
    (see ``graph.checkpointer.thread_id``) plus ticker/date -- NOT side.
    One completed graph run (one thread_id) produces exactly one trading
    decision for one ticker+date, so the ID represents "the order for this
    decision," not a (decision, side) pair. Deriving it from side as well
    was tried and reverted: SignalBridge determines side dynamically from
    the *current* portfolio delta, and checking the ledger only after that
    computation meant a retry that arrived at a since-converged position
    (delta ~0, so no side to compute) silently returned None instead of the
    original recorded result -- the opposite of idempotent. Dropping side
    lets the ledger check run first, before any position/target logic.

    Most broker APIs cap client order IDs at a modest length and require it
    be alphanumeric-ish, so this returns a short hex digest rather than a
    raw concatenated string.
    """
    raw = f"{thread_id}:{ticker.upper()}:{trade_date}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"ta-{digest}"
