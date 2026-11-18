"""Small SQLite-backed store for read-only MT5 telemetry.

The database path is configurable with FOREX_AUTOPILOT_TELEMETRY_DB.
Keep the database on a persistent, access-restricted volume in deployment.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

from app.broker.bridge import MT5AccountSnapshot, MT5Heartbeat, MT5Quote


class TelemetryStore:
    """Persist MT5 observations without storing broker login credentials."""

    def __init__(self, database_path: str | Path | None = None) -> None:
        configured_path = database_path or os.getenv(
            "FOREX_AUTOPILOT_TELEMETRY_DB", "data/telemetry.sqlite3"
        )
        self.database_path = str(configured_path)
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
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS heartbeats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server TEXT NOT NULL,
                    terminal_connected INTEGER NOT NULL,
                    observed_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_heartbeats_observed
                    ON heartbeats(observed_at DESC);

                CREATE TABLE IF NOT EXISTS account_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server TEXT NOT NULL,
                    account_currency TEXT NOT NULL,
                    balance REAL NOT NULL,
                    equity REAL NOT NULL,
                    margin REAL NOT NULL,
                    free_margin REAL NOT NULL,
                    leverage INTEGER NOT NULL,
                    observed_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_accounts_observed
                    ON account_snapshots(observed_at DESC);

                CREATE TABLE IF NOT EXISTS quotes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    bid REAL NOT NULL,
                    ask REAL NOT NULL,
                    observed_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_quotes_symbol_observed
                    ON quotes(symbol, observed_at DESC);
                """
            )

    def save_heartbeat(self, payload: MT5Heartbeat) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO heartbeats(server, terminal_connected, observed_at) "
                "VALUES (?, ?, ?)",
                (payload.server, int(payload.terminal_connected), payload.observed_at.isoformat()),
            )

    def save_account(self, payload: MT5AccountSnapshot) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO account_snapshots(
                    server, account_currency, balance, equity, margin,
                    free_margin, leverage, observed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    payload.server, payload.account_currency, payload.balance,
                    payload.equity, payload.margin, payload.free_margin,
                    payload.leverage, payload.observed_at.isoformat(),
                ),
            )

    def save_quote(self, payload: MT5Quote) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO quotes(symbol, bid, ask, observed_at) VALUES (?, ?, ?, ?)",
                (payload.symbol, payload.bid, payload.ask, payload.timestamp.isoformat()),
            )

    @staticmethod
    def _as_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    def latest_heartbeat(self) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT server, terminal_connected, observed_at
                   FROM heartbeats ORDER BY observed_at DESC, id DESC LIMIT 1"""
            ).fetchone()
        result = self._as_dict(row)
        if result is not None:
            result["terminal_connected"] = bool(result["terminal_connected"])
        return result

    def latest_account(self) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT server, account_currency, balance, equity, margin,
                          free_margin, leverage, observed_at
                   FROM account_snapshots ORDER BY observed_at DESC, id DESC LIMIT 1"""
            ).fetchone()
        return self._as_dict(row)

    def latest_quotes(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT q.symbol, q.bid, q.ask, q.observed_at
                   FROM quotes q
                   INNER JOIN (
                       SELECT symbol, MAX(id) AS latest_id
                       FROM quotes GROUP BY symbol
                   ) latest ON latest.latest_id = q.id
                   ORDER BY q.symbol"""
            ).fetchall()
        return [dict(row) for row in rows]

    def quote_history(self, symbol: str, limit: int = 100) -> list[dict[str, Any]]:
        safe_limit = min(max(int(limit), 1), 1000)
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT symbol, bid, ask, observed_at FROM quotes
                   WHERE symbol = ? ORDER BY observed_at DESC, id DESC LIMIT ?""",
                (symbol.strip().upper(), safe_limit),
            ).fetchall()
        return [dict(row) for row in rows]
