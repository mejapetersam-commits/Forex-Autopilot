from app.execution.trade_attribution import build_trade_attribution
from app.broker.bridge import MT5ExecutionDeal


def deal(ticket, entry, side, volume, *, profit=0.0, commission=0.0, swap=0.0, fee=0.0,
         position="9001", at=None, magic=61119001, symbol="EURUSDM"):
    return {
        "deal_ticket": str(ticket), "order_ticket": "o" + str(ticket),
        "position_id": position, "terminal_id": "terminal-demo", "environment": "demo",
        "server": "Exness-MT5Trial", "symbol": symbol, "side": side, "entry": entry,
        "volume_lots": volume, "price": 1.1, "magic": magic, "comment": "",
        "occurred_at": at or f"2026-11-19T10:0{ticket}:00+00:00",
        "profit": profit, "commission": commission, "swap": swap, "fee": fee,
    }


def test_partial_entries_and_exits_are_one_closed_trade_with_all_cash_components():
    rows = [
        deal(1, "in", "buy", 0.02, commission=-0.10),
        deal(2, "in", "buy", 0.01, commission=-0.05),
        deal(3, "out", "sell", 0.01, profit=2.0, commission=-0.05),
        deal(4, "out", "sell", 0.02, profit=4.0, commission=-0.10, swap=-0.20, fee=-0.03),
    ]
    result = build_trade_attribution(rows)
    assert result["closed_trade_count"] == 1
    assert result["pnl_complete_trade_count"] == 1
    assert result["net_realized_pnl"] == 5.47
    assert result["win_rate_pct"] == 100.0
    assert result["open_position_count"] == 0


def test_same_second_deals_are_ordered_by_numeric_broker_ticket():
    rows = [
        deal(2, "in", "buy", 0.01, at="2026-11-19T10:00:00+00:00"),
        deal(10, "out", "sell", 0.01, profit=1.0, at="2026-11-19T10:00:00+00:00"),
    ]
    result = build_trade_attribution(rows)
    assert result["closed_trade_count"] == 1
    assert result["pnl_complete_trade_count"] == 1
    assert result["net_realized_pnl"] == 1.0

def test_partial_exit_does_not_finalize_remaining_position():
    rows = [
        deal(1, "in", "buy", 0.03),
        deal(2, "out", "sell", 0.01, profit=1.0),
    ]
    result = build_trade_attribution(rows)
    assert result["closed_trade_count"] == 0
    assert result["open_position_count"] == 1
    assert abs(result["open_positions"][0]["remaining_volume_lots"] - 0.02) < 1e-9
    assert result["net_realized_pnl"] == 0


def test_inout_reversal_closes_old_cycle_and_starts_new_cycle():
    rows = [
        deal(1, "in", "buy", 0.02, commission=-0.10),
        deal(2, "inout", "sell", 0.03, profit=3.0, commission=-0.15),
        deal(3, "out", "buy", 0.01, profit=-0.5, commission=-0.05),
    ]
    result = build_trade_attribution(rows)
    assert result["closed_trade_count"] == 2
    assert result["pnl_complete_trade_count"] == 2
    assert result["open_position_count"] == 0
    assert result["closed_trades"][0]["profit"] == 3.0
    assert result["closed_trades"][1]["profit"] == -0.5
    assert abs(result["net_realized_pnl"] - 2.2) < 1e-9


def test_legacy_missing_cash_fields_are_not_fabricated_as_zero():
    rows = [
        deal(1, "in", "buy", 0.01),
        {**deal(2, "out", "sell", 0.01, profit=1.0), "commission": None},
    ]
    result = build_trade_attribution(rows)
    assert result["closed_trade_count"] == 1
    assert result["pnl_complete_trade_count"] == 0
    assert result["pnl_incomplete_trade_count"] == 1
    assert result["net_realized_pnl"] == 0
    assert result["expectancy_per_trade"] is None
    assert result["coverage"] == "partial"


def test_unmatched_exit_is_reported_not_counted_as_a_trade():
    result = build_trade_attribution([deal(1, "out", "sell", 0.01, profit=5.0)])
    assert result["closed_trade_count"] == 0
    assert result["unmatched_deal_count"] == 1


def test_deal_model_rejects_non_finite_broker_cash_amount():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        MT5ExecutionDeal(
            deal_ticket="1", order_ticket="2", position_id="3", symbol="EURUSDM",
            side="buy", entry="in", volume_lots=0.01, price=1.1, magic=1,
            occurred_at="2026-11-19T10:00:00+00:00", profit=float("nan"),
        )


def test_store_persists_cash_components_idempotently_and_exposes_currency(tmp_path):
    from datetime import datetime, timezone
    import pytest
    from app.broker.bridge import MT5ExecutionDeal, MT5ExecutionHistory
    from app.market_data.telemetry_store import TelemetryStore

    store = TelemetryStore(tmp_path / "cash.sqlite3")
    stamp = datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc)
    entry = MT5ExecutionDeal(
        deal_ticket="100", order_ticket="200", position_id="9001", symbol="EURUSDM",
        side="buy", entry="in", volume_lots=0.01, price=1.1, magic=61119001,
        occurred_at=stamp, profit=0, commission=-0.1, swap=0, fee=0,
    )
    exit_deal = MT5ExecutionDeal(
        deal_ticket="101", order_ticket="201", position_id="9001", symbol="EURUSDM",
        side="sell", entry="out", volume_lots=0.01, price=1.101, magic=61119001,
        occurred_at=stamp.replace(minute=1), profit=1.0, commission=-0.1, swap=0, fee=-0.02,
    )
    payload = MT5ExecutionHistory(
        terminal_id="terminal-demo", environment="demo", server="Exness-MT5Trial",
        history_from=stamp, history_to=stamp.replace(minute=2),
        observed_at=stamp.replace(minute=2), deals=[entry, exit_deal],
    )
    store.save_execution_history(payload)
    store.save_execution_history(payload)
    with store._connect() as connection:
        connection.execute(
            "INSERT INTO account_snapshots(server, account_currency, balance, equity, margin, free_margin, leverage, observed_at) VALUES ('Exness-MT5Trial','USD',1000,1000,0,1000,100,'2026-11-19T10:02:00+00:00')"
        )
        connection.execute(
            "INSERT INTO account_snapshots(server, account_currency, balance, equity, margin, free_margin, leverage, observed_at) VALUES ('Other-Broker','KES',5000,5000,0,5000,100,'2026-11-19T10:03:00+00:00')"
        )
    result = store.demo_trade_attribution()
    assert result["deal_count"] == 2
    assert result["closed_trade_count"] == 1
    assert result["pnl_complete_trade_count"] == 1
    assert abs(result["net_realized_pnl"] - 0.78) < 1e-9
    assert result["account_currency"] == "USD"
    assert result["groups"][0]["symbol"] == "EURUSDM"

    conflicting = exit_deal.model_copy(update={"profit": 2.0})
    bad_payload = payload.model_copy(update={"deals": [conflicting]})
    with pytest.raises(ValueError, match="Conflicting broker evidence"):
        store.save_execution_history(bad_payload)


def test_store_migrates_existing_execution_deals_table(tmp_path):
    import sqlite3
    from app.market_data.telemetry_store import TelemetryStore

    path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(
        """CREATE TABLE execution_deals (
            deal_ticket TEXT PRIMARY KEY, order_ticket TEXT NOT NULL,
            position_id TEXT NOT NULL DEFAULT '', terminal_id TEXT NOT NULL,
            environment TEXT NOT NULL CHECK(environment='demo'), server TEXT NOT NULL,
            symbol TEXT NOT NULL, side TEXT NOT NULL, entry TEXT NOT NULL,
            volume_lots REAL NOT NULL, price REAL NOT NULL, magic INTEGER NOT NULL,
            comment TEXT NOT NULL, occurred_at TEXT NOT NULL, observed_at TEXT NOT NULL
        )"""
    )
    connection.commit()
    connection.close()

    TelemetryStore(path)
    connection = sqlite3.connect(path)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(execution_deals)")}
    connection.close()
    assert {"profit", "commission", "swap", "fee"}.issubset(columns)


def test_trade_attribution_dashboard_is_read_only_and_reports_incomplete_coverage(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as main
    from app.market_data.telemetry_store import TelemetryStore

    store = TelemetryStore(tmp_path / "dashboard.sqlite3")
    insert = [
        deal(1, "in", "buy", 0.01, commission=-0.1),
        deal(2, "out", "sell", 0.01, profit=1.0, commission=-0.1),
    ]
    from datetime import datetime, timezone
    from app.broker.bridge import MT5ExecutionDeal, MT5ExecutionHistory
    stamp = datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc)
    models = [
        MT5ExecutionDeal(
            deal_ticket=row["deal_ticket"], order_ticket=row["order_ticket"],
            position_id=row["position_id"], symbol=row["symbol"], side=row["side"],
            entry=row["entry"], volume_lots=row["volume_lots"], price=row["price"],
            magic=row["magic"], comment="", occurred_at=stamp.replace(minute=i),
            profit=row["profit"], commission=row["commission"], swap=row["swap"], fee=row["fee"],
        ) for i, row in enumerate(insert)
    ]
    store.save_execution_history(MT5ExecutionHistory(
        terminal_id="terminal-demo", environment="demo", server="Exness-MT5Trial",
        history_from=stamp, history_to=stamp.replace(minute=2),
        observed_at=stamp.replace(minute=2), deals=models,
    ))
    monkeypatch.setattr(main, "telemetry_store", lambda: store)
    response = TestClient(main.app).get("/api/v1/dashboard/trade-attribution")
    assert response.status_code == 200
    body = response.json()
    assert body["closed_trade_count"] == 1
    assert abs(body["net_realized_pnl"] - 0.8) < 1e-9
    assert body["trading_enabled"] is False
    assert body["execution_mode"] == "disabled"
    assert body["read_only"] is True
