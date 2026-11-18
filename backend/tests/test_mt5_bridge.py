import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
TOKEN = "test-only-bridge-token"


@pytest.fixture(autouse=True)
def bridge_token(monkeypatch):
    monkeypatch.setenv("FOREX_AUTOPILOT_BRIDGE_TOKEN", TOKEN)


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
