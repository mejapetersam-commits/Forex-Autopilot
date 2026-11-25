from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app
import app.main as main


class FakeTelemetryStore:
    def latest_symbol_specifications(self):
        now = datetime.now(timezone.utc)
        return [
            {
                "symbol": "EURUSDm",
                "digits": 5,
                "point": 0.00001,
                "tick_size": 0.00001,
                "tick_value_profit": 1.0,
                "tick_value_loss": 1.0,
                "contract_size": 100000.0,
                "volume_min": 0.01,
                "volume_max": 100.0,
                "volume_step": 0.01,
                "stops_level_points": 10,
                "freeze_level_points": 0,
                "trade_allowed": True,
                "base_currency": "EUR",
                "profit_currency": "USD",
                "margin_currency": "EUR",
                "account_currency": "USD",
                "observed_at": now.isoformat(),
            },
            {
                "symbol": "GBPUSDm",
                "digits": 5,
                "point": 0.00001,
                "tick_size": 0.00001,
                "tick_value_profit": 1.0,
                "tick_value_loss": 1.0,
                "contract_size": 100000.0,
                "volume_min": 0.01,
                "volume_max": 100.0,
                "volume_step": 0.01,
                "stops_level_points": 20,
                "freeze_level_points": 5,
                "trade_allowed": False,
                "base_currency": "GBP",
                "profit_currency": "USD",
                "margin_currency": "GBP",
                "account_currency": "USD",
                "observed_at": (now - timedelta(minutes=10)).isoformat(),
            },
        ]


def test_broker_specifications_dashboard_is_read_only_and_marks_stale_data(monkeypatch):
    monkeypatch.setattr(main, "telemetry_store", FakeTelemetryStore)
    response = TestClient(app).get("/api/v1/dashboard/broker-specifications")

    assert response.status_code == 200
    payload = response.json()
    assert payload["read_only"] is True
    assert payload["trading_enabled"] is False
    assert payload["execution_mode"] == "disabled"
    assert len(payload["items"]) == 2

    fresh, stale = payload["items"]
    assert fresh["symbol"] == "EURUSDm"
    assert fresh["fresh"] is True
    assert fresh["volume_min"] == 0.01
    assert fresh["volume_step"] == 0.01
    assert stale["symbol"] == "GBPUSDm"
    assert stale["fresh"] is False
    assert stale["trade_allowed"] is False
