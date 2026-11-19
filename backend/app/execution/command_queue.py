"""Durable, lease-based command transport for the MT5 demo bridge.

Commands are only created from an already-approved execution intent. This module
never talks to a broker. It uses at-most-once leasing: expired commands are
quarantined for reconciliation and are never automatically redelivered.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class ExecutionCommandQueue:
    def __init__(self, database_path: str | None = None) -> None:
        self.database_path = database_path or os.getenv(
            "FOREX_AUTOPILOT_TELEMETRY_DB", "data/telemetry.sqlite3"
        )
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS execution_commands (
                    command_id TEXT PRIMARY KEY,
                    intent_id TEXT NOT NULL UNIQUE,
                    environment TEXT NOT NULL CHECK(environment = 'demo'),
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN
                        ('queued','leased','acknowledged','rejected','unknown','expired')),
                    created_at TEXT NOT NULL,
                    lease_until TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    terminal_id TEXT,
                    result_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_execution_commands_delivery
                    ON execution_commands(status, created_at);
            """)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def enqueue_approved_intent(
        self, *, command_id: str, intent_id: str, payload: dict[str, Any],
        environment: str, trading_enabled: bool,
    ) -> dict[str, Any]:
        if environment != "demo":
            raise ValueError("Execution command transport is restricted to demo.")
        if not trading_enabled:
            raise ValueError("Trading is disabled; command was not queued.")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", command_id or "") or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", intent_id or ""):
            raise ValueError("Command and intent IDs must use 1 to 128 letters, digits, hyphens or underscores.")
        required = {"symbol", "side", "volume_lots", "stop_loss", "take_profit"}
        if not required.issubset(payload):
            raise ValueError("Protected order payload is incomplete.")
        if payload["side"] not in {"buy", "sell"}:
            raise ValueError("Unsupported order side.")
        if float(payload["volume_lots"]) <= 0 or float(payload["stop_loss"]) <= 0 or float(payload["take_profit"]) <= 0:
            raise ValueError("Volume, stop-loss and take-profit must be positive.")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        now = self._now().isoformat()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM execution_commands WHERE intent_id = ?", (intent_id,)
            ).fetchone()
            if existing:
                if existing["payload_json"] != encoded:
                    raise ValueError("Intent already has a different execution command.")
                return dict(existing)
            db.execute(
                """INSERT INTO execution_commands
                   (command_id,intent_id,environment,payload_json,status,created_at)
                   VALUES (?,?, 'demo', ?, 'queued', ?)""",
                (command_id, intent_id, encoded, now),
            )
            row = db.execute(
                "SELECT * FROM execution_commands WHERE command_id = ?", (command_id,)
            ).fetchone()
        return dict(row)

    def lease_next(self, *, terminal_id: str, lease_seconds: int = 60) -> dict[str, Any] | None:
        if not terminal_id or len(terminal_id) > 128:
            raise ValueError("Terminal ID is required.")
        if not 5 <= lease_seconds <= 60:
            raise ValueError("Lease duration must be between 5 and 60 seconds.")
        now = self._now()
        now_text = now.isoformat()
        lease_until = (now + timedelta(seconds=lease_seconds)).isoformat()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """UPDATE execution_commands SET status='expired', lease_until=NULL
                   WHERE status='leased' AND lease_until < ?""", (now_text,)
            )
            row = db.execute(
                """SELECT * FROM execution_commands WHERE status='queued'
                   ORDER BY created_at, command_id LIMIT 1"""
            ).fetchone()
            if row is None:
                return None
            db.execute(
                """UPDATE execution_commands SET status='leased', lease_until=?,
                   attempts=attempts+1, terminal_id=? WHERE command_id=? AND status='queued'""",
                (lease_until, terminal_id, row["command_id"]),
            )
            leased = db.execute(
                "SELECT * FROM execution_commands WHERE command_id=?", (row["command_id"],)
            ).fetchone()
        result = dict(leased)
        result["payload"] = json.loads(result.pop("payload_json"))
        result.pop("result_json", None)
        return result

    def record_result(self, command_id: str, *, terminal_id: str,
                      outcome: str, result: dict[str, Any],
                      expected_intent_id: str | None = None) -> dict[str, Any]:
        if outcome not in {"acknowledged", "rejected", "unknown"}:
            raise ValueError("Terminal outcome must be acknowledged, rejected or unknown.")
        encoded = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM execution_commands WHERE command_id=?", (command_id,)
            ).fetchone()
            if row is None:
                raise KeyError("Execution command not found.")
            # Bind the terminal callback to the command's immutable intent before
            # accepting either a first result or an idempotent duplicate.
            if expected_intent_id is not None and row["intent_id"] != expected_intent_id:
                raise ValueError("Terminal result intent does not match command.")
            if row["status"] in {"acknowledged", "rejected", "unknown"}:
                if row["result_json"] != encoded or row["status"] != outcome:
                    raise ValueError("Conflicting duplicate terminal result.")
                return dict(row)
            if row["status"] != "leased" or row["terminal_id"] != terminal_id:
                raise ValueError("Command is not leased to this terminal.")
            if not row["lease_until"] or row["lease_until"] < self._now().isoformat():
                raise ValueError("Command lease expired; broker reconciliation is required.")
            db.execute(
                """UPDATE execution_commands SET status=?, result_json=?, lease_until=NULL
                   WHERE command_id=?""", (outcome, encoded, command_id)
            )
            updated = db.execute(
                "SELECT * FROM execution_commands WHERE command_id=?", (command_id,)
            ).fetchone()
        return dict(updated)
