"""Paper Trading Executor for safe local simulation with zero real money risk.

State (cash, positions, order history) persists to SQLite on the persistent
volume instead of living only in the Python process. Without this, every
container restart or Coolify redeploy would silently reset the paper
portfolio to its initial cash balance -- destroying exactly the track record
the paper-first promotion gate (see live_gate.py) depends on.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from pathlib import Path

from .base_executor import BaseExecutor
from .order_models import AccountBalance, Order, OrderResult, OrderSide, OrderStatus, Position

logger = logging.getLogger(__name__)

_DEFAULT_DATA_DIR = "~/.tradingagents"


def _db_path(data_dir: str | Path) -> Path:
    p = Path(data_dir).expanduser() / "execution"
    p.mkdir(parents=True, exist_ok=True)
    return p / "paper_portfolio.db"


class PaperExecutor(BaseExecutor):
    """Simulated paper trading executor, backed by a persistent SQLite ledger."""

    def __init__(
        self,
        initial_cash: float = 100000.0,
        config: dict | None = None,
        data_dir: str | Path | None = None,
    ):
        super().__init__(config)
        self.initial_cash = initial_cash
        self.data_dir = data_dir or (config or {}).get("data_cache_dir", _DEFAULT_DATA_DIR)
        self._db = _db_path(self.data_dir)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS account (id INTEGER PRIMARY KEY CHECK (id = 1), cash REAL NOT NULL)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS positions (
                    symbol TEXT PRIMARY KEY,
                    quantity REAL NOT NULL,
                    average_entry_price REAL NOT NULL,
                    current_price REAL NOT NULL,
                    asset_type TEXT NOT NULL DEFAULT 'stock'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    order_id TEXT PRIMARY KEY,
                    result_json TEXT NOT NULL,
                    placed_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                "INSERT OR IGNORE INTO account (id, cash) VALUES (1, ?)", (self.initial_cash,)
            )
            conn.commit()
        finally:
            conn.close()

    def _get_cash(self, conn: sqlite3.Connection) -> float:
        row = conn.execute("SELECT cash FROM account WHERE id = 1").fetchone()
        return float(row["cash"])

    def _set_cash(self, conn: sqlite3.Connection, cash: float) -> None:
        conn.execute("UPDATE account SET cash = ? WHERE id = 1", (cash,))

    def _get_position(self, conn: sqlite3.Connection, symbol: str) -> Position | None:
        row = conn.execute("SELECT * FROM positions WHERE symbol = ?", (symbol,)).fetchone()
        if row is None:
            return None
        return Position(
            symbol=row["symbol"], quantity=row["quantity"],
            average_entry_price=row["average_entry_price"],
            current_price=row["current_price"], unrealized_pnl=0.0,
            asset_type=row["asset_type"],
        )

    def place_order(self, order: Order) -> OrderResult:
        # Idempotency: a client_order_id we've already recorded returns the
        # original result instead of executing (and double-charging cash
        # for) the same order again -- see execution/idempotency.py.
        if order.client_order_id:
            existing = self._find_by_client_order_id(order.client_order_id)
            if existing is not None:
                logger.info(
                    "PaperExecutor: order %s already placed (client_order_id=%s); returning recorded result.",
                    existing.order_id, order.client_order_id,
                )
                return existing

        order_id = order.client_order_id or f"paper-{uuid.uuid4().hex[:8]}"
        exec_price = order.price if order.price else 100.0
        total_cost = exec_price * order.quantity

        conn = self._connect()
        try:
            cash = self._get_cash(conn)

            if order.side == OrderSide.BUY:
                if cash < total_cost:
                    logger.warning("PaperExecutor: Insufficient buying power for order %s", order.symbol)
                    result = OrderResult(
                        order_id=order_id, symbol=order.symbol, side=order.side,
                        status=OrderStatus.REJECTED, quantity=order.quantity,
                        message="Insufficient funds in paper account",
                    )
                    self._record_order(conn, result)
                    conn.commit()
                    return result

                cash -= total_cost
                existing = self._get_position(conn, order.symbol)
                if existing:
                    new_qty = existing.quantity + order.quantity
                    avg_price = (existing.average_entry_price * existing.quantity + total_cost) / new_qty
                else:
                    new_qty = order.quantity
                    avg_price = exec_price
                conn.execute(
                    """
                    INSERT INTO positions (symbol, quantity, average_entry_price, current_price, asset_type)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(symbol) DO UPDATE SET
                        quantity=excluded.quantity,
                        average_entry_price=excluded.average_entry_price,
                        current_price=excluded.current_price
                    """,
                    (order.symbol, new_qty, avg_price, exec_price, order.asset_type),
                )

            else:  # SELL
                current = self._get_position(conn, order.symbol)
                if not current or current.quantity < order.quantity:
                    result = OrderResult(
                        order_id=order_id, symbol=order.symbol, side=order.side,
                        status=OrderStatus.REJECTED, quantity=order.quantity,
                        message="Insufficient position to sell",
                    )
                    self._record_order(conn, result)
                    conn.commit()
                    return result

                cash += total_cost
                new_qty = current.quantity - order.quantity
                if new_qty <= 0:
                    conn.execute("DELETE FROM positions WHERE symbol = ?", (order.symbol,))
                else:
                    conn.execute(
                        "UPDATE positions SET quantity = ?, current_price = ? WHERE symbol = ?",
                        (new_qty, exec_price, order.symbol),
                    )

            self._set_cash(conn, cash)

            result = OrderResult(
                order_id=order_id, symbol=order.symbol, side=order.side,
                status=OrderStatus.FILLED, quantity=order.quantity,
                filled_quantity=order.quantity, filled_price=exec_price,
                message="Paper order executed successfully",
            )
            self._record_order(conn, result)
            conn.commit()
            logger.info(
                "PaperExecutor: Executed %s %f %s at $%.2f",
                order.side.value, order.quantity, order.symbol, exec_price,
            )
            return result
        finally:
            conn.close()

    def _record_order(self, conn: sqlite3.Connection, result: OrderResult) -> None:
        conn.execute(
            "INSERT OR REPLACE INTO orders (order_id, result_json, placed_at) VALUES (?, ?, ?)",
            (result.order_id, result.model_dump_json(), time.time()),
        )

    def _find_by_client_order_id(self, client_order_id: str) -> OrderResult | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT result_json FROM orders WHERE order_id = ?", (client_order_id,)
            ).fetchone()
            return OrderResult(**json.loads(row["result_json"])) if row else None
        finally:
            conn.close()

    def get_positions(self) -> list[Position]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM positions").fetchall()
            return [
                Position(
                    symbol=r["symbol"], quantity=r["quantity"],
                    average_entry_price=r["average_entry_price"],
                    current_price=r["current_price"], unrealized_pnl=0.0,
                    asset_type=r["asset_type"],
                )
                for r in rows
            ]
        finally:
            conn.close()

    def get_account_balance(self) -> AccountBalance:
        conn = self._connect()
        try:
            cash = self._get_cash(conn)
            positions_value = sum(
                r["quantity"] * r["current_price"]
                for r in conn.execute("SELECT quantity, current_price FROM positions").fetchall()
            )
            return AccountBalance(cash=cash, buying_power=cash, portfolio_value=cash + positions_value)
        finally:
            conn.close()

    def cancel_order(self, order_id: str) -> bool:
        conn = self._connect()
        try:
            row = conn.execute("SELECT result_json FROM orders WHERE order_id = ?", (order_id,)).fetchone()
            if row is None:
                return False
            result = json.loads(row["result_json"])
            result["status"] = OrderStatus.CANCELLED.value
            conn.execute(
                "UPDATE orders SET result_json = ? WHERE order_id = ?",
                (json.dumps(result), order_id),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def get_order_status(self, order_id: str) -> OrderStatus:
        conn = self._connect()
        try:
            row = conn.execute("SELECT result_json FROM orders WHERE order_id = ?", (order_id,)).fetchone()
            if row is None:
                return OrderStatus.REJECTED
            return OrderStatus(json.loads(row["result_json"])["status"])
        finally:
            conn.close()
