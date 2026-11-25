from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
ADMIN_TOKEN = "test-only-forex-admin-token-with-32chars"


def test_runtime_controls_require_admin_authentication(monkeypatch, tmp_path):
    monkeypatch.setenv("FOREX_AUTOPILOT_ADMIN_TOKEN", ADMIN_TOKEN)
    monkeypatch.setenv("FOREX_AUTOPILOT_TELEMETRY_DB", str(tmp_path / "controls-auth.sqlite3"))
    missing = client.post(
        "/api/v1/admin/controls/trading_paused",
        json={"enabled": False},
    )
    assert missing.status_code == 401
    invalid = client.post(
        "/api/v1/admin/controls/trading_paused",
        headers={"X-Admin-Token": "wrong"},
        json={"enabled": False},
    )
    assert invalid.status_code == 401


def test_admin_can_pause_and_emergency_stop_with_audit(monkeypatch, tmp_path):
    monkeypatch.setenv("FOREX_AUTOPILOT_ADMIN_TOKEN", ADMIN_TOKEN)
    monkeypatch.setenv("FOREX_AUTOPILOT_TELEMETRY_DB", str(tmp_path / "controls.sqlite3"))
    headers = {"X-Admin-Token": ADMIN_TOKEN}
    initial = client.get("/api/v1/admin/controls", headers=headers)
    assert initial.status_code == 200
    assert initial.json()["trading_paused"] is True
    assert initial.json()["kill_switch_active"] is True

    resumed = client.post(
        "/api/v1/admin/controls/trading_paused",
        headers=headers,
        json={"enabled": False},
    )
    assert resumed.status_code == 200
    assert resumed.json()["trading_paused"] is False
    assert resumed.json()["trading_enabled"] is False

    stopped = client.post(
        "/api/v1/admin/controls/kill_switch_active",
        headers=headers,
        json={"enabled": True},
    )
    assert stopped.status_code == 200
    assert stopped.json()["kill_switch_active"] is True
    assert len(stopped.json()["audit"]) >= 2


def test_admin_cannot_change_unknown_or_live_enable_control(monkeypatch, tmp_path):
    monkeypatch.setenv("FOREX_AUTOPILOT_ADMIN_TOKEN", ADMIN_TOKEN)
    monkeypatch.setenv("FOREX_AUTOPILOT_TELEMETRY_DB", str(tmp_path / "controls-unknown.sqlite3"))
    response = client.post(
        "/api/v1/admin/controls/live_trading_enabled",
        headers={"X-Admin-Token": ADMIN_TOKEN},
        json={"enabled": True},
    )
    assert response.status_code == 404


def test_admin_token_is_required_to_be_strong(monkeypatch, tmp_path):
    monkeypatch.setenv("FOREX_AUTOPILOT_ADMIN_TOKEN", "weak")
    monkeypatch.setenv("FOREX_AUTOPILOT_TELEMETRY_DB", str(tmp_path / "controls-weak.sqlite3"))
    response = client.get("/api/v1/admin/controls", headers={"X-Admin-Token": "weak"})
    assert response.status_code == 503
