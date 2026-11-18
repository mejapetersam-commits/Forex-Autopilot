import os
from hmac import compare_digest

from fastapi import Depends, FastAPI, Header, HTTPException, status

from app.broker.bridge import MT5AccountSnapshot, MT5Heartbeat, MT5Quote

app = FastAPI(title="FOREX AUTOPILOT API", version="0.2.0")


def require_bridge_token(
    x_bridge_token: str | None = Header(default=None),
) -> None:
    """Authenticate the read-only MT5 bridge using a server-side secret."""
    expected = os.getenv("FOREX_AUTOPILOT_BRIDGE_TOKEN")
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MT5 bridge is not configured.",
        )
    if not x_bridge_token or not compare_digest(x_bridge_token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bridge authentication.",
        )


@app.get("/health")
def health():
    return {"status": "ok", "environment": "demo", "trading_enabled": False}


@app.get("/api/v1/system")
def system_status():
    # The bridge is read-only in this development phase.
    return {
        "project": "FOREX AUTOPILOT",
        "stage": "development",
        "broker_connected": False,
        "execution_mode": "disabled",
        "environment": "demo",
        "mt5_bridge_mode": "read_only",
    }


@app.post(
    "/api/v1/mt5/heartbeat",
    dependencies=[Depends(require_bridge_token)],
)
def mt5_heartbeat(payload: MT5Heartbeat):
    return {
        "accepted": True,
        "platform": "MT5",
        "server": payload.server,
        "terminal_connected": payload.terminal_connected,
        "trading_enabled": False,
        "execution_mode": "disabled",
    }


@app.post(
    "/api/v1/mt5/account",
    dependencies=[Depends(require_bridge_token)],
)
def mt5_account_snapshot(payload: MT5AccountSnapshot):
    return {
        "accepted": True,
        "server": payload.server,
        "account_currency": payload.account_currency,
        "equity": payload.equity,
        "observed_at": payload.observed_at,
        "trading_enabled": False,
    }


@app.post(
    "/api/v1/mt5/quote",
    dependencies=[Depends(require_bridge_token)],
)
def mt5_quote(payload: MT5Quote):
    return {
        "accepted": True,
        "symbol": payload.symbol,
        "bid": payload.bid,
        "ask": payload.ask,
        "timestamp": payload.timestamp,
        "trading_enabled": False,
    }
