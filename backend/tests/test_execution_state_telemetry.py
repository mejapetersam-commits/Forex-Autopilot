from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app import main
from app.broker.bridge import MT5ExecutionState, MT5OpenPosition, MT5Quote, MT5SymbolSpecification
from app.market_data.telemetry_store import TelemetryStore


def sample_state(**overrides):
    values = {
        "terminal_id": "mt5-demo-1",
        "environment": "demo",
        "server": "Exness-MT5Trial",
        "observed_at": datetime.now(timezone.utc),
        "daily_loss_pct": 0.0,
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

def test_execution_state_monitor_flags_daily_loss_limit(monkeypatch, tmp_path):
    store = TelemetryStore(tmp_path / "telemetry.sqlite3")
    store.save_execution_state(sample_state(daily_loss_pct=1.2))
    monkeypatch.setattr(main, "telemetry_store", lambda: store)
    monkeypatch.setenv("FOREX_AUTOPILOT_MAX_DAILY_LOSS_PCT", "1.0")
    result = main.latest_execution_state()
    assert result["status"] == "critical"
    assert "daily_loss_limit_reached" in result["issues"]


def test_unprotected_managed_position_automatically_trips_pause_and_kill_switch(monkeypatch, tmp_path):
    store = TelemetryStore(tmp_path / "shared.sqlite3")
    ledger = __import__("app.execution.ledger", fromlist=["ExecutionLedger"]).ExecutionLedger(
        str(tmp_path / "shared.sqlite3")
    )
    ledger.set_control("trading_paused", False)
    ledger.set_control("kill_switch_active", False)
    monkeypatch.setattr(main, "telemetry_store", lambda: store)
    monkeypatch.setattr(main, "execution_ledger", lambda: ledger)
    payload = sample_state(positions=[{
        "ticket": "123456", "position_id": "998877", "symbol": "EURUSDm",
        "side": "buy", "volume_lots": 0.01, "open_price": 1.085,
        "stop_loss": 0, "take_profit": 1.095, "magic": 61119001,
        "comment": "FA:abcdef0123456789",
    }])
    response = main.mt5_execution_state(payload)
    assert response["protective_guard"]["status"] == "critical"
    assert response["new_entries_paused"] is True
    assert ledger.controls() == {"trading_paused": True, "kill_switch_active": True}


def test_protective_guard_detects_wrong_side_stop_from_fresh_broker_quote(monkeypatch, tmp_path):
    store = TelemetryStore(tmp_path / "telemetry.sqlite3")
    now = datetime.now(timezone.utc)
    store.save_quote(MT5Quote(symbol="EURUSDm", bid=1.1000, ask=1.1001, timestamp=now))
    store.save_symbol_specification(MT5SymbolSpecification(
        symbol="EURUSDm", digits=5, point=0.00001, tick_size=0.00001,
        tick_value_profit=1, tick_value_loss=1, contract_size=100000,
        volume_min=0.01, volume_max=100, volume_step=0.01,
        stops_level_points=10, freeze_level_points=0, trade_allowed=True,
        base_currency="EUR", profit_currency="USD", margin_currency="EUR",
        account_currency="USD", observed_at=now,
    ))
    payload = sample_state(positions=[{
        "ticket": "123456", "position_id": "998877", "symbol": "EURUSDm",
        "side": "buy", "volume_lots": 0.01, "open_price": 1.085,
        "stop_loss": 1.1000, "take_profit": 1.105, "magic": 61119001,
    }])
    result = main.protective_stop_guard(payload, store)
    assert "buy_stop_wrong_side_or_inside_broker_distance" in result["alerts"][0]["reasons"]
