"""Durable, idempotent order-intent ledger and append-only execution audit trail.

This ledger records workflow state only. It does not communicate with a broker.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TRANSITIONS = {
    "created": {"preflight_rejected", "approved", "cancelled"},
    "approved": {"submitted", "cancelled", "rejected"},
    "submitted": {"acknowledged", "partially_filled", "filled", "rejected", "unknown"},
    "acknowledged": {"partially_filled", "filled", "cancel_requested", "rejected", "unknown"},
    "partially_filled": {"partially_filled", "filled", "cancel_requested", "unknown"},
    "cancel_requested": {"cancelled", "partially_filled", "filled", "unknown"},
    "unknown": {"acknowledged", "partially_filled", "filled", "cancelled", "rejected", "reconciled"},
    "preflight_rejected": set(),
    "filled": {"reconciled"},
    "cancelled": {"reconciled"},
    "rejected": {"reconciled"},
    "reconciled": set(),
}


class ExecutionLedger:
    def __init__(self, database_path: str | None = None) -> None:
        self.database_path = database_path or os.getenv(
            "FOREX_AUTOPILOT_TELEMETRY_DB", "data/telemetry.sqlite3"
        )
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS order_intents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    broker_order_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS execution_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    idempotency_key TEXT NOT NULL,
                    previous_status TEXT,
                    new_status TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    occurred_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_execution_audit_key
                    ON execution_audit(idempotency_key, id);
                CREATE TABLE IF NOT EXISTS runtime_controls (
                    control_key TEXT PRIMARY KEY,
                    control_value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS control_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    control_key TEXT NOT NULL,
                    previous_value TEXT NOT NULL,
                    new_value TEXT NOT NULL,
                    changed_at TEXT NOT NULL
                );
                INSERT OR IGNORE INTO runtime_controls(control_key, control_value, updated_at)
                    VALUES ('trading_paused', '1', 'bootstrap');
                INSERT OR IGNORE INTO runtime_controls(control_key, control_value, updated_at)
                    VALUES ('kill_switch_active', '1', 'bootstrap');
            """)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def create_intent(self, idempotency_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not idempotency_key or len(idempotency_key) > 128:
            raise ValueError("Idempotency key must contain 1 to 128 characters.")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        now = self._now()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM order_intents WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing:
                if existing["payload_json"] != encoded:
                    raise ValueError("Idempotency key was already used with a different payload.")
                return dict(existing)
            connection.execute(
                """INSERT INTO order_intents(
                    idempotency_key, payload_json, status, created_at, updated_at
                ) VALUES (?, ?, 'created', ?, ?)""",
                (idempotency_key, encoded, now, now),
            )
            connection.execute(
                """INSERT INTO execution_audit(
                    idempotency_key, previous_status, new_status, event_type,
                    details_json, occurred_at
                ) VALUES (?, NULL, 'created', 'intent_created', '{}', ?)""",
                (idempotency_key, now),
            )
            row = connection.execute(
                "SELECT * FROM order_intents WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return dict(row)

    def transition(
        self,
        idempotency_key: str,
        new_status: str,
        *,
        event_type: str,
        details: dict[str, Any] | None = None,
        broker_order_id: str | None = None,
    ) -> dict[str, Any]:
        if new_status not in TRANSITIONS or not event_type:
            raise ValueError("Unknown status or missing audit event type.")
        details_json = json.dumps(details or {}, sort_keys=True, separators=(",", ":"), allow_nan=False)
        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM order_intents WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if row is None:
                raise KeyError("Order intent not found.")
            previous = row["status"]
            if new_status not in TRANSITIONS[previous]:
                raise ValueError(f"Invalid order state transition: {previous} -> {new_status}.")
            connection.execute(
                """UPDATE order_intents SET status = ?, broker_order_id = COALESCE(?, broker_order_id),
                   updated_at = ? WHERE idempotency_key = ?""",
                (new_status, broker_order_id, now, idempotency_key),
            )
            connection.execute(
                """INSERT INTO execution_audit(
                    idempotency_key, previous_status, new_status, event_type,
                    details_json, occurred_at
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (idempotency_key, previous, new_status, event_type, details_json, now),
            )
            updated = connection.execute(
                "SELECT * FROM order_intents WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return dict(updated)


    def get_intent(self, idempotency_key: str) -> dict[str, Any] | None:
        """Return one durable intent with its decoded payload for guarded dispatch."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM order_intents WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json"))
        return item

    def set_control(self, key: str, enabled: bool) -> None:
        if key not in {"trading_paused", "kill_switch_active"}:
            raise ValueError("Unsupported runtime control.")
        now = self._now()
        new_value = "1" if enabled else "0"
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                "SELECT control_value FROM runtime_controls WHERE control_key = ?",
                (key,),
            ).fetchone()
            previous_value = previous["control_value"] if previous else "1"
            connection.execute(
                """INSERT INTO runtime_controls(control_key, control_value, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(control_key) DO UPDATE SET
                     control_value=excluded.control_value, updated_at=excluded.updated_at""",
                (key, new_value, now),
            )
            connection.execute(
                """INSERT INTO control_audit(control_key, previous_value, new_value, changed_at)
                   VALUES (?, ?, ?, ?)""",
                (key, previous_value, new_value, now),
            )

    def controls(self) -> dict[str, bool]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT control_key, control_value FROM runtime_controls"
            ).fetchall()
        values = {row["control_key"]: row["control_value"] == "1" for row in rows}
        return {
            "trading_paused": values.get("trading_paused", True),
            "kill_switch_active": values.get("kill_switch_active", True),
        }

    def audit_events(self, idempotency_key: str, limit: int = 100) -> list[dict[str, Any]]:
        safe_limit = min(max(int(limit), 1), 500)
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT idempotency_key, previous_status, new_status,
                          event_type, details_json, occurred_at
                   FROM execution_audit WHERE idempotency_key = ?
                   ORDER BY id LIMIT ?""",
                (idempotency_key, safe_limit),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["details"] = json.loads(item.pop("details_json"))
            result.append(item)
        return result

    def control_events(self, limit: int = 100) -> list[dict[str, Any]]:
        safe_limit = min(max(int(limit), 1), 500)
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT control_key, previous_value, new_value, changed_at
                   FROM control_audit ORDER BY id DESC LIMIT ?""",
                (safe_limit,),
            ).fetchall()
        return [dict(row) for row in rows]
