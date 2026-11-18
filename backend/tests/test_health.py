
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "environment": "demo",
        "trading_enabled": False,
    }


def test_system_status():
    response = client.get("/api/v1/system")

    assert response.status_code == 200

    data = response.json()

    assert data["project"] == "FOREX AUTOPILOT"
    assert data["stage"] == "development"
    assert data["broker_connected"] is False
    assert data["execution_mode"] == "disabled"
