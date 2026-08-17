"""Durable record of trade proposals awaiting human approval.

Approval happens after ``SignalBridge`` has already sized and risk-checked an
order but before it reaches a broker, so this cannot be a blocked in-process
call: the worker is unattended and a container restart between "proposed"
and "decided" must not silently drop or double-submit a trade. Every state
transition below is persisted to SQLite on the same ``data_dir`` the rest of
the execution package uses (see ``order_ledger.py``), and every transition
is a conditional ``UPDATE ... WHERE status = ?`` so a double-tap (Telegram
button pressed twice, or a Telegram tap racing a browser click) is a no-op
rather than a second state change.

The primary key is the order's ``client_order_id`` (see ``idempotency.py``),
not a random UUID -- one completed graph run produces at most one proposal,
so reusing that id means a retried worker tick that re-reaches the approval
step finds its own prior proposal instead of creating a duplicate.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

# Terminal-from-PENDING states an operator (or the expiry sweep) can move a
# proposal to. EXECUTED/FAILED are further transitions out of APPROVED,
# applied by the resolver once it has actually submitted the order.
PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
EXPIRED = "expired"
EXECUTED = "executed"
FAILED = "failed"


def _db_path(data_dir: str | Path) -> Path:
    p = Path(data_dir) / "execution"
    p.mkdir(parents=True, exist_ok=True)
    return p / "approvals.db"


def _connect(data_dir: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path(data_dir)))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS approvals (
            approval_id TEXT PRIMARY KEY,
            ticker TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            thread_id TEXT NOT NULL,
            rating TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity REAL NOT NULL,
            reference_price REAL NOT NULL,
            asset_type TEXT NOT NULL,
            platform TEXT NOT NULL,
            proposal_json TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            decided_at REAL,
            decided_by TEXT,
            chat_id TEXT,
            message_id TEXT
        )
        """
    )
    conn.commit()
    return conn


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["proposal"] = json.loads(d.pop("proposal_json"))
    return d


class ApprovalStore:
    """SQLite-backed store of trade proposals pending human approval."""

    def __init__(self, data_dir: str | Path):
        self.data_dir = data_dir

    def create(
        self,
        approval_id: str,
        ticker: str,
        trade_date: str,
        thread_id: str,
        rating: str,
        side: str,
        quantity: float,
        reference_price: float,
        asset_type: str,
        platform: str,
        proposal: dict[str, Any],
        timeout_minutes: float,
    ) -> dict[str, Any]:
        """Insert a new PENDING proposal, or return the existing row unchanged.

        Idempotent on ``approval_id``: a retried worker tick that reaches
        this step again (e.g. after a crash before the first attempt's
        Telegram send completed) must see its own prior proposal, not create
        a second one that could be independently approved twice.
        """
        existing = self.get(approval_id)
        if existing is not None:
            return existing

        now = time.time()
        conn = _connect(self.data_dir)
        try:
            conn.execute(
                """
                INSERT INTO approvals (
                    approval_id, ticker, trade_date, thread_id, rating, side,
                    quantity, reference_price, asset_type, platform,
                    proposal_json, status, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    approval_id, ticker.upper(), str(trade_date), thread_id,
                    rating, side.lower(), quantity, reference_price, asset_type,
                    platform, json.dumps(proposal), PENDING, now,
                    now + timeout_minutes * 60,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get(approval_id)

    def get(self, approval_id: str) -> dict[str, Any] | None:
        conn = _connect(self.data_dir)
        try:
            row = conn.execute(
                "SELECT * FROM approvals WHERE approval_id = ?", (approval_id,)
            ).fetchone()
            return _row_to_dict(row) if row else None
        finally:
            conn.close()

    def list_pending(self) -> list[dict[str, Any]]:
        conn = _connect(self.data_dir)
        try:
            rows = conn.execute(
                "SELECT * FROM approvals WHERE status = ? ORDER BY created_at ASC",
                (PENDING,),
            ).fetchall()
            return [_row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def list_approved(self) -> list[dict[str, Any]]:
        """Proposals decided APPROVED but not yet submitted -- the resolver's
        work queue. Rows leave this set the moment ``mark_executed``/
        ``mark_failed`` runs, so a crash mid-resolve just means the same row
        is picked up again on the next poll."""
        conn = _connect(self.data_dir)
        try:
            rows = conn.execute(
                "SELECT * FROM approvals WHERE status = ? ORDER BY decided_at ASC",
                (APPROVED,),
            ).fetchall()
            return [_row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        conn = _connect(self.data_dir)
        try:
            rows = conn.execute(
                "SELECT * FROM approvals ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [_row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def attach_message(self, approval_id: str, chat_id: str, message_id: str) -> None:
        """Record which Telegram message carries this proposal's buttons, so
        the handler can edit/strip them on decision without a second send."""
        conn = _connect(self.data_dir)
        try:
            conn.execute(
                "UPDATE approvals SET chat_id = ?, message_id = ? WHERE approval_id = ?",
                (chat_id, message_id, approval_id),
            )
            conn.commit()
        finally:
            conn.close()

    def _transition(
        self, approval_id: str, from_status: str, to_status: str, decided_by: str
    ) -> dict[str, Any] | None:
        """Move a proposal from ``from_status`` to ``to_status`` iff it is
        still in ``from_status``. Returns the updated row, or None if the
        transition didn't apply (already decided -- a double-tap)."""
        conn = _connect(self.data_dir)
        try:
            cur = conn.execute(
                """
                UPDATE approvals SET status = ?, decided_at = ?, decided_by = ?
                WHERE approval_id = ? AND status = ?
                """,
                (to_status, time.time(), decided_by, approval_id, from_status),
            )
            conn.commit()
            if cur.rowcount == 0:
                return None
        finally:
            conn.close()
        return self.get(approval_id)

    def approve(self, approval_id: str, decided_by: str) -> dict[str, Any] | None:
        return self._transition(approval_id, PENDING, APPROVED, decided_by)

    def reject(self, approval_id: str, decided_by: str) -> dict[str, Any] | None:
        return self._transition(approval_id, PENDING, REJECTED, decided_by)

    def mark_executed(self, approval_id: str) -> dict[str, Any] | None:
        return self._transition(approval_id, APPROVED, EXECUTED, "system")

    def mark_failed(self, approval_id: str, reason: str) -> dict[str, Any] | None:
        row = self._transition(approval_id, APPROVED, FAILED, "system")
        if row is None:
            return None
        conn = _connect(self.data_dir)
        try:
            proposal = json.loads(
                conn.execute(
                    "SELECT proposal_json FROM approvals WHERE approval_id = ?",
                    (approval_id,),
                ).fetchone()["proposal_json"]
            )
            proposal["failure_reason"] = reason
            conn.execute(
                "UPDATE approvals SET proposal_json = ? WHERE approval_id = ?",
                (json.dumps(proposal), approval_id),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get(approval_id)

    def expire_overdue(self) -> list[dict[str, Any]]:
        """Move every PENDING proposal past its ``expires_at`` to EXPIRED.

        Returns the rows that were expired, so callers can notify. Silence
        must never become a trade -- an unanswered proposal always resolves
        to "no order," never to implicit approval.
        """
        now = time.time()
        conn = _connect(self.data_dir)
        try:
            rows = conn.execute(
                "SELECT approval_id FROM approvals WHERE status = ? AND expires_at < ?",
                (PENDING, now),
            ).fetchall()
            ids = [r["approval_id"] for r in rows]
            if ids:
                conn.executemany(
                    "UPDATE approvals SET status = ?, decided_at = ?, decided_by = ? "
                    "WHERE approval_id = ? AND status = ?",
                    [(EXPIRED, now, "system:timeout", aid, PENDING) for aid in ids],
                )
                conn.commit()
        finally:
            conn.close()
        return [self.get(aid) for aid in ids]
