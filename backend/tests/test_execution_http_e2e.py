import hashlib
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app import main
from app.execution.ledger import ExecutionLedger
from app.execution.command_queue import ExecutionCommandQueue
from app.market_data.telemetry_store import TelemetryStore
from app.broker.bridge import (
    MT5AccountSnapshot,
    MT5ExecutionDeal,
    MT5ExecutionHistory,
    MT5ExecutionOrder,
    MT5ExecutionOrderHistory,
    MT5ExecutionState,
    MT5Heartbeat,
    MT5Quote,
    MT5SymbolSpecification,
)


def test_demo_execution_full_http_lifecycle(monkeypatch, tmp_path):
    db_path = str(tmp_path / "isolated-e2e.sqlite3")
    ledger = ExecutionLedger(db_path)
    queue = ExecutionCommandQueue(db_path)
    store = TelemetryStore(db_path)

    monkeypatch.setattr(main, "execution_ledger", lambda: ledger)
    monkeypatch.setattr(main, "execution_command_queue", lambda: queue)
    monkeypatch.setattr(main, "telemetry_store", lambda: store)

    # Keep operational event writes outside the normal application database.
    monkeypatch.setattr(main, "record_reconciliation_events", lambda result: 0)

    admin_token = "test-admin-secret-" + ("a" * 40)
    bridge_token = "test-bridge-secret-" + ("b" * 40)

    monkeypatch.setenv("FOREX_AUTOPILOT_ADMIN_TOKEN", admin_token)
    monkeypatch.setenv("FOREX_AUTOPILOT_BRIDGE_TOKEN", bridge_token)
    monkeypatch.setenv("FOREX_AUTOPILOT_ENVIRONMENT", "demo")
    monkeypatch.setenv("FOREX_AUTOPILOT_DEMO_EXECUTION_ENABLED", "true")
    monkeypatch.setenv("FOREX_AUTOPILOT_EXECUTION_SYMBOLS", "EURUSDm")
    monkeypatch.setenv("FOREX_AUTOPILOT_MAX_DAILY_LOSS_PCT", "1.0")
    monkeypatch.setenv("FOREX_AUTOPILOT_MAX_RISK_PER_TRADE_PCT", "0.25")
    monkeypatch.setenv("FOREX_AUTOPILOT_MAX_PORTFOLIO_STOP_RISK_PCT", "0.50")
    monkeypatch.setenv("FOREX_AUTOPILOT_EXECUTION_MAGIC", "61119001")

    # These controls are changed only in the temporary test database.
    ledger.set_control("trading_paused", False)
    ledger.set_control("kill_switch_active", False)

    admin = {"x-admin-token": admin_token}
    bridge = {"x-bridge-token": bridge_token}
    server = "Exness-MT5Trial"
    terminal_id = "demo-terminal"
    symbol = "EURUSDm"
    now = datetime.now(timezone.utc)

    with TestClient(main.app) as client:
        # 1. Send fresh terminal telemetry through authenticated HTTP endpoints.
        telemetry = [
            (
                "/api/v1/mt5/heartbeat",
                MT5Heartbeat(
                    server=server, terminal_connected=True, observed_at=now
                ),
            ),
            (
                "/api/v1/mt5/account",
                MT5AccountSnapshot(
                    server=server, account_currency="USD",
                    balance=1000, equity=1000, margin=0,
                    free_margin=1000, leverage=100, observed_at=now,
                ),
            ),
            (
                "/api/v1/mt5/quote",
                MT5Quote(
                    symbol=symbol, bid=1.1000, ask=1.1001, timestamp=now
                ),
            ),
            (
                "/api/v1/mt5/specifications",
                MT5SymbolSpecification(
                    symbol=symbol, digits=5, point=0.00001,
                    tick_size=0.00001, tick_value_profit=1,
                    tick_value_loss=1, contract_size=100000,
                    volume_min=0.01, volume_max=100, volume_step=0.01,
                    stops_level_points=10, freeze_level_points=0,
                    trade_allowed=True, base_currency="EUR",
                    profit_currency="USD", margin_currency="EUR",
                    account_currency="USD", observed_at=now,
                ),
            ),
            (
                "/api/v1/mt5/execution/state",
                MT5ExecutionState(
                    terminal_id=terminal_id, environment="demo",
                    server=server, observed_at=now,
                    daily_loss_pct=0, positions=[],
                ),
            ),
        ]

        for path, model in telemetry:
            response = client.post(
                path, headers=bridge, json=model.model_dump(mode="json")
            )
            assert response.status_code == 200, (path, response.text)

        # 2. Preflight a new intent using the admin API.
        intent_id = "e2e-http-001"
        preflight = client.post(
            "/api/v1/admin/execution/intents/preflight",
            headers=admin,
            json={
                "idempotency_key": intent_id,
                "symbol": symbol,
                "side": "buy",
                "volume_lots": 0.01,
                "stop_loss": 1.0991,
                "take_profit": 1.1020,
                "requested_at": now.isoformat(),
            },
        )
        assert preflight.status_code == 200, preflight.text
        assert preflight.json()["status"] == "approved"
        assert preflight.json()["broker_submission_attempted"] is False

        # 3. Explicitly queue the approved intent in the isolated demo test.
        queued = client.post(
            f"/api/v1/admin/execution/intents/{intent_id}/queue",
            headers=admin,
        )
        assert queued.status_code == 200, queued.text
        command_id = queued.json()["command_id"]
        assert queued.json()["environment"] == "demo"
        assert queued.json()["trading_enabled"] is False

        # 4. Simulate the terminal polling for and acknowledging the command.
        polled = client.get(
            "/api/v1/mt5/execution/commands/next",
            headers=bridge,
            params={"terminal_id": terminal_id},
        )
        assert polled.status_code == 200, polled.text
        command = polled.json()["command"]
        assert command is not None
        assert command["command_id"] == command_id
        assert command["intent_id"] == intent_id

        acknowledged = client.post(
            f"/api/v1/mt5/execution/commands/{command_id}/result",
            headers=bridge,
            json={
                "terminal_id": terminal_id,
                "outcome": "acknowledged",
                "result": {
                    "intent_id": intent_id,
                    "broker_order_id": "12345",
                },
            },
        )
        assert acknowledged.status_code == 200, acknowledged.text
        assert acknowledged.json()["intent_status"] == "acknowledged"

        # 5. Simulate broker order and immutable deal-history uploads.
        tag = hashlib.sha256(intent_id.encode("utf-8")).hexdigest()[:12]
        history_from = now - timedelta(minutes=5)

        order_history = MT5ExecutionOrderHistory(
            terminal_id=terminal_id,
            environment="demo",
            server=server,
            history_from=history_from,
            history_to=now,
            observed_at=now,
            orders=[
                MT5ExecutionOrder(
                    order_ticket="12345",
                    symbol=symbol,
                    order_type="buy",
                    state="filled",
                    initial_volume=0.01,
                    current_volume=0.0,
                    price=1.1001,
                    stop_loss=1.0991,
                    take_profit=1.1020,
                    magic=61119001,
                    comment=f"FA:{tag}",
                    setup_at=now - timedelta(minutes=2),
                    done_at=now,
                )
            ],
        )
        orders_response = client.post(
            "/api/v1/mt5/execution/orders",
            headers=bridge,
            json=order_history.model_dump(mode="json"),
        )
        assert orders_response.status_code == 200, orders_response.text

        deal_history = MT5ExecutionHistory(
            terminal_id=terminal_id,
            environment="demo",
            server=server,
            history_from=history_from,
            history_to=now,
            observed_at=now,
            deals=[
                MT5ExecutionDeal(
                    deal_ticket="98765",
                    order_ticket="12345",
                    position_id="54321",
                    symbol=symbol,
                    side="buy",
                    entry="in",
                    volume_lots=0.01,
                    price=1.1001,
                    magic=61119001,
                    comment=f"FA:{tag}",
                    occurred_at=now,
                )
            ],
        )
        deals_response = client.post(
            "/api/v1/mt5/execution/history",
            headers=bridge,
            json=deal_history.model_dump(mode="json"),
        )
        assert deals_response.status_code == 200, deals_response.text

        # 6. Trigger broker-history reconciliation through the admin API.
        reconciled = client.get(
            "/api/v1/monitoring/reconciliation",
            headers=admin,
        )
        assert reconciled.status_code == 200, reconciled.text
        result = reconciled.json()

        assert result["status"] == "complete", result
        assert len(result["results"]) == 1, result
        assert result["results"][0]["result"] == "reconciled_full_fill", result
        assert ledger.get_intent(intent_id)["status"] == "reconciled"

        # 7. Repeat reconciliation: terminal outcome must remain stable.
        repeated = client.get(
            "/api/v1/monitoring/reconciliation",
            headers=admin,
        )
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["status"] == "no_work"
        assert ledger.get_intent(intent_id)["status"] == "reconciled"
