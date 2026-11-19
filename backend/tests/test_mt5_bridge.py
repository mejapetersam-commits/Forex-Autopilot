from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
TOKEN = "test-only-bridge-token-with-32-plus-chars"


@pytest.fixture(autouse=True)
def bridge_token(monkeypatch, tmp_path):
    monkeypatch.setenv("FOREX_AUTOPILOT_BRIDGE_TOKEN", TOKEN)
    monkeypatch.setenv(
        "FOREX_AUTOPILOT_TELEMETRY_DB", str(tmp_path / "telemetry.sqlite3")
    )


def test_bridge_rejects_missing_token():
    response = client.post(
        "/api/v1/mt5/heartbeat",
        json={
            "server": "ExnessKE-MT5Trial9",
            "terminal_connected": True,
            "observed_at": "2026-11-18T12:00:00Z",
        },
    )
    assert response.status_code == 401


def test_bridge_rejects_invalid_token():
    response = client.post(
        "/api/v1/mt5/heartbeat",
        headers={"X-Bridge-Token": "wrong"},
        json={
            "server": "ExnessKE-MT5Trial9",
            "terminal_connected": True,
            "observed_at": "2026-11-18T12:00:00Z",
        },
    )
    assert response.status_code == 401


def test_bridge_is_unavailable_without_server_secret(monkeypatch):
    monkeypatch.delenv("FOREX_AUTOPILOT_BRIDGE_TOKEN")
    response = client.post(
        "/api/v1/mt5/heartbeat",
        headers={"X-Bridge-Token": TOKEN},
        json={
            "server": "ExnessKE-MT5Trial9",
            "terminal_connected": True,
            "observed_at": "2026-11-18T12:00:00Z",
        },
    )
    assert response.status_code == 503


def test_accepts_authenticated_read_only_heartbeat():
    response = client.post(
        "/api/v1/mt5/heartbeat",
        headers={"X-Bridge-Token": TOKEN},
        json={
            "server": "ExnessKE-MT5Trial9",
            "terminal_connected": True,
            "observed_at": "2026-11-18T12:00:00Z",
        },
    )
    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert response.json()["trading_enabled"] is False
    assert response.json()["execution_mode"] == "disabled"


def test_accepts_account_snapshot_without_login_or_credentials():
    response = client.post(
        "/api/v1/mt5/account",
        headers={"X-Bridge-Token": TOKEN},
        json={
            "server": "ExnessKE-MT5Trial9",
            "account_currency": "usd",
            "balance": 10000,
            "equity": 10000,
            "margin": 0,
            "free_margin": 10000,
            "leverage": 200,
            "observed_at": "2026-11-18T12:00:00Z",
        },
    )
    assert response.status_code == 200
    assert response.json()["account_currency"] == "USD"
    assert response.json()["trading_enabled"] is False


def test_accepts_authenticated_quote():
    response = client.post(
        "/api/v1/mt5/quote",
        headers={"X-Bridge-Token": TOKEN},
        json={
            "symbol": "eurusd",
            "bid": 1.08,
            "ask": 1.0801,
            "timestamp": "2026-11-18T12:00:00Z",
        },
    )
    assert response.status_code == 200
    assert response.json()["symbol"] == "EURUSD"
    assert response.json()["trading_enabled"] is False


def test_rejects_naive_quote_timestamp():
    response = client.post(
        "/api/v1/mt5/quote",
        headers={"X-Bridge-Token": TOKEN},
        json={
            "symbol": "EURUSD",
            "bid": 1.08,
            "ask": 1.0801,
            "timestamp": "2026-11-18T12:00:00",
        },
    )
    assert response.status_code == 422


def test_rejects_extra_fields_on_heartbeat():
    response = client.post(
        "/api/v1/mt5/heartbeat",
        headers={"X-Bridge-Token": TOKEN},
        json={
            "server": "ExnessKE-MT5Trial9",
            "terminal_connected": True,
            "observed_at": "2026-11-18T12:00:00Z",
            "password": "must-not-be-accepted",
        },
    )
    assert response.status_code == 422



def test_persists_and_returns_latest_account_snapshot():
    response = client.post(
        "/api/v1/mt5/account",
        headers={"X-Bridge-Token": TOKEN},
        json={
            "server": "ExnessKE-MT5Trial9",
            "account_currency": "USD",
            "balance": 10000,
            "equity": 10025,
            "margin": 50,
            "free_margin": 9975,
            "leverage": 200,
            "observed_at": "2026-11-18T12:00:00Z",
        },
    )
    assert response.status_code == 200
    assert response.json()["stored"] is True

    latest = client.get(
        "/api/v1/mt5/latest/account",
        headers={"X-Bridge-Token": TOKEN},
    )
    assert latest.status_code == 200
    assert latest.json()["data"]["balance"] == 10000
    assert latest.json()["data"]["equity"] == 10025
    assert "login" not in latest.json()["data"]
    assert "password" not in latest.json()["data"]


def test_persists_latest_quote_per_symbol_and_returns_history():
    headers = {"X-Bridge-Token": TOKEN}
    first = client.post(
        "/api/v1/mt5/quote",
        headers=headers,
        json={
            "symbol": "eurusd",
            "bid": 1.08,
            "ask": 1.0801,
            "timestamp": "2026-11-18T12:00:00Z",
        },
    )
    second = client.post(
        "/api/v1/mt5/quote",
        headers=headers,
        json={
            "symbol": "EURUSD",
            "bid": 1.081,
            "ask": 1.0811,
            "timestamp": "2026-11-18T12:00:15Z",
        },
    )
    assert first.status_code == second.status_code == 200
    assert second.json()["stored"] is True

    latest = client.get("/api/v1/mt5/latest/quotes", headers=headers)
    assert latest.status_code == 200
    assert len(latest.json()["data"]) == 1
    assert latest.json()["data"][0]["bid"] == 1.081

    history = client.get(
        "/api/v1/mt5/history/quotes/EURUSD?limit=10",
        headers=headers,
    )
    assert history.status_code == 200
    assert len(history.json()["data"]) == 2


def test_persists_and_returns_latest_heartbeat():
    headers = {"X-Bridge-Token": TOKEN}
    response = client.post(
        "/api/v1/mt5/heartbeat",
        headers=headers,
        json={
            "server": "ExnessKE-MT5Trial9",
            "terminal_connected": True,
            "observed_at": "2026-11-18T12:00:00Z",
        },
    )
    assert response.status_code == 200
    latest = client.get("/api/v1/mt5/latest/heartbeat", headers=headers)
    assert latest.status_code == 200
    assert latest.json()["data"]["terminal_connected"] is True


def test_telemetry_read_endpoints_require_authentication():
    response = client.get("/api/v1/mt5/latest/quotes")
    assert response.status_code == 401



def test_latest_quote_uses_observation_time_not_arrival_order():
    headers = {"X-Bridge-Token": TOKEN}
    newer = client.post(
        "/api/v1/mt5/quote",
        headers=headers,
        json={
            "symbol": "EURUSD",
            "bid": 1.09,
            "ask": 1.0901,
            "timestamp": "2026-11-18T12:05:00Z",
        },
    )
    delayed_old = client.post(
        "/api/v1/mt5/quote",
        headers=headers,
        json={
            "symbol": "EURUSD",
            "bid": 1.08,
            "ask": 1.0801,
            "timestamp": "2026-11-18T12:04:00Z",
        },
    )
    assert newer.status_code == delayed_old.status_code == 200

    latest = client.get("/api/v1/mt5/latest/quotes", headers=headers)
    assert latest.status_code == 200
    assert latest.json()["data"][0]["bid"] == 1.09


def test_rejects_quote_with_ask_below_bid():
    response = client.post(
        "/api/v1/mt5/quote",
        headers={"X-Bridge-Token": TOKEN},
        json={
            "symbol": "EURUSD",
            "bid": 1.081,
            "ask": 1.08,
            "timestamp": "2026-11-18T12:00:00Z",
        },
    )
    assert response.status_code == 422


def test_rejects_account_snapshot_with_missing_required_fields():
    response = client.post(
        "/api/v1/mt5/account",
        headers={"X-Bridge-Token": TOKEN},
        json={
            "server": "ExnessKE-MT5Trial9",
            "account_currency": "USD",
            "balance": 10000,
            "equity": 10000,
            "observed_at": "2026-11-18T12:00:00Z",
        },
    )
    assert response.status_code == 422



def test_telemetry_status_reports_disconnected_when_no_heartbeat_exists():
    response = client.get(
        "/api/v1/mt5/status",
        headers={"X-Bridge-Token": TOKEN},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["bridge_connected"] is False
    assert data["heartbeat"]["received"] is False
    assert data["trading_enabled"] is False


def test_telemetry_status_reports_fresh_demo_heartbeat_and_quote():
    headers = {"X-Bridge-Token": TOKEN}
    observed_at = datetime.now(timezone.utc).isoformat()
    heartbeat = client.post(
        "/api/v1/mt5/heartbeat",
        headers=headers,
        json={
            "server": "ExnessKE-MT5Trial9",
            "terminal_connected": True,
            "observed_at": observed_at,
        },
    )
    quote = client.post(
        "/api/v1/mt5/quote",
        headers=headers,
        json={
            "symbol": "EURUSD",
            "bid": 1.08,
            "ask": 1.0801,
            "timestamp": observed_at,
        },
    )
    assert heartbeat.status_code == quote.status_code == 200

    response = client.get("/api/v1/mt5/status", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["bridge_connected"] is True
    assert data["heartbeat"]["fresh"] is True
    assert data["quotes"][0]["symbol"] == "EURUSD"
    assert data["quotes"][0]["fresh"] is True
    assert data["execution_mode"] == "disabled"


def test_telemetry_status_requires_authentication():
    response = client.get("/api/v1/mt5/status")
    assert response.status_code == 401



def test_telemetry_status_does_not_treat_future_timestamp_as_fresh():
    headers = {"X-Bridge-Token": TOKEN}
    heartbeat = client.post(
        "/api/v1/mt5/heartbeat",
        headers=headers,
        json={
            "server": "ExnessKE-MT5Trial9",
            "terminal_connected": True,
            "observed_at": "2099-01-01T00:00:00Z",
        },
    )
    assert heartbeat.status_code == 200

    response = client.get("/api/v1/mt5/status", headers=headers)
    assert response.status_code == 200
    assert response.json()["bridge_connected"] is False
    assert response.json()["heartbeat"]["fresh"] is False



def test_bridge_is_unavailable_with_weak_server_secret(monkeypatch):
    monkeypatch.setenv("FOREX_AUTOPILOT_BRIDGE_TOKEN", "too-short")
    response = client.get(
        "/api/v1/mt5/status",
        headers={"X-Bridge-Token": "too-short"},
    )
    assert response.status_code == 503



def test_bulk_candle_upload_stores_eight_groups_atomically():
    headers = {"X-Bridge-Token": TOKEN}
    batches = []
    for symbol in ("EURUSDm", "GBPUSDm"):
        for timeframe in ("M5", "M15", "H1", "H4"):
            batches.append({
                "symbol": symbol,
                "timeframe": timeframe,
                "candles": [
                    {
                        "opened_at": f"2026-11-18T12:{minute:02d}:00Z",
                        "open": 1.0800,
                        "high": 1.0810,
                        "low": 1.0790,
                        "close": 1.0805,
                        "tick_volume": 100 + minute,
                    }
                    for minute in (0, 5)
                ],
            })

    response = client.post(
        "/api/v1/mt5/candles/bulk",
        headers=headers,
        json={"batches": batches},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["accepted"] is True
    assert result["stored"] is True
    assert result["batches_received"] == 8
    assert result["candles_received"] == 16
    assert result["trading_enabled"] is False

    history = client.get(
        "/api/v1/mt5/history/candles/EURUSDm/M5?limit=500",
        headers=headers,
    )
    assert history.status_code == 200
    assert history.json()["count"] == 2


def test_bulk_candle_upload_rejects_duplicate_symbol_timeframe_groups():
    headers = {"X-Bridge-Token": TOKEN}
    batch = {
        "symbol": "EURUSDm",
        "timeframe": "M5",
        "candles": [{
            "opened_at": "2026-11-18T12:00:00Z",
            "open": 1.08,
            "high": 1.081,
            "low": 1.079,
            "close": 1.0805,
            "tick_volume": 100,
        }],
    }
    response = client.post(
        "/api/v1/mt5/candles/bulk",
        headers=headers,
        json={"batches": [batch, batch]},
    )
    assert response.status_code == 422


def test_bulk_candle_upload_rejects_missing_authentication():
    response = client.post(
        "/api/v1/mt5/candles/bulk",
        json={"batches": []},
    )
    assert response.status_code == 401
