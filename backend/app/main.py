import os
import hashlib
from datetime import datetime, timezone
from typing import Literal
from hmac import compare_digest

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from pathlib import Path

from app.broker.bridge import MT5AccountSnapshot, MT5CandleBatch, MT5CandleBulk, MT5Heartbeat, MT5ExecutionState, MT5Quote, MT5SymbolSpecification
from app.market_data.telemetry_store import TelemetryStore
from app.market_data.indicators import calculate_indicators
from app.strategy.engine import StrategyConfig, evaluate_signal
from app.backtesting.engine import BacktestConfig, run_backtest
from app.backtesting.optimization import optimize_walk_forward
from app.market_data.quality import assess_candle_quality
from app.execution.ledger import ExecutionLedger
from app.execution.coordinator import ExecutionCoordinator
from app.execution.preflight import ExecutionSnapshot, TradeIntent, evaluate_with_runtime_controls
from app.execution.command_queue import ExecutionCommandQueue
from app.monitoring.health import assess_system_health

app = FastAPI(title="FOREX AUTOPILOT API", version="0.4.0")


class RuntimeControlUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool


class MT5ExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    terminal_id: str = Field(min_length=3, max_length=128)
    outcome: str
    result: dict


def execution_command_queue() -> ExecutionCommandQueue:
    return ExecutionCommandQueue()


class ExecutionIntentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    symbol: str = Field(min_length=1, max_length=32)
    side: Literal["buy", "sell"]
    volume_lots: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    take_profit: float = Field(gt=0)
    requested_at: datetime




def execution_ledger() -> ExecutionLedger:
    return ExecutionLedger()


def require_admin_token(
    x_admin_token: str | None = Header(default=None),
) -> None:
    expected = os.getenv("FOREX_AUTOPILOT_ADMIN_TOKEN")
    if not expected or len(expected) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin controls are unavailable until a strong admin token is configured.",
        )
    if not x_admin_token or not compare_digest(x_admin_token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin authentication.",
        )



def require_bridge_token(
    x_bridge_token: str | None = Header(default=None),
) -> None:
    """Authenticate the read-only MT5 bridge using a server-side secret."""
    expected = os.getenv("FOREX_AUTOPILOT_BRIDGE_TOKEN")
    if not expected or len(expected) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MT5 bridge requires a configured secret of at least 32 characters.",
        )
    if not x_bridge_token or not compare_digest(x_bridge_token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bridge authentication.",
        )


def telemetry_store() -> TelemetryStore:
    """Create a store using the currently configured persistent database path."""
    return TelemetryStore()


def dashboard_symbols() -> set[str]:
    """Return the symbols permitted in the active dashboard view."""
    configured = os.getenv("FOREX_AUTOPILOT_DASHBOARD_SYMBOLS", "EURUSDm,GBPUSDm")
    return {symbol.strip().upper() for symbol in configured.split(",") if symbol.strip()}



@app.get("/dashboard", include_in_schema=False)
def dashboard():
    """Serve the local read-only dashboard; API port is loopback-bound in Compose."""
    page = Path(__file__).with_name("dashboard.html")
    return FileResponse(page, media_type="text/html")


@app.get("/api/v1/dashboard/overview", include_in_schema=False)
def dashboard_overview():
    """Local read-only dashboard data. Never exposes the bridge token."""
    store = telemetry_store()
    heartbeat = store.latest_heartbeat()
    account = store.latest_account()
    active_symbols = dashboard_symbols()
    quotes = [
        quote for quote in store.latest_quotes()
        if quote["symbol"].upper() in active_symbols
    ]
    now = datetime.now(timezone.utc)

    def age_seconds(timestamp: str | None) -> float | None:
        if timestamp is None:
            return None
        observed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if observed.tzinfo is None or observed.utcoffset() is None:
            return None
        age = (now - observed.astimezone(timezone.utc)).total_seconds()
        if age < -5:
            return None
        return max(0.0, age)

    stale_after = max(5, int(os.getenv("FOREX_AUTOPILOT_TELEMETRY_STALE_AFTER_SECONDS", "60")))
    heartbeat_age = age_seconds(heartbeat["observed_at"]) if heartbeat else None
    account_age = age_seconds(account["observed_at"]) if account else None
    quote_rows = []
    for quote in quotes:
        age = age_seconds(quote["observed_at"])
        quote_rows.append({
            **quote,
            "age_seconds": round(age, 1) if age is not None else None,
            "fresh": age is not None and age <= stale_after,
        })
    connected = bool(
        heartbeat and heartbeat["terminal_connected"]
        and heartbeat_age is not None and heartbeat_age <= stale_after
    )
    return {
        "environment": "demo",
        "execution_mode": "disabled",
        "trading_enabled": False,
        "bridge_connected": connected,
        "heartbeat": {
            **heartbeat,
            "age_seconds": round(heartbeat_age, 1) if heartbeat_age is not None else None,
            "fresh": heartbeat_age is not None and heartbeat_age <= stale_after,
        } if heartbeat else None,
        "account": {
            **account,
            "age_seconds": round(account_age, 1) if account_age is not None else None,
            "fresh": account_age is not None and account_age <= stale_after,
        } if account else None,
        "quotes": quote_rows,
        "system_health": assess_system_health(heartbeat, account, quotes, stale_after_seconds=stale_after, now=now),
        "stale_after_seconds": stale_after,
        "updated_at": now.isoformat(),
    }


@app.get("/api/v1/dashboard/research", include_in_schema=False)
def dashboard_research():
    """Local dashboard research summary; exposes no credentials or execution controls."""
    store = telemetry_store()
    rows = []
    for symbol in sorted(dashboard_symbols()):
        for timeframe in ("M15", "H1", "H4"):
            candles = store.candle_history(symbol, timeframe, 500)
            signal = evaluate_signal(candles, StrategyConfig())
            quality = assess_candle_quality(candles, timeframe)
            rows.append({
                "symbol": symbol,
                "timeframe": timeframe,
                "candles": len(candles),
                "signal": signal["signal"],
                "reason": signal.get("reason", "Insufficient historical candles."),
                "latest_close": signal.get("indicators", {}).get("latest_close"),
                "research_status": signal.get("research_status", "insufficient_data"),
                "data_quality": quality["status"],
                "gap_count": quality["gap_count"],
            })
    return {
        "items": rows,
        "execution_mode": "disabled",
        "trading_enabled": False,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get(
    "/api/v1/monitoring/health",
    dependencies=[Depends(require_bridge_token)],
)
def monitoring_health():
    store = telemetry_store()
    stale_after = max(5, int(os.getenv("FOREX_AUTOPILOT_TELEMETRY_STALE_AFTER_SECONDS", "60")))
    return assess_system_health(
        store.latest_heartbeat(),
        store.latest_account(),
        store.latest_quotes(),
        stale_after_seconds=stale_after,
    )


@app.get("/api/v1/dashboard/controls", include_in_schema=False)
def dashboard_runtime_controls():
    """Expose only non-secret local pause and emergency-stop state."""
    return {
        **execution_ledger().controls(),
        "trading_enabled": False,
        "execution_mode": "disabled",
    }


@app.get(
    "/api/v1/admin/controls",
    dependencies=[Depends(require_admin_token)],
)
def admin_runtime_controls():
    return {
        **execution_ledger().controls(),
        "audit": execution_ledger().control_events(100),
        "trading_enabled": False,
        "execution_mode": "disabled",
    }


@app.post(
    "/api/v1/admin/controls/{control_key}",
    dependencies=[Depends(require_admin_token)],
)
def update_runtime_control(control_key: str, payload: RuntimeControlUpdate):
    if control_key not in {"trading_paused", "kill_switch_active"}:
        raise HTTPException(status_code=404, detail="Unsupported runtime control.")
    ledger = execution_ledger()
    ledger.set_control(control_key, payload.enabled)
    return {
        **ledger.controls(),
        "audit": ledger.control_events(20),
        "trading_enabled": False,
        "execution_mode": "disabled",
    }





def execution_snapshot_for_symbol(symbol: str) -> ExecutionSnapshot:
    """Build a fail-closed preflight snapshot exclusively from recent broker telemetry."""
    store = telemetry_store()
    now = datetime.now(timezone.utc)

    def age(value):
        if not value:
            return 1e9
        try:
            observed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if observed.tzinfo is None or observed.utcoffset() is None:
                return 1e9
            return max(-1e9, (now - observed.astimezone(timezone.utc)).total_seconds())
        except (TypeError, ValueError):
            return 1e9

    heartbeat = store.latest_heartbeat()
    account = store.latest_account()
    quote = next((item for item in store.latest_quotes()
                  if item["symbol"].upper() == symbol.strip().upper()), None)
    state = store.latest_execution_state()
    specification = store.latest_symbol_specification(symbol)
    controls = execution_ledger().controls()

    max_positions = int(os.getenv("FOREX_AUTOPILOT_MAX_OPEN_POSITIONS", "1"))
    max_daily_loss = float(os.getenv("FOREX_AUTOPILOT_MAX_DAILY_LOSS_PCT", "1.0"))
    heartbeat_age = age(heartbeat["observed_at"] if heartbeat else None)
    account_age = age(account["observed_at"] if account else None)
    quote_age = age(quote["observed_at"] if quote else None)
    state_age = age(state["observed_at"] if state else None)
    spec_age = age(specification["observed_at"] if specification else None)

    heartbeat_ok = bool(heartbeat and heartbeat["terminal_connected"] and 0 <= heartbeat_age <= 60)
    account_ok = bool(account and 0 <= account_age <= 30)
    state_ok = bool(state and state["environment"] == "demo" and 0 <= state_age <= 20)
    spec_ok = bool(specification and specification["trade_allowed"] and 0 <= spec_age <= 300)
    same_server = bool(
        heartbeat and account and state
        and heartbeat["server"] == account["server"] == state["server"]
    )
    broker_connected = heartbeat_ok and account_ok and state_ok and spec_ok and same_server

    allowlist = tuple(
        value.strip().upper()
        for value in os.getenv("FOREX_AUTOPILOT_EXECUTION_SYMBOLS", "").split(",")
        if value.strip()
    )
    digits = specification["digits"] if specification else 0
    point = specification["point"] if specification else 0.0
    pip_size = point * (10 if digits in (3, 5) else 1)
    return ExecutionSnapshot(
        environment=os.getenv("FOREX_AUTOPILOT_ENVIRONMENT", "demo"),
        trading_enabled=os.getenv("FOREX_AUTOPILOT_DEMO_EXECUTION_ENABLED", "false").lower() == "true",
        kill_switch_active=controls["kill_switch_active"],
        trading_paused=controls["trading_paused"],
        broker_connected=broker_connected,
        account_equity=float(account["equity"]) if account else 0.0,
        free_margin=float(account["free_margin"]) if account else 0.0,
        quote_bid=float(quote["bid"]) if quote else 0.0,
        quote_ask=float(quote["ask"]) if quote else 0.0,
        quote_age_seconds=quote_age,
        account_age_seconds=account_age,
        open_positions=state["positions_count"] if state else max_positions,
        daily_loss_pct=state["daily_loss_pct"] if state else max_daily_loss,
        symbol_allowlist=allowlist,
        max_spread_pips=float(os.getenv("FOREX_AUTOPILOT_MAX_SPREAD_PIPS", "2.0")),
        pip_size=pip_size,
        max_open_positions=max_positions,
        max_daily_loss_pct=max_daily_loss,
        require_broker_specification=True,
        broker_trade_allowed=specification["trade_allowed"] if specification else None,
        broker_volume_min=specification["volume_min"] if specification else None,
        broker_volume_max=specification["volume_max"] if specification else None,
        broker_volume_step=specification["volume_step"] if specification else None,
        broker_tick_size=specification["tick_size"] if specification else None,
        broker_tick_value_loss=specification["tick_value_loss"] if specification else None,
        max_volume_lots=float(os.getenv("FOREX_AUTOPILOT_MAX_VOLUME_LOTS", "0.01")),
        max_risk_per_trade_pct=float(os.getenv("FOREX_AUTOPILOT_MAX_RISK_PER_TRADE_PCT", "0.25")),
    )


@app.post(
    "/api/v1/admin/execution/intents/preflight",
    dependencies=[Depends(require_admin_token)],
)
def preflight_execution_intent(payload: ExecutionIntentRequest):
    intent = TradeIntent(
        symbol=payload.symbol.strip().upper(),
        side=payload.side,
        volume_lots=payload.volume_lots,
        stop_loss=payload.stop_loss,
        take_profit=payload.take_profit,
        requested_at=payload.requested_at,
    )
    snapshot = execution_snapshot_for_symbol(intent.symbol)
    result = ExecutionCoordinator(execution_ledger()).preflight_and_record(
        payload.idempotency_key, intent, snapshot
    )
    return {
        "intent_id": payload.idempotency_key,
        "status": result["status"],
        "preflight": result["preflight"],
        "broker_submission_attempted": False,
        "trading_enabled": False,
    }


@app.post(
    "/api/v1/admin/execution/intents/{intent_id}/queue",
    dependencies=[Depends(require_admin_token)],
)
def queue_approved_demo_intent(intent_id: str):
    """Dispatch only preflight-approved intents under explicit demo safeguards."""
    if os.getenv("FOREX_AUTOPILOT_ENVIRONMENT", "demo").strip().lower() != "demo":
        raise HTTPException(status_code=403, detail="Execution transport is demo-only.")
    if os.getenv("FOREX_AUTOPILOT_DEMO_EXECUTION_ENABLED", "false").strip().lower() != "true":
        raise HTTPException(status_code=403, detail="Demo execution transport is disabled by configuration.")
    controls = execution_ledger().controls()
    if controls["trading_paused"] or controls["kill_switch_active"]:
        raise HTTPException(status_code=423, detail="Pause or emergency stop is active.")
    intent = execution_ledger().get_intent(intent_id)
    if intent is None:
        raise HTTPException(status_code=404, detail="Order intent not found.")
    if intent["status"] != "approved":
        raise HTTPException(status_code=409, detail="Only a preflight-approved intent can be queued.")
    allowed = {v.strip().upper() for v in os.getenv("FOREX_AUTOPILOT_EXECUTION_SYMBOLS", "").split(",") if v.strip()}
    if not allowed or intent["payload"].get("symbol", "").upper() not in allowed:
        raise HTTPException(status_code=403, detail="Symbol is not in the explicit execution allowlist.")
    try:
        queued = execution_command_queue().enqueue_approved_intent(
            command_id="cmd-" + hashlib.sha256(intent_id.encode("utf-8")).hexdigest()[:32], intent_id=intent_id,
            payload=intent["payload"], environment="demo", trading_enabled=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"command_id": queued["command_id"], "status": queued["status"],
            "environment": "demo", "trading_enabled": False}


@app.get("/api/v1/mt5/execution/commands/next", dependencies=[Depends(require_bridge_token)])
def lease_next_execution_command(terminal_id: str = Query(min_length=1, max_length=128)):
    if os.getenv("FOREX_AUTOPILOT_ENVIRONMENT", "demo").strip().lower() != "demo":
        return {"command": None, "reason": "demo_environment_required"}
    if os.getenv("FOREX_AUTOPILOT_DEMO_EXECUTION_ENABLED", "false").strip().lower() != "true":
        return {"command": None, "reason": "demo_execution_disabled"}
    controls = execution_ledger().controls()
    if controls["trading_paused"] or controls["kill_switch_active"]:
        return {"command": None, "reason": "execution_safeguards_active"}
    command = execution_command_queue().lease_next(terminal_id=terminal_id)
    return {"command": command, "environment": "demo"} if command else {"command": None}


@app.post("/api/v1/mt5/execution/commands/{command_id}/result", dependencies=[Depends(require_bridge_token)])
def record_execution_command_result(command_id: str, payload: MT5ExecutionResult):
    if payload.outcome not in {"acknowledged", "rejected", "unknown"}:
        raise HTTPException(status_code=422, detail="Unsupported terminal outcome.")
    try:
        result = execution_command_queue().record_result(
            command_id, terminal_id=payload.terminal_id,
            outcome=payload.outcome, result=payload.result,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Execution command not found.")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    ledger = execution_ledger()
    intent = ledger.get_intent(result["intent_id"])
    if intent is None:
        raise HTTPException(status_code=409, detail="Command has no matching order intent.")
    reported_intent = payload.result.get("intent_id")
    if reported_intent is not None and reported_intent != result["intent_id"]:
        raise HTTPException(status_code=409, detail="Terminal result intent does not match command.")
    if intent["status"] == "approved":
        if result["status"] == "rejected":
            ledger.transition(result["intent_id"], "rejected",
                              event_type="mt5_demo_rejected", details=payload.result)
        else:
            order_id = payload.result.get("broker_order_id")
            ledger.transition(result["intent_id"], "submitted",
                              event_type="mt5_demo_submission_result",
                              broker_order_id=str(order_id) if order_id else None,
                              details={"command_id": command_id})
            next_status = "acknowledged" if result["status"] == "acknowledged" else "unknown"
            ledger.transition(result["intent_id"], next_status,
                              event_type="mt5_demo_" + next_status, details=payload.result)
    return {"command_id": result["command_id"], "status": result["status"],
            "intent_status": ledger.get_intent(result["intent_id"])["status"],
            "execution_mode": "demo_transport", "trading_enabled": False}


@app.get("/health")
def health():
    return {"status": "ok", "environment": "demo", "trading_enabled": False}


@app.get("/api/v1/system")
def system_status():
    return {
        "project": "FOREX AUTOPILOT",
        "stage": "development",
        "broker_connected": False,
        "execution_mode": "disabled",
        "environment": "demo",
        "mt5_bridge_mode": "read_only",
    }


@app.post(
    "/api/v1/mt5/specifications",
    dependencies=[Depends(require_bridge_token)],
)
def mt5_symbol_specification(payload: MT5SymbolSpecification):
    telemetry_store().save_symbol_specification(payload)
    return {
        "accepted": True,
        "stored": True,
        "symbol": payload.symbol,
        "digits": payload.digits,
        "tick_size": payload.tick_size,
        "tick_value_loss": payload.tick_value_loss,
        "account_currency": payload.account_currency,
        "trading_enabled": False,
    }


@app.get(
    "/api/v1/mt5/specifications",
    dependencies=[Depends(require_bridge_token)],
)
def latest_mt5_symbol_specifications():
    return {"data": telemetry_store().latest_symbol_specifications()}


@app.post(
    "/api/v1/mt5/heartbeat",
    dependencies=[Depends(require_bridge_token)],
)
def mt5_heartbeat(payload: MT5Heartbeat):
    telemetry_store().save_heartbeat(payload)
    return {
        "accepted": True,
        "stored": True,
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
    telemetry_store().save_account(payload)
    return {
        "accepted": True,
        "stored": True,
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
    telemetry_store().save_quote(payload)
    return {
        "accepted": True,
        "stored": True,
        "symbol": payload.symbol,
        "bid": payload.bid,
        "ask": payload.ask,
        "timestamp": payload.timestamp,
        "trading_enabled": False,
    }


@app.post(
    "/api/v1/mt5/candles",
    dependencies=[Depends(require_bridge_token)],
)
def mt5_candles(payload: MT5CandleBatch):
    """Store historical OHLC candles received from the read-only MT5 bridge."""
    stored = telemetry_store().save_candle_batch(payload)
    return {
        "accepted": True,
        "stored": True,
        "symbol": payload.symbol,
        "timeframe": payload.timeframe,
        "candles_received": stored,
        "trading_enabled": False,
    }


@app.post(
    "/api/v1/mt5/candles/bulk",
    dependencies=[Depends(require_bridge_token)],
)
def mt5_candles_bulk(payload: MT5CandleBulk):
    """Validate and atomically store a multi-symbol/timeframe candle upload."""
    counts = telemetry_store().save_candle_batches(payload.batches)
    return {
        "accepted": True,
        "stored": True,
        "batches_received": len(payload.batches),
        "candles_received": sum(counts.values()),
        "groups": [
            {"symbol": batch.symbol, "timeframe": batch.timeframe,
             "candles_received": len(batch.candles)}
            for batch in payload.batches
        ],
        "trading_enabled": False,
        "execution_mode": "disabled",
    }


@app.get(
    "/api/v1/mt5/history/candles/{symbol}/{timeframe}",
    dependencies=[Depends(require_bridge_token)],
)
def mt5_candle_history(
    symbol: str,
    timeframe: str,
    limit: int = Query(default=500, ge=1, le=5000),
):
    """Return stored candles in chronological order for analysis and charting."""
    data = telemetry_store().candle_history(symbol, timeframe, limit)
    return {"data": data, "count": len(data)}


@app.get(
    "/api/v1/market-analysis/{symbol}/{timeframe}",
    dependencies=[Depends(require_bridge_token)],
)
def market_analysis(
    symbol: str,
    timeframe: str,
    limit: int = Query(default=500, ge=1, le=5000),
):
    """Calculate deterministic indicators from stored, chronologically ordered candles."""
    normalized_symbol = symbol.strip().upper()
    normalized_timeframe = timeframe.strip().upper()
    candles = telemetry_store().candle_history(normalized_symbol, normalized_timeframe, limit)
    return {
        "symbol": normalized_symbol,
        "timeframe": normalized_timeframe,
        "analysis": calculate_indicators(candles),
        "trading_enabled": False,
    }


@app.get(
    "/api/v1/strategy/signal/{symbol}/{timeframe}",
    dependencies=[Depends(require_bridge_token)],
)
def strategy_signal(
    symbol: str,
    timeframe: str,
    limit: int = Query(default=500, ge=60, le=5000),
):
    """Return a research-only signal candidate; this endpoint cannot execute trades."""
    normalized_symbol = symbol.strip().upper()
    normalized_timeframe = timeframe.strip().upper()
    candles = telemetry_store().candle_history(
        normalized_symbol, normalized_timeframe, limit
    )
    result = evaluate_signal(candles, StrategyConfig())
    return {
        "symbol": normalized_symbol,
        "timeframe": normalized_timeframe,
        **result,
        "trading_enabled": False,
        "execution_mode": "disabled",
    }


def resolve_backtest_pip_values(
    store: TelemetryStore,
    symbol: str,
    pip_size: float | None,
    pip_value_per_lot: float | None,
) -> tuple[float, float, str]:
    """Use caller overrides or derive pip units from broker account-currency tick metadata."""
    if pip_size is not None and pip_value_per_lot is not None:
        return pip_size, pip_value_per_lot, "explicit_request_values"
    specification = store.latest_symbol_specification(symbol)
    if specification is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No broker symbol specification is stored; send MT5 specification telemetry or provide both pip inputs.",
        )
    derived_pip_size = pip_size
    if derived_pip_size is None:
        derived_pip_size = specification["point"] * (
            10 if specification["digits"] in (3, 5) else 1
        )
    derived_pip_value = pip_value_per_lot
    if derived_pip_value is None:
        derived_pip_value = (
            specification["tick_value_loss"] * derived_pip_size
            / specification["tick_size"]
        )
    if derived_pip_value <= 0 or derived_pip_size <= 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Broker specification does not provide usable pip valuation.",
        )
    return derived_pip_size, derived_pip_value, "broker_symbol_specification"


@app.get(
    "/api/v1/backtests/run/{symbol}/{timeframe}",
    dependencies=[Depends(require_bridge_token)],
)
def run_historical_backtest(
    symbol: str,
    timeframe: str,
    pip_value_per_lot: float | None = Query(default=None, gt=0),
    limit: int = Query(default=5000, ge=61, le=5000),
    initial_equity: float = Query(default=10000, gt=0),
    risk_per_trade_pct: float = Query(default=0.25, gt=0, le=1.0),
    pip_size: float | None = Query(default=None, gt=0),
    spread_pips: float = Query(default=1.0, ge=0, le=100),
    slippage_pips_per_side: float = Query(default=0.2, ge=0, le=100),
    commission_per_lot_per_side: float = Query(default=3.5, ge=0, le=1000),
):
    """Run an authenticated historical simulation on stored MT5 OHLC candles."""
    normalized_symbol = symbol.strip().upper()
    normalized_timeframe = timeframe.strip().upper()
    store = telemetry_store()
    candles = store.candle_history(normalized_symbol, normalized_timeframe, limit)
    resolved_pip_size, resolved_pip_value, pip_value_source = resolve_backtest_pip_values(
        store, normalized_symbol, pip_size, pip_value_per_lot
    )
    config = BacktestConfig(
        initial_equity=initial_equity,
        risk_per_trade_pct=risk_per_trade_pct,
        pip_size=resolved_pip_size,
        pip_value_per_lot=resolved_pip_value,
        spread_pips=spread_pips,
        slippage_pips_per_side=slippage_pips_per_side,
        commission_per_lot_per_side=commission_per_lot_per_side,
    )
    result = run_backtest(candles, config)
    return {
        "symbol": normalized_symbol,
        "timeframe": normalized_timeframe,
        "account_currency_note": "Pip value is in account currency for one standard lot.",
        "pip_size_used": resolved_pip_size,
        "pip_value_per_lot_used": resolved_pip_value,
        "pip_value_source": pip_value_source,
        **result,
        "trading_enabled": False,
        "execution_mode": "disabled",
    }


@app.get(
    "/api/v1/backtests/walk-forward/{symbol}/{timeframe}",
    dependencies=[Depends(require_bridge_token)],
)
def walk_forward_backtest(
    symbol: str,
    timeframe: str,
    pip_value_per_lot: float | None = Query(default=None, gt=0),
    limit: int = Query(default=1500, ge=400, le=5000),
    initial_equity: float = Query(default=10000, gt=0),
    risk_per_trade_pct: float = Query(default=0.25, gt=0, le=1.0),
    pip_size: float | None = Query(default=None, gt=0),
    spread_pips: float = Query(default=1.0, ge=0, le=100),
    slippage_pips_per_side: float = Query(default=0.2, ge=0, le=100),
    commission_per_lot_per_side: float = Query(default=3.5, ge=0, le=1000),
    minimum_trades: int = Query(default=5, ge=1, le=100),
):
    """Tune on earlier candles and evaluate on later, untouched windows."""
    normalized_symbol = symbol.strip().upper()
    normalized_timeframe = timeframe.strip().upper()
    store = telemetry_store()
    candles = store.candle_history(normalized_symbol, normalized_timeframe, limit)
    resolved_pip_size, resolved_pip_value, pip_value_source = resolve_backtest_pip_values(
        store, normalized_symbol, pip_size, pip_value_per_lot
    )
    config = BacktestConfig(
        initial_equity=initial_equity,
        risk_per_trade_pct=risk_per_trade_pct,
        pip_size=resolved_pip_size,
        pip_value_per_lot=resolved_pip_value,
        spread_pips=spread_pips,
        slippage_pips_per_side=slippage_pips_per_side,
        commission_per_lot_per_side=commission_per_lot_per_side,
    )
    result = optimize_walk_forward(candles, config, minimum_trades=minimum_trades)
    return {
        "symbol": normalized_symbol,
        "timeframe": normalized_timeframe,
        "pip_size_used": resolved_pip_size,
        "pip_value_per_lot_used": resolved_pip_value,
        "pip_value_source": pip_value_source,
        **result,
        "trading_enabled": False,
        "execution_mode": "disabled",
    }


@app.get(
    "/api/v1/market-data/quality/{symbol}/{timeframe}",
    dependencies=[Depends(require_bridge_token)],
)
def market_data_quality(
    symbol: str,
    timeframe: str,
    limit: int = Query(default=5000, ge=1, le=5000),
):
    """Inspect candle OHLC integrity, timestamp ordering and interval gaps."""
    normalized_symbol = symbol.strip().upper()
    normalized_timeframe = timeframe.strip().upper()
    candles = telemetry_store().candle_history(normalized_symbol, normalized_timeframe, limit)
    return {
        "symbol": normalized_symbol,
        "timeframe": normalized_timeframe,
        **assess_candle_quality(candles, normalized_timeframe),
        "trading_enabled": False,
    }



@app.post(
    "/api/v1/mt5/execution/state",
    dependencies=[Depends(require_bridge_token)],
)
def mt5_execution_state(payload: MT5ExecutionState):
    """Persist a read-only open-position snapshot; this endpoint never places orders."""
    telemetry_store().save_execution_state(payload)
    return {
        "accepted": True,
        "stored": True,
        "terminal_id": payload.terminal_id,
        "environment": payload.environment,
        "positions_received": len(payload.positions),
        "trading_enabled": False,
    }


@app.get(
    "/api/v1/monitoring/execution-state",
    dependencies=[Depends(require_bridge_token)],
)
def latest_execution_state():
    snapshot = telemetry_store().latest_execution_state()
    if snapshot is None:
        return {"status": "critical", "reason": "no_execution_state_received",
                "trading_enabled": False}
    observed = datetime.fromisoformat(snapshot["observed_at"].replace("Z", "+00:00"))
    age = (datetime.now(timezone.utc) - observed).total_seconds()
    stale_after = max(5, int(os.getenv("FOREX_AUTOPILOT_EXECUTION_STATE_STALE_SECONDS", "20")))
    expected_magic = int(os.getenv("FOREX_AUTOPILOT_EXECUTION_MAGIC", "61119001"))
    managed = [p for p in snapshot["positions"] if p["magic"] == expected_magic]
    stop_alerts = [
        {"ticket": p["ticket"], "symbol": p["symbol"],
         "missing_stop_loss": p["stop_loss"] <= 0,
         "missing_take_profit": p["take_profit"] <= 0}
        for p in managed if p["stop_loss"] <= 0 or p["take_profit"] <= 0
    ]
    issues = []
    if snapshot["environment"] != "demo":
        issues.append("terminal_not_on_demo_account")
    if age < -5 or age > stale_after:
        issues.append("execution_state_stale")
    max_daily_loss = float(os.getenv("FOREX_AUTOPILOT_MAX_DAILY_LOSS_PCT", "1.0"))
    if snapshot["daily_loss_pct"] >= max_daily_loss:
        issues.append("daily_loss_limit_reached")
    if stop_alerts:
        issues.append("managed_position_missing_protective_level")
    return {
        "status": "critical" if issues else "healthy",
        "issues": issues,
        "terminal_id": snapshot["terminal_id"],
        "environment": snapshot["environment"],
        "observed_at": snapshot["observed_at"],
        "age_seconds": round(max(0.0, age), 2),
        "positions_count": snapshot["positions_count"],
        "daily_loss_pct": snapshot["daily_loss_pct"],
        "managed_positions_count": len(managed),
        "protective_stop_alerts": stop_alerts,
        "positions": snapshot["positions"],
        "trading_enabled": False,
    }

@app.get(
    "/api/v1/mt5/latest/heartbeat",
    dependencies=[Depends(require_bridge_token)],
)
def latest_mt5_heartbeat():
    return {"data": telemetry_store().latest_heartbeat()}


@app.get(
    "/api/v1/mt5/latest/account",
    dependencies=[Depends(require_bridge_token)],
)
def latest_mt5_account():
    return {"data": telemetry_store().latest_account()}


@app.get(
    "/api/v1/mt5/latest/quotes",
    dependencies=[Depends(require_bridge_token)],
)
def latest_mt5_quotes():
    return {"data": telemetry_store().latest_quotes()}


@app.get(
    "/api/v1/mt5/history/quotes/{symbol}",
    dependencies=[Depends(require_bridge_token)],
)
def mt5_quote_history(
    symbol: str,
    limit: int = Query(default=100, ge=1, le=1000),
):
    return {"data": telemetry_store().quote_history(symbol, limit)}


@app.get(
    "/api/v1/mt5/status",
    dependencies=[Depends(require_bridge_token)],
)
def mt5_telemetry_status():
    """Summarize bridge freshness for a future monitoring dashboard."""
    store = telemetry_store()
    heartbeat = store.latest_heartbeat()
    quotes = store.latest_quotes()
    account = store.latest_account()
    now = datetime.now(timezone.utc)
    stale_after = max(5, int(os.getenv("FOREX_AUTOPILOT_TELEMETRY_STALE_AFTER_SECONDS", "60")))

    def age_seconds(timestamp: str | None) -> float | None:
        if timestamp is None:
            return None
        observed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if observed.tzinfo is None or observed.utcoffset() is None:
            return None
        age = (now - observed.astimezone(timezone.utc)).total_seconds()
        # Allow only tiny clock skew; a materially future-dated report is not fresh.
        if age < -5:
            return None
        return max(0.0, age)

    heartbeat_age = age_seconds(heartbeat["observed_at"]) if heartbeat else None
    heartbeat_fresh = heartbeat_age is not None and heartbeat_age <= stale_after
    quote_status = []
    for quote in quotes:
        quote_age = age_seconds(quote["observed_at"])
        quote_status.append({
            "symbol": quote["symbol"],
            "fresh": quote_age is not None and quote_age <= stale_after,
            "age_seconds": round(quote_age, 2) if quote_age is not None else None,
        })

    account_age = age_seconds(account["observed_at"]) if account else None
    return {
        "bridge_connected": bool(
            heartbeat and heartbeat["terminal_connected"] and heartbeat_fresh
        ),
        "heartbeat": {
            "received": heartbeat is not None,
            "terminal_connected": heartbeat["terminal_connected"] if heartbeat else False,
            "fresh": heartbeat_fresh,
            "age_seconds": round(heartbeat_age, 2) if heartbeat_age is not None else None,
        },
        "account": {
            "received": account is not None,
            "fresh": account_age is not None and account_age <= stale_after,
            "age_seconds": round(account_age, 2) if account_age is not None else None,
        },
        "quotes": quote_status,
        "stale_after_seconds": stale_after,
        "execution_mode": "disabled",
        "trading_enabled": False,
    }
