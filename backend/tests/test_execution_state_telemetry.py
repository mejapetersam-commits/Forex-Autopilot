from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app import main
from app.broker.bridge import MT5ExecutionState, MT5OpenPosition
from app.market_data.telemetry_store import TelemetryStore


def sample_state(**overrides):
    values = {
        "terminal_id": "mt5-demo-1",
        "environment": "demo",
        "server": "Exness-MT5Trial",
        "observed_at": datetime.now(timezone.utc),
        "positions": [{
            "ticket": "123456", "symbol": "EURUSDm", "side": "buy",
            "volume_lots": 0.01, "open_price": 1.085,
            "stop_loss": 1.08, "take_profit": 1.095,
            "magic": 61119001, "comment": "FA:abcdef0123456789",
        }],
    }
    values.update(overrides)
    return MT5ExecutionState(**values)


def test_execution_state_requires_timezone_and_unique_position_tickets():
    with pytest.raises(ValidationError):
        sample_state(observed_at=datetime(2026, 11, 19))
    duplicate = [{
        "ticket": "1", "symbol": "EURUSDm", "side": "buy",
        "volume_lots": 0.01, "open_price": 1.08,
        "stop_loss": 1.07, "take_profit": 1.09, "magic": 1,
    }] * 2
    with pytest.raises(ValidationError, match="unique"):
        sample_state(positions=duplicate)


def test_execution_state_rejects_non_finite_position_values():
    with pytest.raises(ValidationError):
        MT5OpenPosition(
            ticket="1", symbol="EURUSDm", side="buy", volume_lots=float("nan"),
            open_price=1.08, stop_loss=1.07, take_profit=1.09, magic=1,
        )


def test_execution_state_is_persisted_and_retrieved(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry.sqlite3")
    payload = sample_state()
    store.save_execution_state(payload)
    result = store.latest_execution_state()
    assert result["terminal_id"] == "mt5-demo-1"
    assert result["environment"] == "demo"
    assert result["positions_count"] == 1
    assert result["positions"][0]["ticket"] == "123456"


def test_execution_state_monitor_flags_missing_protective_stop(monkeypatch, tmp_path):
    store = TelemetryStore(tmp_path / "telemetry.sqlite3")
    payload = sample_state(positions=[{
        "ticket": "123456", "symbol": "EURUSDm", "side": "buy",
        "volume_lots": 0.01, "open_price": 1.085,
        "stop_loss": 0, "take_profit": 1.095,
        "magic": 61119001, "comment": "FA:abcdef0123456789",
    }])
    store.save_execution_state(payload)
    monkeypatch.setattr(main, "telemetry_store", lambda: store)
    monkeypatch.setenv("FOREX_AUTOPILOT_EXECUTION_MAGIC", "61119001")
    result = main.latest_execution_state()
    assert result["status"] == "critical"
    assert result["issues"] == ["managed_position_missing_protective_level"]
    assert result["protective_stop_alerts"][0]["missing_stop_loss"] is True


def test_execution_state_monitor_ignores_unmanaged_positions(monkeypatch, tmp_path):
    store = TelemetryStore(tmp_path / "telemetry.sqlite3")
    payload = sample_state(positions=[{
        "ticket": "123456", "symbol": "EURUSDm", "side": "buy",
        "volume_lots": 0.01, "open_price": 1.085,
        "stop_loss": 0, "take_profit": 0,
        "magic": 123, "comment": "manual-trade",
    }])
    store.save_execution_state(payload)
    monkeypatch.setattr(main, "telemetry_store", lambda: store)
    monkeypatch.setenv("FOREX_AUTOPILOT_EXECUTION_MAGIC", "61119001")
    result = main.latest_execution_state()
    assert result["status"] == "healthy"
    assert result["managed_positions_count"] == 0


def test_execution_state_monitor_flags_non_demo_terminal(monkeypatch, tmp_path):
    store = TelemetryStore(tmp_path / "telemetry.sqlite3")
    store.save_execution_state(sample_state(environment="real"))
    monkeypatch.setattr(main, "telemetry_store", lambda: store)
    result = main.latest_execution_state()
    assert result["status"] == "critical"
    assert "terminal_not_on_demo_account" in result["issues"]


def test_execution_state_monitor_flags_stale_snapshot(monkeypatch, tmp_path):
    store = TelemetryStore(tmp_path / "telemetry.sqlite3")
    stale = datetime(2020, 1, 1, tzinfo=timezone.utc)
    store.save_execution_state(sample_state(observed_at=stale))
    monkeypatch.setattr(main, "telemetry_store", lambda: store)
    result = main.latest_execution_state()
    assert result["status"] == "critical"
    assert "execution_state_stale" in result["issues"]
