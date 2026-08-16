"""Local record of every order this system has placed, keyed by client_order_id.

The idempotency guard for order submission lives here, not in broker-side
duplicate-ID rejection: querying "have I already placed this?" against our
own SQLite record works identically across every executor regardless of
whether that specific broker API even supports a client-order-ID lookup,
and it doesn't depend on guessing exchange-specific param names. The
``client_order_id`` is still forwarded to the broker request where the SDK
supports it (see alpaca_executor.py/ccxt_executor.py) as defense in depth,
but correctness here does not depend on that.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


def _db_path(data_dir: str | Path) -> Path:
    p = Path(data_dir) / "execution"
    p.mkdir(parents=True, exist_ok=True)
    return p / "order_ledger.db"


def _connect(data_dir: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path(data_dir)))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS placed_orders (
            client_order_id TEXT PRIMARY KEY,
            ticker TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            side TEXT NOT NULL,
            platform TEXT NOT NULL,
            order_result_json TEXT NOT NULL,
            placed_at REAL NOT NULL
        )
        """
    )
    conn.commit()
    return conn


class OrderLedger:
    """SQLite-backed record of placed orders, one file per data_cache_dir."""

    def __init__(self, data_dir: str | Path):
        self.data_dir = data_dir

    def get(self, client_order_id: str) -> dict[str, Any] | None:
        """Return the previously-recorded order result dict, or None if never placed."""
        conn = _connect(self.data_dir)
        try:
            row = conn.execute(
                "SELECT order_result_json FROM placed_orders WHERE client_order_id = ?",
                (client_order_id,),
            ).fetchone()
            return json.loads(row["order_result_json"]) if row else None
        finally:
            conn.close()

    def record(
        self,
        client_order_id: str,
        ticker: str,
        trade_date: str,
        side: str,
        platform: str,
        order_result: dict[str, Any],
    ) -> None:
        """Record a successfully placed order. Idempotent: a re-record of the
        same client_order_id overwrites (e.g. a status update), never
        duplicates."""
        conn = _connect(self.data_dir)
        try:
            conn.execute(
                """
                INSERT INTO placed_orders (
                    client_order_id, ticker, trade_date, side, platform,
                    order_result_json, placed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(client_order_id) DO UPDATE SET
                    order_result_json=excluded.order_result_json
                """,
                (
                    client_order_id, ticker.upper(), str(trade_date), side.lower(),
                    platform, json.dumps(order_result), time.time(),
                ),
            )
            conn.commit()
        finally:
            conn.close()
