from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_dashboard_page_is_served():
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "System monitor" in response.text
    assert "read-only" in response.text.lower()


def test_dashboard_overview_defaults_to_safe_demo_state(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "FOREX_AUTOPILOT_TELEMETRY_DB", str(tmp_path / "dashboard.sqlite3")
    )
    response = client.get("/api/v1/dashboard/overview")
    assert response.status_code == 200
    data = response.json()
    assert data["environment"] == "demo"
    assert data["execution_mode"] == "disabled"
    assert data["trading_enabled"] is False
    assert data["bridge_connected"] is False
    assert data["heartbeat"] is None
    assert data["account"] is None
    assert data["quotes"] == []


def test_dashboard_overview_returns_stored_read_only_telemetry(monkeypatch, tmp_path):
    from app.broker.bridge import MT5AccountSnapshot, MT5Heartbeat, MT5Quote
    from app.market_data.telemetry_store import TelemetryStore
    from datetime import datetime, timezone

    monkeypatch.setenv(
        "FOREX_AUTOPILOT_TELEMETRY_DB", str(tmp_path / "dashboard-data.sqlite3")
    )
    store = TelemetryStore()
    now = datetime.now(timezone.utc)
    store.save_heartbeat(MT5Heartbeat(
        server="LOCAL-DEMO", terminal_connected=True, observed_at=now
    ))
    store.save_account(MT5AccountSnapshot(
        server="LOCAL-DEMO", account_currency="USD", balance=10000,
        equity=10025, margin=50, free_margin=9975, leverage=200,
        observed_at=now,
    ))
    store.save_quote(MT5Quote(
        symbol="EURUSDm", bid=1.08, ask=1.0801, timestamp=now
    ))

    data = client.get("/api/v1/dashboard/overview").json()
    assert data["bridge_connected"] is True
    assert data["account"]["balance"] == 10000
    assert data["account"]["equity"] == 10025
    assert data["quotes"][0]["symbol"] == "EURUSDM"
    assert data["quotes"][0]["fresh"] is True
    assert data["trading_enabled"] is False
    assert data["execution_mode"] == "disabled"


def test_dashboard_hides_legacy_symbols_but_preserves_quote_history(monkeypatch, tmp_path):
    from datetime import datetime, timezone

    from app.broker.bridge import MT5Quote
    from app.market_data.telemetry_store import TelemetryStore

    monkeypatch.setenv(
        "FOREX_AUTOPILOT_TELEMETRY_DB", str(tmp_path / "dashboard-symbols.sqlite3")
    )
    monkeypatch.setenv("FOREX_AUTOPILOT_DASHBOARD_SYMBOLS", "EURUSDm,GBPUSDm")
    store = TelemetryStore()
    now = datetime.now(timezone.utc)

    for symbol, bid in (("EURUSD", 1.07), ("EURUSDm", 1.08), ("GBPUSDm", 1.27)):
        store.save_quote(MT5Quote(
            symbol=symbol, bid=bid, ask=bid + 0.0001, timestamp=now
        ))

    response = client.get("/api/v1/dashboard/overview")
    assert response.status_code == 200
    assert {quote["symbol"] for quote in response.json()["quotes"]} == {
        "EURUSDM", "GBPUSDM"
    }
    assert len(store.quote_history("EURUSD")) == 1
