"""Durable operational event journal and notification outbox.

This module records events and queues notification payloads. It deliberately
contains no network sender: delivery adapters can be added later with explicit
provider configuration, timeouts, redaction and operator approval.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


_ALLOWED_SEVERITIES = {"info", "warning", "critical"}
_KEY_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamps must be timezone-aware.")
    return value.astimezone(timezone.utc).isoformat()


class EventOutbox:
    """Append-only event journal with an idempotent, lease-based outbox."""

    def __init__(self, database_path: str | Path | None = None) -> None:
        self.database_path = str(database_path or os.getenv(
            "FOREX_AUTOPILOT_TELEMETRY_DB", "data/telemetry.sqlite3"
        ))
        if self.database_path != ":memory:":
            Path(self.database_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=15)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS operational_events (
                    event_id TEXT PRIMARY KEY,
                    event_key TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    severity TEXT NOT NULL CHECK(severity IN ('info','warning','critical')),
                    message TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    occurred_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_operational_events_time
                    ON operational_events(occurred_at DESC);
                CREATE TABLE IF NOT EXISTS notification_outbox (
                    event_id TEXT PRIMARY KEY REFERENCES operational_events(event_id),
                    channel TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','leased','delivered','dead')),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    available_at TEXT NOT NULL,
                    lease_token TEXT,
                    lease_until TEXT,
                    last_error TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_notification_outbox_due
                    ON notification_outbox(status, available_at, lease_until);
            """)

    def record(
        self, *, event_key: str, event_type: str, severity: str,
        message: str, payload: dict[str, Any] | None = None,
        channel: str = "operator",
        occurred_at: datetime | None = None,
    ) -> dict[str, Any]:
        if not _KEY_RE.fullmatch(event_key):
            raise ValueError("event_key contains unsupported characters or is too long.")
        if severity not in _ALLOWED_SEVERITIES:
            raise ValueError("Unsupported event severity.")
        if not event_type or len(event_type) > 120:
            raise ValueError("event_type must contain 1-120 characters.")
        if not message or len(message) > 2000:
            raise ValueError("message must contain 1-2000 characters.")
        if not channel or len(channel) > 80:
            raise ValueError("channel must contain 1-80 characters.")
        encoded = json.dumps(payload or {}, sort_keys=True, separators=(",", ":"), allow_nan=False)
        timestamp = _iso(occurred_at or _now())
        event_id = str(uuid.uuid4())
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT e.*, o.channel, o.status FROM operational_events e "
                "LEFT JOIN notification_outbox o USING(event_id) WHERE event_key=?",
                (event_key,),
            ).fetchone()
            if existing:
                return dict(existing)
            db.execute(
                "INSERT INTO operational_events VALUES (?, ?, ?, ?, ?, ?, ?)",
                (event_id, event_key, event_type, severity, message, encoded, timestamp),
            )
            db.execute(
                "INSERT INTO notification_outbox(event_id,channel,status,available_at,updated_at) "
                "VALUES (?,?,'pending',?,?)",
                (event_id, channel, timestamp, timestamp),
            )
            return dict(db.execute(
                "SELECT e.*, o.channel, o.status FROM operational_events e "
                "JOIN notification_outbox o USING(event_id) WHERE e.event_id=?",
                (event_id,),
            ).fetchone())

    def list_events(self, limit: int = 100, severity: str | None = None) -> list[dict[str, Any]]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500.")
        if severity is not None and severity not in _ALLOWED_SEVERITIES:
            raise ValueError("Unsupported event severity.")
        with self._connect() as db:
            query = ("SELECT e.*, o.channel, o.status AS delivery_status, o.attempts "
                     "FROM operational_events e JOIN notification_outbox o USING(event_id)")
            params: list[Any] = []
            if severity:
                query += " WHERE e.severity=?"
                params.append(severity)
            query += " ORDER BY e.occurred_at DESC LIMIT ?"
            params.append(limit)
            rows = db.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def lease_due(self, *, limit: int = 20, lease_seconds: int = 60,
                  now: datetime | None = None) -> list[dict[str, Any]]:
        if not 1 <= limit <= 100 or not 5 <= lease_seconds <= 900:
            raise ValueError("Invalid lease limit or duration.")
        current = now or _now()
        current_text = _iso(current)
        expiry = _iso(current + timedelta(seconds=lease_seconds))
        leased: list[dict[str, Any]] = []
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                """SELECT o.event_id, o.channel, o.attempts, e.event_key,
                          e.event_type, e.severity, e.message, e.payload_json, e.occurred_at
                   FROM notification_outbox o JOIN operational_events e USING(event_id)
                   WHERE (o.status='pending' AND o.available_at<=?)
                      OR (o.status='leased' AND o.lease_until<=?)
                   ORDER BY e.occurred_at LIMIT ?""",
                (current_text, current_text, limit),
            ).fetchall()
            for row in rows:
                token = str(uuid.uuid4())
                db.execute(
                    """UPDATE notification_outbox
                       SET status='leased', attempts=attempts+1, lease_token=?,
                           lease_until=?, updated_at=? WHERE event_id=?""",
                    (token, expiry, current_text, row["event_id"]),
                )
                item = dict(row)
                item["payload"] = json.loads(item.pop("payload_json"))
                item["lease_token"] = token
                item["attempts"] += 1
                leased.append(item)
        return leased

    def complete(self, event_id: str, lease_token: str, *,
                 delivered: bool, error: str | None = None,
                 retry_after_seconds: int = 300,
                 max_attempts: int = 8,
                 now: datetime | None = None) -> str:
        if retry_after_seconds < 1 or not 1 <= max_attempts <= 50:
            raise ValueError("Invalid retry policy.")
        timestamp = now or _now()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT attempts,status,lease_token FROM notification_outbox WHERE event_id=?",
                (event_id,),
            ).fetchone()
            if not row or row["status"] != "leased" or row["lease_token"] != lease_token:
                raise ValueError("Outbox lease is missing, expired or does not belong to this worker.")
            if delivered:
                status = "delivered"
                available = _iso(timestamp)
                safe_error = None
            elif row["attempts"] >= max_attempts:
                status = "dead"
                available = _iso(timestamp)
                safe_error = (error or "Delivery failed")[:500]
            else:
                status = "pending"
                available = _iso(timestamp + timedelta(seconds=retry_after_seconds))
                safe_error = (error or "Delivery failed")[:500]
            db.execute(
                """UPDATE notification_outbox SET status=?, available_at=?,
                   lease_token=NULL, lease_until=NULL, last_error=?, updated_at=?
                   WHERE event_id=?""",
                (status, available, safe_error, _iso(timestamp), event_id),
            )
            return status
