from fastapi import FastAPI

app = FastAPI(title="FOREX AUTOPILOT API", version="0.1.0")

@app.get("/health")
def health():
    return {"status": "ok", "environment": "demo", "trading_enabled": False}

@app.get("/api/v1/system")
def system_status():
    # Initial scaffold: no broker connection and no live execution.
    return {
        "project": "FOREX AUTOPILOT",
        "stage": "development",
        "broker_connected": False,
        "execution_mode": "disabled",
        "environment": "demo",
    }
