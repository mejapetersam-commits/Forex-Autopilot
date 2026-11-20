from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.broker.bridge import MT5SymbolSpecification
from app.main import app
from app.market_data.telemetry_store import TelemetryStore

client = TestClient(app)
TOKEN = "test-only-symbol-specification-token-32chars"


def spec_payload(symbol="EURUSDm"):
    return {
        "symbol": symbol, "digits": 5, "point": 0.00001,
        "tick_size": 0.00001, "tick_value_profit": 1.0,
        "tick_value_loss": 1.0, "contract_size": 100000,
        "volume_min": 0.01, "volume_max": 100.0, "volume_step": 0.01,
        "stops_level_points": 10, "freeze_level_points": 0,
        "trade_allowed": True, "base_currency": "EUR",
        "profit_currency": "USD", "margin_currency": "EUR",
        "account_currency": "USD", "observed_at": datetime.now(timezone.utc).isoformat(),
    }


def test_symbol_specification_model_rejects_invalid_volume_constraints():
    payload = spec_payload()
    payload["volume_max"] = 0.001
    with pytest.raises(ValueError, match="volume constraints"):
        MT5SymbolSpecification.model_validate(payload)


def test_symbol_specifications_are_persisted_and_normalized(tmp_path):
    store = TelemetryStore(tmp_path / "specs.sqlite3")
    store.save_symbol_specification(MT5SymbolSpecification.model_validate(spec_payload()))
    result = store.latest_symbol_specification("eurusdm")
    assert result["symbol"] == "EURUSDM"
    assert result["trade_allowed"] is True
    assert result["tick_value_loss"] == 1.0


def test_older_symbol_specification_snapshot_cannot_overwrite_newer_data(tmp_path):
    from datetime import timedelta

    store = TelemetryStore(tmp_path / "spec-order.sqlite3")
    now = datetime.now(timezone.utc)
    newer = spec_payload()
    newer["observed_at"] = now.isoformat()
    newer["tick_value_profit"] = 2.5
    older = spec_payload()
    older["observed_at"] = (now - timedelta(minutes=5)).isoformat()
    older["tick_value_profit"] = 1.0

    store.save_symbol_specification(MT5SymbolSpecification.model_validate(newer))
    store.save_symbol_specification(MT5SymbolSpecification.model_validate(older))

    result = store.latest_symbol_specification("EURUSDm")
    assert result["tick_value_profit"] == pytest.approx(2.5)
    assert result["observed_at"] == now.isoformat()


def test_symbol_specification_endpoint_requires_auth_and_persists(monkeypatch, tmp_path):
    monkeypatch.setenv("FOREX_AUTOPILOT_BRIDGE_TOKEN", TOKEN)
    monkeypatch.setenv("FOREX_AUTOPILOT_TELEMETRY_DB", str(tmp_path / "spec-api.sqlite3"))
    denied = client.post("/api/v1/mt5/specifications", json=spec_payload())
    assert denied.status_code == 401
    accepted = client.post(
        "/api/v1/mt5/specifications",
        headers={"X-Bridge-Token": TOKEN},
        json=spec_payload(),
    )
    assert accepted.status_code == 200
    listed = client.get(
        "/api/v1/mt5/specifications",
        headers={"X-Bridge-Token": TOKEN},
    )
    assert listed.status_code == 200
    assert listed.json()["data"][0]["symbol"] == "EURUSDM"


def test_backtest_derives_pip_value_from_account_currency_tick_spec(monkeypatch, tmp_path):
    monkeypatch.setenv("FOREX_AUTOPILOT_BRIDGE_TOKEN", TOKEN)
    monkeypatch.setenv("FOREX_AUTOPILOT_TELEMETRY_DB", str(tmp_path / "pip-value.sqlite3"))
    headers = {"X-Bridge-Token": TOKEN}
    stored = client.post("/api/v1/mt5/specifications", headers=headers, json=spec_payload())
    assert stored.status_code == 200
    # No explicit pip inputs: 5-digit FX pip = 10 points; one pip = 10 ticks.
    # Tick value is already denominated in account currency by MT5.
    response = client.get(
        "/api/v1/backtests/run/EURUSDm/H1?limit=61",
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["pip_size_used"] == pytest.approx(0.0001)
    assert payload["pip_value_per_lot_used"] == pytest.approx(10.0)
    assert payload["pip_value_source"] == "broker_symbol_specification"


def test_backtest_refuses_to_guess_pip_value_without_broker_metadata(monkeypatch, tmp_path):
    monkeypatch.setenv("FOREX_AUTOPILOT_BRIDGE_TOKEN", TOKEN)
    monkeypatch.setenv("FOREX_AUTOPILOT_TELEMETRY_DB", str(tmp_path / "no-specs.sqlite3"))
    response = client.get(
        "/api/v1/backtests/run/EURUSDm/H1?limit=61",
        headers={"X-Bridge-Token": TOKEN},
    )
    assert response.status_code == 409
