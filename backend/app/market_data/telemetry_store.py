"""Small SQLite-backed store for read-only MT5 telemetry.

The database path is configurable with FOREX_AUTOPILOT_TELEMETRY_DB.
Keep the database on a persistent, access-restricted volume in deployment.
"""
from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.broker.bridge import MT5AccountSnapshot, MT5CandleBatch, MT5ExecutionHistory, MT5ExecutionOrderHistory, MT5ExecutionState, MT5Heartbeat, MT5Quote, MT5SymbolSpecification


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
                    position_id TEXT NOT NULL DEFAULT '',
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
                    observed_at TEXT NOT NULL,
                    profit REAL,
                    commission REAL,
                    swap REAL,
                    fee REAL
                );
                CREATE INDEX IF NOT EXISTS idx_execution_deals_order
                    ON execution_deals(order_ticket, entry, occurred_at);

                CREATE TABLE IF NOT EXISTS execution_orders (
                    order_ticket TEXT PRIMARY KEY,
                    terminal_id TEXT NOT NULL,
                    environment TEXT NOT NULL CHECK(environment = 'demo'),
                    server TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    state TEXT NOT NULL,
                    initial_volume REAL NOT NULL,
                    current_volume REAL NOT NULL,
                    price REAL NOT NULL,
                    stop_loss REAL NOT NULL,
                    take_profit REAL NOT NULL,
                    magic INTEGER NOT NULL,
                    comment TEXT NOT NULL,
                    setup_at TEXT NOT NULL,
                    done_at TEXT,
                    observed_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_execution_orders_state
                    ON execution_orders(state, observed_at DESC);

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

                CREATE TABLE IF NOT EXISTS candle_ingestion_batches (
                    batch_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    received_count INTEGER NOT NULL,
                    first_candle_at TEXT NOT NULL,
                    last_candle_at TEXT NOT NULL,
                    ingested_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_candle_ingestion_recent
                    ON candle_ingestion_batches(symbol, timeframe, ingested_at DESC);
                """
            )
            execution_columns = {
                row["name"] for row in connection.execute(
                    "PRAGMA table_info(execution_state_snapshots)"
                ).fetchall()
            }
            deal_columns = {
                row["name"] for row in connection.execute(
                    "PRAGMA table_info(execution_deals)"
                ).fetchall()
            }
            if "position_id" not in deal_columns:
                connection.execute(
                    "ALTER TABLE execution_deals ADD COLUMN position_id TEXT NOT NULL DEFAULT ''"
                )
            for cash_column in ("profit", "commission", "swap", "fee"):
                if cash_column not in deal_columns:
                    connection.execute(
                        f"ALTER TABLE execution_deals ADD COLUMN {cash_column} REAL"
                    )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_execution_deals_position "
                "ON execution_deals(position_id, occurred_at)"
            )
            position_columns = {
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

    def recent_execution_states(self, limit: int = 2) -> list[dict[str, Any]]:
        """Return newest execution snapshots, newest first, with linked deal evidence."""
        safe_limit = min(max(int(limit), 1), 10)
        import json
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT terminal_id, environment, server, observed_at,
                          daily_loss_pct, payload_json
                   FROM execution_state_snapshots
                   ORDER BY observed_at DESC, id DESC LIMIT ?""",
                (safe_limit,),
            ).fetchall()
        snapshots = []
        for row in rows:
            item = dict(row)
            item["positions"] = json.loads(item.pop("payload_json"))
            for position in item["positions"]:
                position["related_deals"] = self.execution_deals_for_position(
                    position.get("position_id", "")
                ) if position.get("position_id") else []
            snapshots.append(item)
        return snapshots

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
        for position in result["positions"]:
            position["related_deals"] = self.execution_deals_for_position(
                position.get("position_id", "")
            ) if position.get("position_id") else []
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
            ingested_at = datetime.now(timezone.utc).isoformat()
            for payload in batches:
                opened = sorted(candle.opened_at for candle in payload.candles)
                connection.execute(
                    """INSERT INTO candle_ingestion_batches(
                        batch_id, symbol, timeframe, received_count,
                        first_candle_at, last_candle_at, ingested_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (str(uuid.uuid4()), payload.symbol, payload.timeframe,
                     len(payload.candles), opened[0].isoformat(),
                     opened[-1].isoformat(), ingested_at),
                )
        return counts

    def candle_ingestion_summary(self, *, limit: int = 100) -> dict[str, Any]:
        """Return recent bulk-ingestion receipts and per-series upload aggregates."""
        safe_limit = min(max(int(limit), 1), 500)
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT batch_id, symbol, timeframe, received_count,
                          first_candle_at, last_candle_at, ingested_at
                   FROM candle_ingestion_batches
                   ORDER BY ingested_at DESC, rowid DESC LIMIT ?""",
                (safe_limit,),
            ).fetchall()
            totals = connection.execute(
                """SELECT batches.symbol, batches.timeframe,
                          COUNT(*) AS batch_count,
                          SUM(batches.received_count) AS candles_received,
                          MAX(batches.ingested_at) AS last_ingested_at,
                          MAX(batches.last_candle_at) AS latest_candle_at,
                          (SELECT COUNT(*) FROM candles
                           WHERE candles.symbol = batches.symbol
                             AND candles.timeframe = batches.timeframe)
                              AS unique_candles_stored,
                          (SELECT MIN(opened_at) FROM candles
                           WHERE candles.symbol = batches.symbol
                             AND candles.timeframe = batches.timeframe)
                              AS first_stored_candle_at,
                          (SELECT MAX(opened_at) FROM candles
                           WHERE candles.symbol = batches.symbol
                             AND candles.timeframe = batches.timeframe)
                              AS latest_stored_candle_at
                   FROM candle_ingestion_batches AS batches
                   GROUP BY batches.symbol, batches.timeframe
                   ORDER BY batches.symbol, batches.timeframe"""
            ).fetchall()
        return {
            "recent_batches": [dict(row) for row in rows],
            "series": [dict(row) for row in totals],
            "batch_count": len(rows),
            "series_count": len(totals),
            "read_only": True,
            "trading_enabled": False,
        }

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
                    observed_at=excluded.observed_at
                WHERE excluded.observed_at >= symbol_specifications.observed_at""",
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
        """Insert broker deals idempotently and reject conflicting reuse of a deal ticket."""
        rows = [
            (
                deal.deal_ticket, deal.order_ticket, deal.position_id, payload.terminal_id,
                payload.environment, payload.server, deal.symbol, deal.side,
                deal.entry, deal.volume_lots, deal.price, deal.magic,
                deal.comment, deal.occurred_at.isoformat(),
                payload.observed_at.isoformat(), deal.profit, deal.commission,
                deal.swap, deal.fee,
            )
            for deal in payload.deals
        ]
        immutable_columns = {
            "order_ticket": 1, "terminal_id": 3, "environment": 4,
            "server": 5, "symbol": 6, "side": 7, "entry": 8,
            "volume_lots": 9, "price": 10, "magic": 11,
            "comment": 12, "occurred_at": 13,
        }
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for row in rows:
                existing = connection.execute(
                    "SELECT * FROM execution_deals WHERE deal_ticket = ?", (row[0],)
                ).fetchone()
                if existing is not None:
                    for column, row_index in immutable_columns.items():
                        if existing[column] != row[row_index]:
                            raise ValueError(
                                f"Conflicting broker evidence for existing deal ticket {row[0]} ({column})."
                            )
                    if existing["position_id"] and row[2] and existing["position_id"] != row[2]:
                        raise ValueError(
                            f"Conflicting broker evidence for existing deal ticket {row[0]} (position_id)."
                        )
                    for column, row_index in {
                        "profit": 15, "commission": 16, "swap": 17, "fee": 18,
                    }.items():
                        if (existing[column] is not None and row[row_index] is not None
                                and abs(float(existing[column]) - float(row[row_index])) > 1e-8):
                            raise ValueError(
                                f"Conflicting broker evidence for existing deal ticket {row[0]} ({column})."
                            )
            connection.executemany(
                """INSERT INTO execution_deals(
                    deal_ticket, order_ticket, position_id, terminal_id, environment, server,
                    symbol, side, entry, volume_lots, price, magic, comment,
                    occurred_at, observed_at, profit, commission, swap, fee
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(deal_ticket) DO UPDATE SET
                    position_id=CASE WHEN execution_deals.position_id='' THEN excluded.position_id ELSE execution_deals.position_id END,
                    profit=COALESCE(execution_deals.profit, excluded.profit),
                    commission=COALESCE(execution_deals.commission, excluded.commission),
                    swap=COALESCE(execution_deals.swap, excluded.swap),
                    fee=COALESCE(execution_deals.fee, excluded.fee)
                WHERE (execution_deals.position_id='' AND excluded.position_id<>'')
                   OR (execution_deals.profit IS NULL AND excluded.profit IS NOT NULL)
                   OR (execution_deals.commission IS NULL AND excluded.commission IS NOT NULL)
                   OR (execution_deals.swap IS NULL AND excluded.swap IS NOT NULL)
                   OR (execution_deals.fee IS NULL AND excluded.fee IS NOT NULL)""",
                rows,
            )
        return len(rows)



    def execution_deals_for_position(self, position_id: str) -> list[dict[str, Any]]:
        """Return broker deals linked by MT5's stable POSITION_IDENTIFIER."""
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT deal_ticket, order_ticket, position_id, symbol, side, entry,
                          volume_lots, price, magic, comment, occurred_at,
                          profit, commission, swap, fee
                   FROM execution_deals WHERE position_id=?
                   ORDER BY occurred_at, deal_ticket""",
                (str(position_id),),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_execution_order_history(self, payload: MT5ExecutionOrderHistory) -> int:
        """Upsert broker order snapshots while rejecting immutable ticket conflicts."""
        rows = [
            (order.order_ticket, payload.terminal_id, payload.environment, payload.server,
             order.symbol, order.order_type, order.state, order.initial_volume,
             order.current_volume, order.price, order.stop_loss, order.take_profit,
             order.magic, order.comment, order.setup_at.isoformat(),
             order.done_at.isoformat() if order.done_at else None,
             payload.observed_at.isoformat())
            for order in payload.orders
        ]
        immutable = {
            "terminal_id": 1, "environment": 2, "server": 3, "symbol": 4,
            "order_type": 5, "initial_volume": 7, "magic": 12,
            "comment": 13, "setup_at": 14,
        }
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for row in rows:
                existing = connection.execute(
                    "SELECT * FROM execution_orders WHERE order_ticket=?", (row[0],)
                ).fetchone()
                if existing is not None:
                    for column, index in immutable.items():
                        if existing[column] != row[index]:
                            raise ValueError(
                                f"Conflicting broker evidence for existing order ticket {row[0]} ({column})."
                            )
            connection.executemany(
                """INSERT INTO execution_orders(
                    order_ticket, terminal_id, environment, server, symbol, order_type,
                    state, initial_volume, current_volume, price, stop_loss, take_profit,
                    magic, comment, setup_at, done_at, observed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_ticket) DO UPDATE SET
                    state=excluded.state, current_volume=excluded.current_volume,
                    price=excluded.price, stop_loss=excluded.stop_loss,
                    take_profit=excluded.take_profit, done_at=excluded.done_at,
                    observed_at=excluded.observed_at
                WHERE excluded.observed_at >= execution_orders.observed_at""",
                rows,
            )
        return len(rows)

    def recent_execution_orders(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return sanitized recent broker order snapshots for read-only operations views."""
        safe_limit = min(max(int(limit), 1), 500)
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT order_ticket, terminal_id, environment, server, symbol,
                          order_type, state, initial_volume, current_volume, price,
                          stop_loss, take_profit, magic, setup_at, done_at, observed_at
                   FROM execution_orders
                   WHERE environment='demo'
                   ORDER BY observed_at DESC, order_ticket DESC LIMIT ?""",
                (safe_limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def execution_orders_for_ticket(self, order_ticket: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM execution_orders WHERE order_ticket=?",
                (str(order_ticket),),
            ).fetchone()
        return self._as_dict(row)

    def execution_orders_for_tag(self, broker_tag: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT * FROM execution_orders WHERE comment LIKE ?
                   ORDER BY setup_at, order_ticket""",
                ("FA:" + broker_tag + "%",),
            ).fetchall()
        return [dict(row) for row in rows]

    def execution_deals_for_order(self, order_ticket: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT deal_ticket, order_ticket, position_id, terminal_id, environment,
                          server, symbol, side, entry, volume_lots, price,
                          magic, comment, occurred_at, observed_at,
                          profit, commission, swap, fee
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
                """SELECT deal_ticket, order_ticket, position_id, terminal_id, environment,
                          server, symbol, side, entry, volume_lots, price,
                          magic, comment, occurred_at, observed_at,
                          profit, commission, swap, fee
                   FROM execution_deals WHERE comment LIKE ?
                   ORDER BY occurred_at, deal_ticket""",
                (prefix + "%",),
            ).fetchall()
        return [dict(row) for row in rows]


    def demo_trade_attribution(self) -> dict[str, Any]:
        """Reconstruct closed round trips from persisted demo broker deal evidence."""
        from app.execution.trade_attribution import build_trade_attribution
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT deal_ticket, order_ticket, position_id, terminal_id, environment,
                          server, symbol, side, entry, volume_lots, price, magic, comment,
                          occurred_at, profit, commission, swap, fee
                   FROM execution_deals WHERE environment='demo'
                   ORDER BY occurred_at, deal_ticket"""
            ).fetchall()
            servers = {row["server"] for row in rows}
            if len(servers) == 1:
                account = connection.execute(
                    """SELECT account_currency FROM account_snapshots
                       WHERE server = ? ORDER BY observed_at DESC, id DESC LIMIT 1""",
                    (next(iter(servers)),),
                ).fetchone()
            elif not servers:
                account = connection.execute(
                    """SELECT account_currency FROM account_snapshots
                       ORDER BY observed_at DESC, id DESC LIMIT 1"""
                ).fetchone()
            else:
                account = None  # Mixed broker servers: currency cannot be safely inferred.
        deals = [dict(row) for row in rows]
        result = build_trade_attribution(deals)
        result["account_currency"] = account["account_currency"] if account else None
        result["deal_count"] = len(deals)
        result["history_start"] = min((d["occurred_at"] for d in deals), default=None)
        result["history_end"] = max((d["occurred_at"] for d in deals), default=None)
        groups = []
        keys = sorted({(int(d["magic"]), d["symbol"]) for d in deals})
        for magic, symbol in keys:
            group = build_trade_attribution(
                [d for d in deals if int(d["magic"]) == magic and d["symbol"] == symbol]
            )
            groups.append({"magic": magic, "symbol": symbol, **group})
        result["groups"] = groups
        return result

    def demo_observation_summary(self, limit: int = 100) -> dict[str, Any]:
        """Read-only rollup of broker-confirmed demo deals; no inferred PnL."""
        safe_limit = min(max(int(limit), 1), 500)
        with self._connect() as connection:
            totals = connection.execute(
                """SELECT COUNT(*) AS deal_count,
                          COALESCE(SUM(CASE WHEN profit IS NOT NULL AND commission IS NOT NULL
                                    AND swap IS NOT NULL AND fee IS NOT NULL THEN 1 ELSE 0 END), 0)
                              AS cash_complete_deal_count,
                          COUNT(DISTINCT terminal_id) AS terminal_count,
                          COUNT(DISTINCT magic) AS strategy_magic_count,
                          MIN(occurred_at) AS first_deal_at,
                          MAX(observed_at) AS last_observed_at
                   FROM execution_deals WHERE environment='demo'"""
            ).fetchone()
            groups = connection.execute(
                """SELECT magic, symbol,
                          SUM(CASE WHEN entry='in' THEN 1 ELSE 0 END) AS entry_deals,
                          SUM(CASE WHEN entry IN ('out','out_by','inout') THEN 1 ELSE 0 END) AS exit_deals,
                          COUNT(*) AS deal_count,
                          SUM(volume_lots) AS gross_deal_volume_lots,
                          MAX(occurred_at) AS last_deal_at,
                          MAX(observed_at) AS last_observed_at
                   FROM execution_deals WHERE environment='demo'
                   GROUP BY magic, symbol
                   ORDER BY last_deal_at DESC LIMIT ?""",
                (safe_limit,),
            ).fetchall()
            order_totals = connection.execute(
                """SELECT COUNT(*) AS order_count,
                          SUM(CASE WHEN state IN ('filled','completed','done') THEN 1 ELSE 0 END) AS completed_orders,
                          SUM(CASE WHEN state IN ('rejected','canceled','cancelled','expired') THEN 1 ELSE 0 END) AS failed_orders,
                          MAX(observed_at) AS last_order_observed_at
                   FROM execution_orders WHERE environment='demo'"""
            ).fetchone()
            latest_state = connection.execute(
                """SELECT terminal_id, environment, server, observed_at,
                          daily_loss_pct, payload_json
                   FROM execution_state_snapshots
                   WHERE environment='demo'
                   ORDER BY observed_at DESC, id DESC LIMIT 1"""
            ).fetchone()
        import json
        positions = json.loads(latest_state["payload_json"]) if latest_state else []
        return {
            "deal_totals": dict(totals),
            "order_totals": dict(order_totals),
            "groups": [dict(row) for row in groups],
            "latest_terminal": {
                "terminal_id": latest_state["terminal_id"],
                "environment": latest_state["environment"],
                "server": latest_state["server"],
                "observed_at": latest_state["observed_at"],
                "reported_open_positions": len(positions),
                "daily_loss_pct_estimate": latest_state["daily_loss_pct"],
            } if latest_state else None,
            "pnl_available": bool(totals["cash_complete_deal_count"]),
            "limitations": [
                "Older broker history rows may predate cash-component ingestion and remain incomplete.",
                "Only fully closed position cycles with complete cash fields are included in realized P&L.",
                "Magic number is a grouping key, not proof that a strategy generated a trade.",
                "Deal counts and gross volume are not equivalent to completed round trips.",
            ],
        }

