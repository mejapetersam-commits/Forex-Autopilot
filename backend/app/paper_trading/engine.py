"""Persistent, forward-only H1 paper trading. Never submits broker orders."""
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from math import floor, isfinite

from app.strategy.engine import StrategyConfig, evaluate_signal


INITIAL_EQUITY = 10_000.0
RISK_PCT = 0.25
MAX_DAILY_LOSS_PCT = 1.0
MAX_DRAWDOWN_PCT = 5.0
TIMEFRAME = "H1"


def utc_now():
    return datetime.now(timezone.utc)


def parse_time(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


class PaperTradingEngine:
    def __init__(self):
        self.db = os.getenv(
            "FOREX_AUTOPILOT_TELEMETRY_DB",
            "data/telemetry.sqlite3",
        )

    def connect(self):
        connection = sqlite3.connect(self.db, timeout=20)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=20000")
        return connection

    def initialize(self, connection):
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS paper_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS paper_cursors (
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                opened_at TEXT NOT NULL,
                PRIMARY KEY(symbol, timeframe)
            );
            CREATE TABLE IF NOT EXISTS paper_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                entry_at TEXT NOT NULL,
                entry_price REAL NOT NULL,
                stop_loss REAL NOT NULL,
                take_profit REAL NOT NULL,
                volume_lots REAL NOT NULL,
                tick_size REAL NOT NULL,
                tick_value_profit REAL NOT NULL,
                tick_value_loss REAL NOT NULL,
                risk_cash REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS paper_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                entry_at TEXT NOT NULL,
                exit_at TEXT NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL NOT NULL,
                stop_loss REAL NOT NULL,
                take_profit REAL NOT NULL,
                volume_lots REAL NOT NULL,
                pnl_gross REAL NOT NULL,
                exit_reason TEXT NOT NULL,
                signal_strategy TEXT NOT NULL
            );
        """)
        defaults = {
            "equity": str(INITIAL_EQUITY),
            "peak_equity": str(INITIAL_EQUITY),
            "daily_date": utc_now().date().isoformat(),
            "daily_start_equity": str(INITIAL_EQUITY),
            "started_at": utc_now().isoformat(),
        }
        for key, value in defaults.items():
            connection.execute(
                "INSERT OR IGNORE INTO paper_state(key,value) VALUES (?,?)",
                (key, value),
            )

    def state(self, connection, key):
        row = connection.execute(
            "SELECT value FROM paper_state WHERE key=?", (key,)
        ).fetchone()
        return float(row["value"]) if row else 0.0

    def set_state(self, connection, key, value):
        connection.execute(
            """INSERT INTO paper_state(key,value) VALUES (?,?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
            (key, str(value)),
        )

    def snapshot(self):
        with self.connect() as db:
            self.initialize(db)
            equity = self.state(db, "equity")
            peak = self.state(db, "peak_equity")
            daily_start = self.state(db, "daily_start_equity")
            daily_date = db.execute(
                "SELECT value FROM paper_state WHERE key='daily_date'"
            ).fetchone()["value"]
            today = utc_now().date().isoformat()
            if today != daily_date:
                daily_start = equity
                self.set_state(db, "daily_date", today)
                self.set_state(db, "daily_start_equity", daily_start)

            position = db.execute(
                "SELECT * FROM paper_positions ORDER BY id DESC LIMIT 1"
            ).fetchone()
            trades = db.execute(
                "SELECT * FROM paper_trades ORDER BY id DESC LIMIT 100"
            ).fetchall()
            cursors = db.execute(
                "SELECT * FROM paper_cursors ORDER BY symbol"
            ).fetchall()
            count = db.execute(
                "SELECT COUNT(*) AS n FROM paper_trades"
            ).fetchone()["n"]

            return {
                "mode": "forward_paper",
                "execution_enabled": False,
                "broker_orders_submitted": 0,
                "timeframe": TIMEFRAME,
                "initial_equity": INITIAL_EQUITY,
                "equity": round(equity, 2),
                "peak_equity": round(peak, 2),
                "net_pnl_gross": round(equity - INITIAL_EQUITY, 2),
                "drawdown_pct": round(
                    max(0.0, (peak - equity) / peak * 100), 3
                ) if peak else 0.0,
                "daily_loss_pct": round(
                    max(0.0, (daily_start - equity) / daily_start * 100), 3
                ) if daily_start else 0.0,
                "risk_per_trade_pct": RISK_PCT,
                "max_daily_loss_pct": MAX_DAILY_LOSS_PCT,
                "max_drawdown_pct": MAX_DRAWDOWN_PCT,
                "open_position": dict(position) if position else None,
                "closed_trade_count": count,
                "closed_trades": [dict(row) for row in trades],
                "candle_checkpoints": [dict(row) for row in cursors],
                "started_at": db.execute(
                    "SELECT value FROM paper_state WHERE key='started_at'"
                ).fetchone()["value"],
                "pnl_basis": "Gross simulated P&L; spread, slippage and commission not deducted.",
                "status": "running" if cursors else "awaiting_initialization",
            }

    def process(self, store):
        symbols = sorted({
            item.strip().upper()
            for item in os.getenv(
                "FOREX_AUTOPILOT_DASHBOARD_SYMBOLS", "EURUSDm,GBPUSDm"
            ).split(",") if item.strip()
        })
        processed = 0
        opened = 0
        closed = 0
        skipped = []

        with self.connect() as db:
            self.initialize(db)
            db.commit()
            db.execute("BEGIN IMMEDIATE")

            today = utc_now().date().isoformat()
            daily_date = db.execute(
                "SELECT value FROM paper_state WHERE key='daily_date'"
            ).fetchone()["value"]
            equity = self.state(db, "equity")
            if today != daily_date:
                self.set_state(db, "daily_date", today)
                self.set_state(db, "daily_start_equity", equity)

            for symbol in symbols:
                candles = store.candle_history(symbol, TIMEFRAME, 5000)
                if not candles:
                    skipped.append({"symbol": symbol, "reason": "No H1 candles"})
                    continue

                # Never process a still-forming H1 candle.
                now = utc_now()
                candles = [
                    row for row in candles
                    if parse_time(row["opened_at"]) + timedelta(hours=1) <= now
                ]
                if not candles:
                    skipped.append({
                        "symbol": symbol,
                        "reason": "No completed H1 candles available",
                    })
                    continue

                cursor = db.execute(
                    """SELECT opened_at FROM paper_cursors
                       WHERE symbol=? AND timeframe=?""",
                    (symbol, TIMEFRAME),
                ).fetchone()

                if cursor is None:
                    latest = candles[-1]["opened_at"]
                    db.execute(
                        """INSERT INTO paper_cursors(symbol,timeframe,opened_at)
                           VALUES (?,?,?)""",
                        (symbol, TIMEFRAME, latest),
                    )
                    skipped.append({
                        "symbol": symbol,
                        "reason": "Initial checkpoint set; historical candles not replayed",
                        "checkpoint": latest,
                    })
                    continue

                newer = [
                    row for row in candles
                    if row["opened_at"] > cursor["opened_at"]
                ]

                for candle in newer:
                    index = candles.index(candle)
                    history = candles[:index]
                    position = db.execute(
                        "SELECT * FROM paper_positions ORDER BY id DESC LIMIT 1"
                    ).fetchone()
                    had_position_at_candle_start = position is not None

                    # Manage only this symbol's position. A position on another
                    # symbol blocks new entries but must not use this symbol's OHLC.
                    # If both levels are touched in one candle, assume the stop was hit first.
                    if position and position["symbol"] == symbol:
                        side = position["side"]
                        stop_hit = (
                            candle["low"] <= position["stop_loss"]
                            if side == "buy"
                            else candle["high"] >= position["stop_loss"]
                        )
                        target_hit = (
                            candle["high"] >= position["take_profit"]
                            if side == "buy"
                            else candle["low"] <= position["take_profit"]
                        )
                        if stop_hit or target_hit:
                            reason = "stop_loss" if stop_hit else "take_profit"
                            exit_price = position["stop_loss"] if stop_hit else position["take_profit"]
                            direction = 1 if side == "buy" else -1
                            price_change = (exit_price - position["entry_price"]) * direction
                            tick_value = (
                                position["tick_value_profit"]
                                if price_change >= 0
                                else position["tick_value_loss"]
                            )
                            pnl = (
                                price_change / position["tick_size"]
                                * tick_value * position["volume_lots"]
                            )
                            if not isfinite(pnl):
                                raise ValueError("Non-finite paper P&L; transaction stopped.")
                            db.execute(
                                """INSERT INTO paper_trades(
                                    symbol,side,entry_at,exit_at,entry_price,exit_price,
                                    stop_loss,take_profit,volume_lots,pnl_gross,
                                    exit_reason,signal_strategy
                                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                                (
                                    position["symbol"], side, position["entry_at"],
                                    candle["opened_at"], position["entry_price"],
                                    exit_price, position["stop_loss"],
                                    position["take_profit"], position["volume_lots"],
                                    pnl, reason, "EMA + RSI + MACD v0.1.0",
                                ),
                            )
                            db.execute("DELETE FROM paper_positions WHERE id=?", (position["id"],))
                            equity = self.state(db, "equity") + pnl
                            self.set_state(db, "equity", equity)
                            self.set_state(
                                db, "peak_equity",
                                max(self.state(db, "peak_equity"), equity),
                            )
                            closed += 1
                            position = None

                    # A position closed during this candle cannot be reopened
                    # at that same candle's already-passed opening price.
                    if position is None and not had_position_at_candle_start and len(history) >= 60:
                        equity = self.state(db, "equity")
                        peak = self.state(db, "peak_equity")
                        daily_start = self.state(db, "daily_start_equity")
                        daily_loss = (
                            max(0, (daily_start - equity) / daily_start * 100)
                            if daily_start else 0
                        )
                        drawdown = (
                            max(0, (peak - equity) / peak * 100) if peak else 0
                        )

                        if daily_loss < MAX_DAILY_LOSS_PCT and drawdown < MAX_DRAWDOWN_PCT:
                            spec = store.latest_symbol_specification(symbol)
                            if not spec:
                                skipped.append({"symbol": symbol, "reason": "Missing broker symbol specification"})
                            else:
                                try:
                                    tick_size = float(spec["tick_size"])
                                    tick_loss = float(spec["tick_value_loss"])
                                    tick_profit = float(spec["tick_value_profit"])
                                    volume_min = float(spec["volume_min"])
                                    volume_max = min(
                                        float(spec["volume_max"]),
                                        float(os.getenv("FOREX_AUTOPILOT_MAX_VOLUME_LOTS", "0.01")),
                                    )
                                    volume_step = float(spec["volume_step"])
                                    observed = parse_time(spec["observed_at"])
                                    spec_age = (utc_now() - observed).total_seconds()
                                    if (
                                        min(tick_size, tick_loss, tick_profit,
                                            volume_min, volume_step) <= 0
                                        or volume_max < volume_min
                                        or spec_age < -300
                                        or spec_age > 86400
                                    ):
                                        raise ValueError("Invalid or stale symbol specification")
                                except (KeyError, TypeError, ValueError, OverflowError):
                                    skipped.append({"symbol": symbol, "reason": "Invalid or stale broker specification"})
                                    spec = None

                                if spec:
                                    signal = evaluate_signal(history, StrategyConfig())
                                    side = str(signal.get("signal", "")).strip().lower()
                                    levels = signal.get("candidate_levels", {})
                                    if side in ("buy", "sell") and levels:
                                        entry = float(candle["open"])
                                        distance = abs(
                                            float(levels["reference_close"])
                                            - float(levels["stop_loss"])
                                        )
                                        risk_cash = equity * RISK_PCT / 100
                                        loss_per_lot = distance / tick_size * tick_loss
                                        raw_volume = risk_cash / loss_per_lot if loss_per_lot > 0 else 0
                                        volume = floor(raw_volume / volume_step) * volume_step
                                        volume = min(volume, volume_max)
                                        if volume + 1e-10 >= volume_min:
                                            stop = entry - distance if side == "buy" else entry + distance
                                            target = entry + distance * 2 if side == "buy" else entry - distance * 2
                                            db.execute(
                                                """INSERT INTO paper_positions(
                                                    symbol,side,entry_at,entry_price,stop_loss,
                                                    take_profit,volume_lots,tick_size,
                                                    tick_value_profit,tick_value_loss,risk_cash
                                                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                                                (
                                                    symbol, side, candle["opened_at"], entry,
                                                    stop, target, volume, tick_size,
                                                    tick_profit, tick_loss, risk_cash,
                                                ),
                                            )
                                            opened += 1

                    db.execute(
                        """UPDATE paper_cursors SET opened_at=?
                           WHERE symbol=? AND timeframe=?""",
                        (candle["opened_at"], symbol, TIMEFRAME),
                    )
                    processed += 1

            db.commit()

        return {
            "processed_candles": processed,
            "positions_opened": opened,
            "positions_closed": closed,
            "skipped": skipped,
            "snapshot": self.snapshot(),
        }
