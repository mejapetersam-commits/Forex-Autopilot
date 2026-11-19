"""Small SQLite-backed store for read-only MT5 telemetry.

The database path is configurable with FOREX_AUTOPILOT_TELEMETRY_DB.
Keep the database on a persistent, access-restricted volume in deployment.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

from app.broker.bridge import MT5AccountSnapshot, MT5CandleBatch, MT5ExecutionHistory, MT5ExecutionState, MT5Heartbeat, MT5Quote, MT5SymbolSpecification


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

                CREATE TABLE IF NOT EXISTS symbol_specifications (
                    symbol TEXT PRIMARY KEY,
                    digits INTEGER NOT NULL,
                    point REAL NOT NULL,
                    tick_size REAL NOT NULL,
                    tick_value_profit REAL NOT NULL,
                    tick_value_loss REAL NOT NULL,
                    contract_size REAL NOT NULL,
                    volume_min REAL NOT NULL,
                    volume_max REAL NOT NULL,
                    volume_step REAL NOT NULL,
                    stops_level_points INTEGER NOT NULL,
                    freeze_level_points INTEGER NOT NULL,
                    trade_allowed INTEGER NOT NULL,
                    base_currency TEXT NOT NULL,
                    profit_currency TEXT NOT NULL,
                    margin_currency TEXT NOT NULL,
                    account_currency TEXT NOT NULL,
                    observed_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_symbol_specs_observed
                    ON symbol_specifications(observed_at DESC);


                CREATE TABLE IF NOT EXISTS execution_state_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    terminal_id TEXT NOT NULL,
                    environment TEXT NOT NULL,
                    server TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    daily_loss_pct REAL NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_execution_state_observed
                    ON execution_state_snapshots(observed_at DESC);

                CREATE TABLE IF NOT EXISTS execution_deals (
                    deal_ticket TEXT PRIMARY KEY,
                    order_ticket TEXT NOT NULL,
                    terminal_id TEXT NOT NULL,
                    environment TEXT NOT NULL CHECK(environment = 'demo'),
                    server TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry TEXT NOT NULL,
                    volume_lots REAL NOT NULL,
                    price REAL NOT NULL,
                    magic INTEGER NOT NULL,
                    comment TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    observed_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_execution_deals_order
                    ON execution_deals(order_ticket, entry, occurred_at);

                CREATE TABLE IF NOT EXISTS candles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    opened_at TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    tick_volume INTEGER NOT NULL,
                    UNIQUE(symbol, timeframe, opened_at)
                );
                CREATE INDEX IF NOT EXISTS idx_candles_lookup
                    ON candles(symbol, timeframe, opened_at DESC);
                """
            )
            execution_columns = {
                row["name"] for row in connection.execute(
                    "PRAGMA table_info(execution_state_snapshots)"
                ).fetchall()
            }
            if "daily_loss_pct" not in execution_columns:
                connection.execute(
                    "ALTER TABLE execution_state_snapshots "
                    "ADD COLUMN daily_loss_pct REAL NOT NULL DEFAULT 1000"
                )


    def save_execution_state(self, payload: MT5ExecutionState) -> None:
        import json
        encoded = json.dumps(
            [position.model_dump(mode="json") for position in payload.positions],
            sort_keys=True, separators=(",", ":"), allow_nan=False,
        )
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO execution_state_snapshots(
                    terminal_id, environment, server, observed_at, daily_loss_pct, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (payload.terminal_id, payload.environment, payload.server,
                 payload.observed_at.isoformat(), payload.daily_loss_pct, encoded),
            )

    def latest_execution_state(self) -> dict[str, Any] | None:
        import json
        with self._connect() as connection:
            row = connection.execute(
                """SELECT terminal_id, environment, server, observed_at, daily_loss_pct, payload_json
                   FROM execution_state_snapshots ORDER BY observed_at DESC, id DESC LIMIT 1"""
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["positions"] = json.loads(result.pop("payload_json"))
        result["positions_count"] = len(result["positions"])
        return result

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
                       SELECT symbol, MAX(observed_at) AS latest_observed_at
                       FROM quotes GROUP BY symbol
                   ) latest ON latest.symbol = q.symbol
                           AND latest.latest_observed_at = q.observed_at
                   WHERE q.id = (
                       SELECT MAX(q2.id) FROM quotes q2
                       WHERE q2.symbol = q.symbol
                         AND q2.observed_at = q.observed_at
                   )
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


    def save_candle_batch(self, payload: MT5CandleBatch) -> int:
        """Insert or refresh candles idempotently by symbol, timeframe and open time."""
        rows = [
            (
                payload.symbol,
                payload.timeframe,
                candle.opened_at.isoformat(),
                candle.open,
                candle.high,
                candle.low,
                candle.close,
                candle.tick_volume,
            )
            for candle in payload.candles
        ]
        with self._connect() as connection:
            connection.executemany(
                """INSERT INTO candles(
                    symbol, timeframe, opened_at, open, high, low, close, tick_volume
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, timeframe, opened_at) DO UPDATE SET
                    open=excluded.open,
                    high=excluded.high,
                    low=excluded.low,
                    close=excluded.close,
                    tick_volume=excluded.tick_volume""",
                rows,
            )
        return len(rows)


    def save_candle_batches(self, batches: list[MT5CandleBatch]) -> dict[str, int]:
        """Atomically upsert multiple symbol/timeframe batches in one transaction."""
        rows = []
        counts: dict[str, int] = {}
        for payload in batches:
            key = f"{payload.symbol}:{payload.timeframe}"
            counts[key] = len(payload.candles)
            rows.extend(
                (
                    payload.symbol,
                    payload.timeframe,
                    candle.opened_at.isoformat(),
                    candle.open,
                    candle.high,
                    candle.low,
                    candle.close,
                    candle.tick_volume,
                )
                for candle in payload.candles
            )

        with self._connect() as connection:
            connection.executemany(
                """INSERT INTO candles(
                    symbol, timeframe, opened_at, open, high, low, close, tick_volume
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, timeframe, opened_at) DO UPDATE SET
                    open=excluded.open,
                    high=excluded.high,
                    low=excluded.low,
                    close=excluded.close,
                    tick_volume=excluded.tick_volume""",
                rows,
            )
        return counts

    def candle_history(
        self, symbol: str, timeframe: str, limit: int = 500
    ) -> list[dict[str, Any]]:
        safe_limit = min(max(int(limit), 1), 5000)
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT symbol, timeframe, opened_at, open, high, low, close, tick_volume
                   FROM candles
                   WHERE symbol = ? AND timeframe = ?
                   ORDER BY opened_at DESC, id DESC LIMIT ?""",
                (symbol.strip().upper(), timeframe.strip().upper(), safe_limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]


    def save_symbol_specification(self, payload: MT5SymbolSpecification) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO symbol_specifications(
                    symbol, digits, point, tick_size, tick_value_profit,
                    tick_value_loss, contract_size, volume_min, volume_max,
                    volume_step, stops_level_points, freeze_level_points,
                    trade_allowed, base_currency, profit_currency, margin_currency,
                    account_currency, observed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    digits=excluded.digits, point=excluded.point,
                    tick_size=excluded.tick_size,
                    tick_value_profit=excluded.tick_value_profit,
                    tick_value_loss=excluded.tick_value_loss,
                    contract_size=excluded.contract_size,
                    volume_min=excluded.volume_min, volume_max=excluded.volume_max,
                    volume_step=excluded.volume_step,
                    stops_level_points=excluded.stops_level_points,
                    freeze_level_points=excluded.freeze_level_points,
                    trade_allowed=excluded.trade_allowed,
                    base_currency=excluded.base_currency,
                    profit_currency=excluded.profit_currency,
                    margin_currency=excluded.margin_currency,
                    account_currency=excluded.account_currency,
                    observed_at=excluded.observed_at""",
                (
                    payload.symbol, payload.digits, payload.point, payload.tick_size,
                    payload.tick_value_profit, payload.tick_value_loss,
                    payload.contract_size, payload.volume_min, payload.volume_max,
                    payload.volume_step, payload.stops_level_points,
                    payload.freeze_level_points, int(payload.trade_allowed),
                    payload.base_currency, payload.profit_currency,
                    payload.margin_currency, payload.account_currency,
                    payload.observed_at.isoformat(),
                ),
            )

    def latest_symbol_specification(self, symbol: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM symbol_specifications WHERE symbol = ?",
                (symbol.strip().upper(),),
            ).fetchone()
        result = self._as_dict(row)
        if result is not None:
            result["trade_allowed"] = bool(result["trade_allowed"])
        return result

    def latest_symbol_specifications(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM symbol_specifications ORDER BY symbol"
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["trade_allowed"] = bool(item["trade_allowed"])
            result.append(item)
        return result


    def save_execution_history(self, payload: MT5ExecutionHistory) -> int:
        """Idempotently upsert broker deals; duplicate tickets update the same row."""
        rows = [
            (
                deal.deal_ticket, deal.order_ticket, payload.terminal_id,
                payload.environment, payload.server, deal.symbol, deal.side,
                deal.entry, deal.volume_lots, deal.price, deal.magic,
                deal.comment, deal.occurred_at.isoformat(),
                payload.observed_at.isoformat(),
            )
            for deal in payload.deals
        ]
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany(
                """INSERT INTO execution_deals(
                    deal_ticket, order_ticket, terminal_id, environment, server,
                    symbol, side, entry, volume_lots, price, magic, comment,
                    occurred_at, observed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(deal_ticket) DO UPDATE SET
                    order_ticket=excluded.order_ticket,
                    terminal_id=excluded.terminal_id,
                    environment=excluded.environment,
                    server=excluded.server,
                    symbol=excluded.symbol,
                    side=excluded.side,
                    entry=excluded.entry,
                    volume_lots=excluded.volume_lots,
                    price=excluded.price,
                    magic=excluded.magic,
                    comment=excluded.comment,
                    occurred_at=excluded.occurred_at,
                    observed_at=excluded.observed_at""",
                rows,
            )
        return len(rows)

    def execution_deals_for_order(self, order_ticket: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT deal_ticket, order_ticket, terminal_id, environment,
                          server, symbol, side, entry, volume_lots, price,
                          magic, comment, occurred_at, observed_at
                   FROM execution_deals WHERE order_ticket=?
                   ORDER BY occurred_at, deal_ticket""",
                (str(order_ticket),),
            ).fetchall()
        return [dict(row) for row in rows]


    def execution_deals_for_tag(self, broker_tag: str) -> list[dict[str, Any]]:
        """Find broker fills carrying the deterministic FOREX AUTOPILOT order tag."""
        prefix = "FA:" + broker_tag
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT deal_ticket, order_ticket, terminal_id, environment,
                          server, symbol, side, entry, volume_lots, price,
                          magic, comment, occurred_at, observed_at
                   FROM execution_deals WHERE comment LIKE ?
                   ORDER BY occurred_at, deal_ticket""",
                (prefix + "%",),
            ).fetchall()
        return [dict(row) for row in rows]
