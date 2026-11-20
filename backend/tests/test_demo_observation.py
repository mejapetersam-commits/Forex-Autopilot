from app.market_data.telemetry_store import TelemetryStore


def insert_deal(store, ticket, entry, symbol="EURUSDM", magic=61119001, volume=0.01):
    with store._connect() as connection:
        connection.execute(
            """INSERT INTO execution_deals(
                deal_ticket, order_ticket, position_id, terminal_id, environment,
                server, symbol, side, entry, volume_lots, price, magic, comment,
                occurred_at, observed_at
            ) VALUES (?, ?, ?, 'terminal-demo', 'demo', 'Exness-MT5Trial',
                      ?, 'buy', ?, ?, 1.10000, ?, 'test', ?, ?)""",
            (ticket, "order-" + ticket, "position-" + ticket, symbol, entry,
             volume, magic, "2026-11-19T10:00:00+00:00",
             "2026-11-19T10:01:00+00:00"),
        )


def test_demo_observation_rolls_up_only_broker_confirmed_deals(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry.sqlite3")
    insert_deal(store, "deal-1", "in")
    insert_deal(store, "deal-2", "out")
    insert_deal(store, "deal-3", "in", symbol="GBPUSDm", magic=61119002, volume=0.02)

    summary = store.demo_observation_summary()

    assert summary["deal_totals"]["deal_count"] == 3
    assert summary["deal_totals"]["terminal_count"] == 1
    assert summary["deal_totals"]["strategy_magic_count"] == 2
    assert len(summary["groups"]) == 2
    eur = next(row for row in summary["groups"] if row["symbol"] == "EURUSDM")
    assert eur["entry_deals"] == 1
    assert eur["exit_deals"] == 1
    assert eur["gross_deal_volume_lots"] == 0.02
    assert summary["pnl_available"] is False
    assert summary["latest_terminal"] is None


def test_demo_observation_is_empty_and_does_not_fabricate_results(tmp_path):
    summary = TelemetryStore(tmp_path / "empty.sqlite3").demo_observation_summary()
    assert summary["deal_totals"]["deal_count"] == 0
    assert summary["groups"] == []
    assert summary["pnl_available"] is False
