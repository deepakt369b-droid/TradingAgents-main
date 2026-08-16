"""Registry of runs parked after a classified quota/rate-limit failure.

Sits beside the per-ticker checkpoint DBs (see :mod:`checkpointer`) in a
single shared SQLite file, since parked runs are rare enough that per-ticker
sharding isn't worth the complexity. A parked run's LangGraph checkpoint is
left intact (the graph only clears it on success) -- this registry exists so
a caller (the web UI, the CLI, a scheduler) can *discover* that a run is
sitting there waiting to be resumed, without having to guess by scanning
every checkpoint DB, and so it can be resumed under a different per-role
provider than the one that failed.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

from tradingagents.dataflows.utils import safe_ticker_component


def _db_path(data_dir: str | Path) -> Path:
    p = Path(data_dir) / "checkpoints"
    p.mkdir(parents=True, exist_ok=True)
    return p / "run_registry.db"


def _connect(data_dir: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path(data_dir)))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS parked_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            signature TEXT NOT NULL DEFAULT '',
            thread_id TEXT NOT NULL,
            step INTEGER,
            failed_role TEXT,
            failed_provider TEXT,
            error_type TEXT,
            error_message TEXT,
            status_code INTEGER,
            status TEXT NOT NULL DEFAULT 'parked',
            parked_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            UNIQUE(ticker, trade_date, signature)
        )
        """
    )
    conn.commit()
    return conn


def park_run(
    data_dir: str | Path,
    ticker: str,
    trade_date: str,
    signature: str,
    thread_id: str,
    step: int | None,
    failed_role: str,
    failed_provider: str,
    error_info: dict[str, Any],
) -> None:
    """Record (or refresh) a parked run after a classified quota failure.

    Upserts on ``(ticker, trade_date, signature)`` so repeated failures on
    the same run update the existing record rather than accumulating
    duplicates, and reopens a previously-resumed/cleared record if the same
    run parks again.
    """
    safe_ticker_component(ticker)  # validate; raises on path-unsafe input
    now = time.time()
    conn = _connect(data_dir)
    try:
        conn.execute(
            """
            INSERT INTO parked_runs (
                ticker, trade_date, signature, thread_id, step,
                failed_role, failed_provider, error_type, error_message,
                status_code, status, parked_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'parked', ?, ?)
            ON CONFLICT(ticker, trade_date, signature) DO UPDATE SET
                thread_id=excluded.thread_id,
                step=excluded.step,
                failed_role=excluded.failed_role,
                failed_provider=excluded.failed_provider,
                error_type=excluded.error_type,
                error_message=excluded.error_message,
                status_code=excluded.status_code,
                status='parked',
                updated_at=excluded.updated_at
            """,
            (
                ticker.upper(), str(trade_date), signature, thread_id, step,
                failed_role, failed_provider,
                error_info.get("type"), error_info.get("message"),
                error_info.get("status_code"),
                now, now,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def list_parked_runs(data_dir: str | Path, status: str = "parked") -> list[dict[str, Any]]:
    """Return parked-run records, most recently parked first."""
    conn = _connect(data_dir)
    try:
        rows = conn.execute(
            "SELECT * FROM parked_runs WHERE status = ? ORDER BY parked_at DESC",
            (status,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_parked_run(
    data_dir: str | Path, ticker: str, trade_date: str, signature: str = ""
) -> dict[str, Any] | None:
    conn = _connect(data_dir)
    try:
        row = conn.execute(
            "SELECT * FROM parked_runs WHERE ticker = ? AND trade_date = ? AND signature = ?",
            (ticker.upper(), str(trade_date), signature),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def mark_run_resolved(
    data_dir: str | Path, ticker: str, trade_date: str, signature: str, status: str = "resumed"
) -> None:
    """Mark a parked run as resumed (succeeded) or cleared (abandoned)."""
    conn = _connect(data_dir)
    try:
        conn.execute(
            "UPDATE parked_runs SET status = ?, updated_at = ? "
            "WHERE ticker = ? AND trade_date = ? AND signature = ?",
            (status, time.time(), ticker.upper(), str(trade_date), signature),
        )
        conn.commit()
    finally:
        conn.close()
