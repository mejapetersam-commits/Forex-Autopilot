import os
import json
import hashlib
from datetime import datetime, timezone
from typing import Literal
from hmac import compare_digest
from math import isfinite

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from pathlib import Path

from app.broker.bridge import MT5AccountSnapshot, MT5CandleBatch, MT5CandleBulk, MT5Heartbeat, MT5ExecutionHistory, MT5ExecutionOrderHistory, MT5ExecutionState, MT5Quote, MT5SymbolSpecification
from app.market_data.telemetry_store import TelemetryStore
from app.market_data.indicators import calculate_indicators
from app.strategy.engine import StrategyConfig, evaluate_signal
from app.backtesting.engine import BacktestConfig, run_backtest
from app.backtesting.optimization import optimize_walk_forward
from app.backtesting.analytics import analyse_backtest
from app.strategy.registry import list_strategies
from app.market_data.quality import assess_candle_quality, assess_candle_readiness
from app.execution.ledger import ExecutionLedger
from app.execution.reconciliation import reconcile_broker_history
from app.execution.position_reconciliation import reconcile_open_positions
from app.execution.position_lifecycle import compare_position_lifecycle
from app.execution.coordinator import ExecutionCoordinator
from app.execution.preflight import ExecutionSnapshot, TradeIntent, evaluate_with_runtime_controls
from app.execution.portfolio_risk import evaluate_portfolio_risk
from app.execution.command_queue import ExecutionCommandQueue
from app.monitoring.health import assess_system_health
from app.operations.event_outbox import EventOutbox
from app.operations.backup import inspect_backup_inventory
from app.portfolio.telemetry import build_portfolio_exposure

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


class StrategyDispatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    volume_lots: float = Field(gt=0, le=0.01)
    queue_if_approved: StrictBool = False




def execution_ledger() -> ExecutionLedger:
    return ExecutionLedger()


def quarantine_expired_execution_commands() -> int:
    """Mark timed-out terminal leases unknown; never redeliver them automatically."""
    expired = execution_command_queue().expire_leases()
    ledger = execution_ledger()
    changed = 0
    for command in expired:
        intent = ledger.get_intent(command["intent_id"])
        if intent and intent["status"] == "approved":
            ledger.transition(
                command["intent_id"], "unknown",
                event_type="command_lease_expired",
                details={
                    "command_id": command["command_id"],
                    "terminal_id": command["terminal_id"],
                    "attempts": command["attempts"],
                    "recovery": "broker_history_required",
                },
            )
            changed += 1
    return changed


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
            readiness = assess_candle_readiness(
                candles, timeframe,
                minimum_candles=max(1, int(os.getenv("FOREX_AUTOPILOT_MIN_RESEARCH_CANDLES", "500"))),
            )
            rows.append({
                "symbol": symbol,
                "timeframe": timeframe,
                "candles": len(candles),
                "valid_candles": readiness["valid_candles"],
                "readiness_status": readiness["status"],
                "coverage_pct": readiness["coverage_pct"],
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



@app.get("/api/v1/dashboard/data-readiness", include_in_schema=False)
def dashboard_data_readiness(
    minimum_candles: int = Query(default=500, ge=1, le=5000),
    limit: int = Query(default=5000, ge=1, le=5000),
):
    """Read-only history coverage and candle integrity grid for dashboard symbols."""
    store = telemetry_store()
    items = []
    for symbol in sorted(dashboard_symbols()):
        for timeframe in ("M5", "M15", "H1", "H4"):
            candles = store.candle_history(symbol, timeframe, limit)
            readiness = assess_candle_readiness(
                candles, timeframe, minimum_candles=minimum_candles,
            )
            items.append({"symbol": symbol, "timeframe": timeframe, **readiness})
    ready_count = sum(item["ready_for_research"] for item in items)
    return {
        "status": "ready" if ready_count == len(items) else "attention_required",
        "items": items,
        "ready_series": ready_count,
        "series_checked": len(items),
        "minimum_candles": minimum_candles,
        "execution_mode": "disabled",
        "trading_enabled": False,
        "read_only": True,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/v1/dashboard/strategy-performance", include_in_schema=False)
def dashboard_strategy_performance(
    symbol: str = Query(default="EURUSDm", min_length=1, max_length=32),
    timeframe: str = Query(default="H1", pattern="^(M15|H1|H4)$"),
    include_walk_forward: bool = Query(default=False),
    limit: int = Query(default=1000, ge=61, le=5000),
):
    """Local read-only strategy research workspace; never authorizes execution."""
    normalized_symbol = symbol.strip().upper()
    if normalized_symbol not in dashboard_symbols():
        raise HTTPException(status_code=403, detail="Symbol is not in the dashboard research allowlist.")
    normalized_timeframe = timeframe.strip().upper()
    store = telemetry_store()
    candles = store.candle_history(normalized_symbol, normalized_timeframe, limit)
    quality = assess_candle_quality(candles, normalized_timeframe)
    pip_size, pip_value, pip_source = resolve_backtest_pip_values(
        store, normalized_symbol, None, None
    )
    config = BacktestConfig(
        initial_equity=10000.0,
        risk_per_trade_pct=0.25,
        pip_size=pip_size,
        pip_value_per_lot=pip_value,
        spread_pips=1.0,
        slippage_pips_per_side=0.2,
        commission_per_lot_per_side=3.5,
    )
    result = run_backtest(candles, config)
    analytics = analyse_backtest(result) if result.get("status") == "completed" else None
    walk_forward = None
    if include_walk_forward:
        walk_forward = optimize_walk_forward(candles, config) if len(candles) >= 400 else {
            "status": "insufficient_data", "candles_available": len(candles),
            "minimum_required": 400, "execution_enabled": False,
        }
    return {
        "symbol": normalized_symbol,
        "timeframe": normalized_timeframe,
        "candles_available": len(candles),
        "data_quality": quality,
        "pip_size_used": pip_size,
        "pip_value_per_lot_used": pip_value,
        "pip_value_source": pip_source,
        "backtest": result,
        "analytics": analytics,
        "walk_forward": walk_forward,
        "trading_enabled": False,
        "execution_mode": "disabled",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/v1/dashboard/strategy-qualification", include_in_schema=False)
def dashboard_strategy_qualification(
    symbol: str = Query(default="EURUSDm", min_length=1, max_length=32),
    timeframe: str = Query(default="H1", pattern="^(M15|H1|H4)$"),
    limit: int = Query(default=1000, ge=400, le=5000),
):
    """On-demand walk-forward qualification for a single market/timeframe pair."""
    from app.backtesting.qualification import evaluate_strategy_qualification

    normalized_symbol = symbol.strip().upper()
    if normalized_symbol not in dashboard_symbols():
        raise HTTPException(status_code=403, detail="Symbol is not in the dashboard research allowlist.")
    normalized_timeframe = timeframe.strip().upper()
    store = telemetry_store()
    candles = store.candle_history(normalized_symbol, normalized_timeframe, limit)
    quality = assess_candle_quality(candles, normalized_timeframe)
    readiness = assess_candle_readiness(
        candles, normalized_timeframe,
        minimum_candles=max(1, int(os.getenv("FOREX_AUTOPILOT_MIN_RESEARCH_CANDLES", "500"))),
    )
    quality["ready_for_research"] = readiness["ready_for_research"]
    if len(candles) < 400:
        walk_forward = {
            "status": "insufficient_data", "candles_available": len(candles),
            "minimum_required": 400, "folds": [],
            "out_of_sample_summary": {"valid_folds": 0, "total_trades": 0},
        }
    else:
        pip_size, pip_value, _ = resolve_backtest_pip_values(store, normalized_symbol, None, None)
        config = BacktestConfig(
            initial_equity=10000.0, risk_per_trade_pct=0.25,
            pip_size=pip_size, pip_value_per_lot=pip_value,
            spread_pips=1.0, slippage_pips_per_side=0.2,
            commission_per_lot_per_side=3.5,
        )
        walk_forward = optimize_walk_forward(candles, config)
    qualification = evaluate_strategy_qualification(walk_forward, quality)
    return {
        "symbol": normalized_symbol,
        "timeframe": normalized_timeframe,
        "candles_available": len(candles),
        "data_quality": quality,
        "data_readiness": readiness,
        "walk_forward": walk_forward,
        "qualification": qualification,
        "execution_mode": "disabled",
        "trading_enabled": False,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/v1/dashboard/demo-observation", include_in_schema=False)
def dashboard_demo_observation(limit: int = Query(default=100, ge=1, le=500)):
    """Read-only broker-confirmed demo activity; never infers missing trade PnL."""
    summary = telemetry_store().demo_observation_summary(limit)
    latest = summary.get("latest_terminal")
    return {
        **summary,
        "status": "observing" if summary["deal_totals"]["deal_count"] else "awaiting_demo_activity",
        "execution_mode": "disabled",
        "trading_enabled": False,
        "read_only": True,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/v1/dashboard/trade-attribution", include_in_schema=False)
def dashboard_trade_attribution():
    """Read-only realized P&L from fully closed broker-evidenced demo position cycles."""
    result = telemetry_store().demo_trade_attribution()
    return {
        **result,
        "status": "observing" if result["deal_count"] else "awaiting_demo_activity",
        "execution_mode": "disabled",
        "trading_enabled": False,
        "read_only": True,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/v1/dashboard/strategy-comparison", include_in_schema=False)
def dashboard_strategy_comparison(
    limit: int = Query(default=1000, ge=61, le=5000),
):
    """Compare fixed research configurations across the dashboard symbol/timeframe grid."""
    store = telemetry_store()
    rows = []
    for symbol in sorted(dashboard_symbols()):
        for timeframe in ("M15", "H1", "H4"):
            candles = store.candle_history(symbol, timeframe, limit)
            quality = assess_candle_quality(candles, timeframe)
            row = {
                "symbol": symbol, "timeframe": timeframe,
                "candles_available": len(candles),
                "data_quality": quality.get("status", "unknown"),
                "gap_count": quality.get("gap_count", 0),
                "status": "insufficient_data",
                "execution_enabled": False,
            }
            if len(candles) < 61:
                rows.append(row)
                continue
            try:
                pip_size, pip_value, pip_source = resolve_backtest_pip_values(
                    store, symbol, None, None
                )
                config = BacktestConfig(
                    initial_equity=10000.0, risk_per_trade_pct=0.25,
                    pip_size=pip_size, pip_value_per_lot=pip_value,
                    spread_pips=1.0, slippage_pips_per_side=0.2,
                    commission_per_lot_per_side=3.5,
                )
                result = run_backtest(candles, config)
                row.update({
                    "status": result.get("status", "unknown"),
                    "return_pct": result.get("return_pct"),
                    "total_trades": result.get("total_trades"),
                    "win_rate_pct": result.get("win_rate_pct"),
                    "profit_factor": result.get("profit_factor"),
                    "max_drawdown_pct": result.get("mark_to_market_max_drawdown_pct",
                                                   result.get("max_drawdown_pct")),
                    "expectancy_per_trade": result.get("expectancy_per_trade"),
                    "pip_value_source": pip_source,
                })
            except HTTPException as exc:
                row.update({"status": "unavailable", "reason": str(exc.detail)})
            rows.append(row)
    ranked = sorted(
        (row for row in rows if row.get("status") == "completed"),
        key=lambda row: (
            row.get("profit_factor") is not None,
            row.get("profit_factor") or 0,
            row.get("return_pct") or 0,
        ),
        reverse=True,
    )
    for index, row in enumerate(ranked, 1):
        row["research_rank"] = index
    return {
        "items": rows,
        "ranked_count": len(ranked),
        "ranking_method": "profit factor then return; descriptive historical comparison only",
        "warning": "Rankings are not out-of-sample validation and can be distorted by small samples, data quality and OHLC execution assumptions.",
        "trading_enabled": False,
        "execution_mode": "disabled",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/v1/dashboard/portfolio", include_in_schema=False)
def dashboard_portfolio():
    """Read-only exposure and stop-risk estimate from fresh demo telemetry."""
    store = telemetry_store()
    return build_portfolio_exposure(
        execution_state=store.latest_execution_state(),
        account=store.latest_account(),
        quotes=store.latest_quotes(),
        specifications=store.latest_symbol_specifications(),
    )


@app.get("/api/v1/dashboard/execution-reconciliation", include_in_schema=False)
def dashboard_execution_reconciliation(
    limit: int = Query(default=50, ge=1, le=100),
):
    """Expose sanitized, read-only broker fill evidence for the local dashboard.

    Terminal rejections/cancellations are outcomes, not missing-history alerts.
    """
    ledger = execution_ledger()
    store = telemetry_store()
    intents = ledger.list_intents(limit=limit)
    evidence_events = {
        "broker_history_partial_fill",
        "broker_history_full_fill_confirmed",
        "broker_history_reconciled",
        "broker_order_history_reconciled",
    }
    rows = []
    visible_statuses = {"submitted", "acknowledged", "partially_filled", "filled", "unknown", "reconciled", "cancelled", "rejected"}
    for intent in intents:
        if intent["status"] not in visible_statuses:
            continue
        audit = ledger.audit_events(intent["idempotency_key"], limit=100)
        broker_events = [event for event in audit if event["event_type"] in evidence_events]
        latest = broker_events[-1] if broker_events else None
        details = latest["details"] if latest else {}
        payload = intent.get("payload", {})
        requested_volume = payload.get("volume_lots")
        filled_volume = details.get("filled_volume_lots")
        try:
            requested_number = float(requested_volume)
            filled_number = float(filled_volume)
            fill_values_valid = (
                isfinite(requested_number) and requested_number > 0
                and isfinite(filled_number) and filled_number >= 0
            )
        except (TypeError, ValueError):
            fill_values_valid = False
            requested_number = filled_number = 0.0
        remaining_volume = (
            max(0.0, requested_number - filled_number)
            if fill_values_valid else None
        )
        fill_progress = (
            min(100.0, filled_number / requested_number * 100.0)
            if fill_values_valid else None
        )
        rows.append({
            "intent_id": intent["idempotency_key"],
            "status": intent["status"],
            "symbol": str(payload.get("symbol") or ""),
            "side": str(payload.get("side") or ""),
            "requested_volume_lots": payload.get("volume_lots"),
            "broker_order_id": intent.get("broker_order_id") or details.get("broker_order_id"),
            "result": (
                "partial_fill_confirmed" if latest and latest["event_type"] == "broker_history_partial_fill"
                else "full_fill_reconciled" if latest and latest["event_type"] in {
                    "broker_history_full_fill_confirmed", "broker_history_reconciled",
                    "broker_order_history_reconciled",
                }
                else "terminal_outcome_recorded" if intent["status"] in {"cancelled", "rejected"}
                else "reconciled" if intent["status"] == "reconciled"
                else "awaiting_broker_history"
            ),
            "filled_volume_lots": details.get("filled_volume_lots", 0.0),
            "remaining_volume_lots": remaining_volume,
            "fill_progress_pct": fill_progress,
            "average_fill_price": details.get("average_fill_price"),
            "fill_details": (details.get("fill_details") or [])[:20],
            "deal_tickets": (details.get("deal_tickets") or [])[:20],
            "position_ids": (details.get("position_ids") or [])[:20],
            "last_broker_evidence_at": latest["occurred_at"] if latest else None,
        })

    review_events = []
    for event in EventOutbox().list_events(limit=200):
        if event["event_type"] != "execution_reconciliation_review":
            continue
        try:
            payload = json.loads(event.get("payload_json") or "{}")
        except (TypeError, ValueError):
            payload = {}
        review_events.append({
            "event_id": event["event_id"],
            "occurred_at": event["occurred_at"],
            "severity": event["severity"],
            "intent_id": payload.get("intent_id"),
            "outcome": payload.get("outcome"),
            "reasons": payload.get("reasons") or [],
            "broker_order_id": payload.get("broker_order_id"),
            "filled_volume_lots": payload.get("filled_volume_lots"),
            "requested_volume_lots": payload.get("requested_volume_lots"),
        })
        if len(review_events) >= 20:
            break

    broker_orders = store.recent_execution_orders(limit=min(limit, 50))
    pending_order_states = {"started", "placed", "partial", "request_add", "request_modify", "request_cancel"}
    order_counts = {
        "total": len(broker_orders),
        "pending": sum(order["state"] in pending_order_states for order in broker_orders),
        "terminal": sum(order["state"] in {"filled", "canceled", "rejected", "expired"} for order in broker_orders),
    }
    counts = {
        "partial_fill_count": sum(row["result"] == "partial_fill_confirmed" for row in rows),
        "reconciled_count": sum(row["status"] == "reconciled" for row in rows),
        "awaiting_history_count": sum(
            row["result"] == "awaiting_broker_history"
            and row["status"] in {"submitted", "acknowledged", "partially_filled", "filled", "unknown"}
            for row in rows
        ),
        "unknown_count": sum(row["status"] == "unknown" for row in rows),
        "manual_review_count": len(review_events),
    }
    return {
        "status": "review_required" if review_events else (
            "observing" if rows or broker_orders else "awaiting_demo_activity"
        ),
        "intents_checked": len(rows),
        "counts": counts,
        "order_counts": order_counts,
        "broker_orders": broker_orders,
        "intents": rows,
        "manual_review_events": review_events,
        "execution_mode": "disabled",
        "trading_enabled": False,
        "read_only": True,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/v1/dashboard/release-readiness", include_in_schema=False)
def dashboard_release_readiness():
    """Consolidated read-only automated and operator release gates.

    Manual broker/terminal validations are deliberately never inferred from
    source-code tests or dashboard telemetry.
    """
    overview = dashboard_overview()
    data = dashboard_data_readiness(minimum_candles=500, limit=500)
    operations = dashboard_operations()
    recovery = dashboard_recovery_status()
    execution = dashboard_execution_reconciliation(limit=50)
    observation = dashboard_demo_observation(limit=500)

    def gate(key: str, label: str, state: str, detail: str) -> dict:
        return {"key": key, "label": label, "status": state, "detail": detail}

    account_fresh = bool(overview.get("account") and overview["account"].get("fresh"))
    terminal_fresh = bool(overview.get("bridge_connected") and overview.get("heartbeat", {}).get("fresh"))
    automated = [
        gate(
            "broker_telemetry", "Fresh demo broker telemetry",
            "passed" if terminal_fresh and account_fresh else "attention_required",
            "Terminal heartbeat and account snapshot are fresh."
            if terminal_fresh and account_fresh
            else "A fresh connected terminal heartbeat and account snapshot are required.",
        ),
        gate(
            "market_history", "Market history quality and coverage",
            "passed" if data["status"] == "ready" else "attention_required",
            f'{data["ready_series"]} of {data["series_checked"]} symbol/timeframe series meet the {data["minimum_candles"]}-candle research gate.',
        ),
        gate(
            "verified_backup", "Verified recovery point and worker",
            "passed" if recovery["backups"].get("fresh_verified_backup")
            and recovery["backup_worker"].get("fresh")
            and recovery["backups"].get("invalid_count", 0) == 0 else "attention_required",
            "A fresh verified backup exists and the backup worker heartbeat is healthy."
            if recovery["backups"].get("fresh_verified_backup")
            and recovery["backup_worker"].get("fresh")
            and recovery["backups"].get("invalid_count", 0) == 0
            else "A fresh verified backup, healthy worker heartbeat and zero invalid snapshots are required.",
        ),
    ]

    recon_counts = execution["counts"]
    observed_execution = bool(execution["intents_checked"] or execution["order_counts"]["total"])
    if not observed_execution:
        recon_state = "awaiting_activity"
        recon_detail = "No broker order/intent activity has yet exercised reconciliation."
    elif any(recon_counts.get(k, 0) for k in (
        "partial_fill_count", "awaiting_history_count", "unknown_count", "manual_review_count"
    )):
        recon_state = "attention_required"
        recon_detail = "Partial, unknown, missing-history or manual-review outcomes remain unresolved."
    else:
        recon_state = "passed"
        recon_detail = "Observed broker order and intent records have no unresolved reconciliation exceptions."
    automated.append(gate("broker_reconciliation", "Broker order and deal reconciliation", recon_state, recon_detail))

    has_terminal_snapshot = operations["reconciliation"].get("status") not in {
        "waiting_for_terminal_snapshot", "terminal_snapshot_stale_or_not_demo"
    }
    protection_issues = operations["reconciliation"].get("protection_issues", [])
    orphaned = operations["reconciliation"].get("orphaned_positions", [])
    mismatched = operations["reconciliation"].get("mismatched_positions", [])
    if not has_terminal_snapshot:
        position_state = "awaiting_telemetry"
        position_detail = "A fresh demo position snapshot is required before position protection can be audited."
    elif protection_issues or orphaned or mismatched:
        position_state = "attention_required"
        position_detail = "Broker positions include missing protection, orphaned identity or mismatched records."
    else:
        position_state = "passed"
        position_detail = "Latest fresh demo snapshot has no reported orphan, mismatch or missing-protection issue."
    automated.append(gate("position_integrity", "Position identity and protection audit", position_state, position_detail))

    deal_count = observation["deal_totals"]["deal_count"]
    order_count = execution["order_counts"]["total"]
    automated.append(gate(
        "demo_broker_history", "Broker-side demo history observed",
        "passed" if deal_count > 0 and order_count > 0 else "awaiting_activity",
        f"{deal_count} managed deals and {order_count} broker orders are currently visible."
        if deal_count > 0 and order_count > 0
        else "A controlled demo execution must produce broker order and deal history before this gate can pass.",
    ))

    manual = [
        gate("metaeditor_compile", "Compile both MT5 Expert Advisors in MetaEditor", "operator_validation_required",
             "Requires a clean compile on the target MT5 terminal; CI source checks are not a substitute."),
        gate("demo_execution_scenarios", "Exercise demo order and protective-stop scenarios", "operator_validation_required",
             "Verify accepted orders, partial fills, rejects, cancels, broker SL/TP and statement matching on a dedicated demo account."),
        gate("terminal_restart_recovery", "Test terminal disconnect and restart recovery", "operator_validation_required",
             "Verify uncertain outcomes remain quarantined and are recovered only from broker-side evidence."),
        gate("forward_demo_trial", "Complete sustained forward-demo observation", "operator_validation_required",
             "Requires a documented multi-week demo run and reconciliation against broker statements."),
    ]
    passed_automated = sum(item["status"] == "passed" for item in automated)
    return {
        "status": "not_ready",
        "automated_gates": automated,
        "manual_gates": manual,
        "automated_passed": passed_automated,
        "automated_total": len(automated),
        "manual_validation_required": len(manual),
        "execution_enabled": False,
        "trading_enabled": False,
        "live_trading_supported": False,
        "read_only": True,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/v1/dashboard/operations", include_in_schema=False)
def dashboard_operations():
    """Safe read-only operations summary for the local dashboard; no admin secrets or mutations."""
    store = telemetry_store()
    snapshots = store.recent_execution_states(limit=2)
    now = datetime.now(timezone.utc)
    expected_magic = int(os.getenv("FOREX_AUTOPILOT_EXECUTION_MAGIC", "61119001"))
    reconciliation = {
        "status": "waiting_for_terminal_snapshot",
        "managed_positions_checked": 0,
        "orphaned_positions": [],
    }
    lifecycle = {
        "status": "waiting_for_terminal_snapshot",
        "previous_snapshot_available": False,
        "managed_positions_current": 0,
        "events": [],
    }
    if snapshots:
        current = snapshots[0]
        observed = datetime.fromisoformat(current["observed_at"].replace("Z", "+00:00"))
        age = (now - observed).total_seconds()
        if current["environment"] == "demo" and -5 <= age <= 30:
            reconciliation = reconcile_open_positions(
                current["positions"], execution_ledger().list_intents(),
                expected_magic=expected_magic,
            )
            previous = snapshots[1] if len(snapshots) > 1 else None
            deals_by_position = {}
            if previous and previous.get("terminal_id") == current.get("terminal_id"):
                for position in previous["positions"]:
                    if int(position.get("magic", -1)) != expected_magic:
                        continue
                    position_id = str(position.get("position_id") or "")
                    if position_id:
                        deals_by_position[position_id] = store.execution_deals_for_position(position_id)
            lifecycle = compare_position_lifecycle(
                previous, current, deals_by_position=deals_by_position,
                expected_magic=expected_magic,
            )
        else:
            reconciliation["status"] = "terminal_snapshot_stale_or_not_demo"
            lifecycle["status"] = "terminal_snapshot_stale_or_not_demo"

    portfolio = build_portfolio_exposure(
        execution_state=store.latest_execution_state(),
        account=store.latest_account(),
        quotes=store.latest_quotes(),
        specifications=store.latest_symbol_specifications(),
    )
    limit = float(os.getenv("FOREX_AUTOPILOT_MAX_PORTFOLIO_STOP_RISK_PCT", "0.50"))
    portfolio_gate = evaluate_portfolio_risk(portfolio, max_stop_risk_pct=limit)
    position_event_types = {
        "orphan_broker_position", "position_opened_observed",
        "position_ticket_replaced", "position_partially_closed_observed",
        "position_protection_changed", "position_closed_confirmed",
        "position_disappearance_unconfirmed",
    }
    recent_position_events = [
        item for item in EventOutbox().list_events(limit=100)
        if item["event_type"] in position_event_types
    ][:20]
    return {
        "reconciliation": reconciliation,
        "lifecycle": lifecycle,
        "portfolio_risk_gate": portfolio_gate,
        "recent_position_events": recent_position_events,
        "execution_mode": "disabled",
        "trading_enabled": False,
        "read_only": True,
        "updated_at": now.isoformat(),
    }


@app.get("/api/v1/dashboard/events", include_in_schema=False)
def dashboard_operational_events(
    limit: int = Query(default=50, ge=1, le=200),
    severity: Literal["info", "warning", "critical"] | None = None,
):
    """Expose recent operational events to the local read-only dashboard."""
    events = EventOutbox().list_events(limit=limit, severity=severity)
    return {
        "items": events,
        "execution_mode": "disabled",
        "trading_enabled": False,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/v1/dashboard/recovery-status", include_in_schema=False)
def dashboard_recovery_status():
    """Read-only backup freshness and execution-command quarantine overview."""
    backup_dir = os.getenv(
        "FOREX_AUTOPILOT_BACKUP_DIR", "data/backups"
    )
    max_age_hours = max(1, min(
        87600, int(os.getenv("FOREX_AUTOPILOT_BACKUP_MAX_AGE_HOURS", "48"))
    ))
    try:
        backups = inspect_backup_inventory(
            backup_dir, max_age_hours=max_age_hours
        )
    except (OSError, ValueError) as exc:
        backups = {
            "status": "inspection_failed",
            "directory_exists": False,
            "snapshot_count": 0,
            "verified_count": 0,
            "invalid_count": 0,
            "fresh_verified_backup": False,
            "error": str(exc)[:300],
            "snapshots": [],
        }
    commands = execution_command_queue().operational_summary(limit=20)
    heartbeat_path = Path(os.getenv(
        "FOREX_AUTOPILOT_TELEMETRY_DB", "data/telemetry.sqlite3"
    )).expanduser().parent / "backup-worker-heartbeat.json"
    worker_interval = max(3600, int(os.getenv(
        "FOREX_AUTOPILOT_BACKUP_INTERVAL_SECONDS", "86400"
    )))
    worker_max_age = max(7200, worker_interval * 2 + 300)
    worker = {"status": "missing", "fresh": False, "age_seconds": None}
    try:
        heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
        observed = datetime.fromisoformat(
            str(heartbeat["observed_at"]).replace("Z", "+00:00")
        )
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError("Worker heartbeat timestamp must be timezone-aware.")
        age = (datetime.now(timezone.utc) - observed.astimezone(timezone.utc)).total_seconds()
        fresh = -300 <= age <= worker_max_age and heartbeat.get("status") == "ok"
        worker = {
            "status": "healthy" if fresh else "stale",
            "fresh": fresh,
            "age_seconds": round(max(0.0, age), 1),
            "max_age_seconds": worker_max_age,
            "last_backup": heartbeat.get("backup"),
            "observed_at": observed.isoformat(),
        }
    except FileNotFoundError:
        pass
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        worker["status"] = "invalid"
    return {
        "backups": backups,
        "backup_worker": worker,
        "execution_commands": commands,
        "execution_mode": "disabled",
        "trading_enabled": False,
        "read_only": True,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


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
    spec_ok = bool(
        specification and specification["trade_allowed"] and 0 <= spec_age <= 300
        and account and specification["account_currency"] == account["account_currency"]
    )
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
        saved_payload = intent["payload"]
        current_intent = TradeIntent(
            symbol=saved_payload["symbol"], side=saved_payload["side"],
            volume_lots=float(saved_payload["volume_lots"]),
            stop_loss=float(saved_payload["stop_loss"]),
            take_profit=float(saved_payload["take_profit"]),
            requested_at=datetime.fromisoformat(saved_payload["requested_at"]),
        )
        current_snapshot = execution_snapshot_for_symbol(current_intent.symbol)
        current_decision = evaluate_with_runtime_controls(
            current_intent, current_snapshot, execution_ledger()
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="Stored intent cannot be safely revalidated.") from exc
    # Rebuild aggregate risk from current broker telemetry immediately before dispatch.
    store = telemetry_store()
    portfolio = build_portfolio_exposure(
        execution_state=store.latest_execution_state(),
        account=store.latest_account(),
        quotes=store.latest_quotes(),
        specifications=store.latest_symbol_specifications(),
    )
    max_portfolio_risk_pct = float(os.getenv("FOREX_AUTOPILOT_MAX_PORTFOLIO_STOP_RISK_PCT", "0.50"))
    portfolio_decision = evaluate_portfolio_risk(
        portfolio, max_stop_risk_pct=max_portfolio_risk_pct
    )
    if not current_decision["approved"] or not portfolio_decision["approved"]:
        reasons = [*current_decision["reasons"], *portfolio_decision["reasons"]]
        execution_ledger().transition(
            intent_id, "rejected", event_type="dispatch_recheck_failed",
            details={"reasons": reasons, "portfolio": portfolio_decision},
        )
        raise HTTPException(status_code=423, detail={
            "message": "Current broker, individual-risk or aggregate portfolio conditions no longer pass preflight.",
            "reasons": reasons, "portfolio": portfolio_decision,
        })
    try:
        queued = execution_command_queue().enqueue_approved_intent(
            command_id="cmd-" + hashlib.sha256(intent_id.encode("utf-8")).hexdigest()[:32], intent_id=intent_id,
            payload={**intent["payload"], "broker_tag": hashlib.sha256(intent_id.encode("utf-8")).hexdigest()[:12]},
            environment="demo", trading_enabled=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"command_id": queued["command_id"], "status": queued["status"],
            "environment": "demo", "trading_enabled": False}


@app.get("/api/v1/mt5/execution/commands/next", dependencies=[Depends(require_bridge_token)])
def lease_next_execution_command(terminal_id: str = Query(min_length=1, max_length=128)):
    quarantine_expired_execution_commands()
    if os.getenv("FOREX_AUTOPILOT_ENVIRONMENT", "demo").strip().lower() != "demo":
        return {"command": None, "reason": "demo_environment_required"}
    if os.getenv("FOREX_AUTOPILOT_DEMO_EXECUTION_ENABLED", "false").strip().lower() != "true":
        return {"command": None, "reason": "demo_execution_disabled"}
    terminal = telemetry_store().latest_execution_state()
    if terminal is None:
        return {"command": None, "reason": "terminal_snapshot_missing"}
    observed = datetime.fromisoformat(terminal["observed_at"].replace("Z", "+00:00"))
    terminal_age = (datetime.now(timezone.utc) - observed).total_seconds()
    if terminal["environment"] != "demo" or terminal["terminal_id"] != terminal_id:
        return {"command": None, "reason": "terminal_identity_mismatch"}
    if terminal_age < -5 or terminal_age > 30:
        return {"command": None, "reason": "terminal_snapshot_stale"}
    controls = execution_ledger().controls()
    if controls["trading_paused"] or controls["kill_switch_active"]:
        return {"command": None, "reason": "execution_safeguards_active"}
    command = execution_command_queue().lease_next(terminal_id=terminal_id)
    return {"command": command, "environment": "demo"} if command else {"command": None}


@app.post("/api/v1/mt5/execution/commands/{command_id}/result", dependencies=[Depends(require_bridge_token)])
def record_execution_command_result(command_id: str, payload: MT5ExecutionResult):
    if payload.outcome not in {"acknowledged", "rejected", "unknown"}:
        raise HTTPException(status_code=422, detail="Unsupported terminal outcome.")
    reported_intent = payload.result.get("intent_id")
    if not isinstance(reported_intent, str) or not reported_intent.strip():
        raise HTTPException(status_code=422, detail="Terminal result must identify its order intent.")
    try:
        result = execution_command_queue().record_result(
            command_id, terminal_id=payload.terminal_id,
            outcome=payload.outcome, result=payload.result,
            expected_intent_id=reported_intent,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Execution command not found.")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    ledger = execution_ledger()
    intent = ledger.get_intent(result["intent_id"])
    if intent is None:
        raise HTTPException(status_code=409, detail="Command has no matching order intent.")
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


@app.post(
    "/api/v1/admin/strategy/dispatch/{symbol}/{timeframe}",
    dependencies=[Depends(require_admin_token)],
)
def dispatch_strategy_candidate(
    symbol: str, timeframe: str, payload: StrategyDispatchRequest,
):
    """Convert a validated research candidate into a risk-preflighted intent.

    Queueing remains a separate explicit opt-in and re-runs all live safety gates.
    """
    normalized_symbol, normalized_timeframe = symbol.strip().upper(), timeframe.strip().upper()
    candles = telemetry_store().candle_history(normalized_symbol, normalized_timeframe, 500)
    signal = evaluate_signal(candles, StrategyConfig())
    if signal.get("signal") not in {"buy", "sell"} or not signal.get("candidate_levels"):
        return {
            "created": False, "reason": signal.get("reason", signal.get("signal")),
            "signal": signal.get("signal"), "execution_queued": False,
            "trading_enabled": False,
        }
    levels = signal["candidate_levels"]
    if not levels.get("stop_loss") or not levels.get("take_profit"):
        raise HTTPException(status_code=409, detail="Strategy candidate has no valid protective levels.")
    latest_bar = candles[-1]
    identity = "|".join((
        normalized_symbol, normalized_timeframe, str(latest_bar["opened_at"]),
        signal["signal"], signal["strategy"]["version"],
    ))
    intent_id = "signal-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:40]
    intent = TradeIntent(
        symbol=normalized_symbol, side=signal["signal"],
        volume_lots=payload.volume_lots,
        stop_loss=float(levels["stop_loss"]),
        take_profit=float(levels["take_profit"]),
        requested_at=datetime.fromisoformat(
            str(latest_bar["opened_at"]).replace("Z", "+00:00")
        ),
    )
    result = ExecutionCoordinator(execution_ledger()).preflight_and_record(
        intent_id, intent, execution_snapshot_for_symbol(normalized_symbol)
    )
    queued = None
    if payload.queue_if_approved and result["status"] == "approved":
        queued = queue_approved_demo_intent(intent_id)
    return {
        "created": result["status"] in {"approved", "preflight_rejected"},
        "intent_id": intent_id, "status": result["status"],
        "signal": signal["signal"], "candidate_levels": levels,
        "preflight": result["preflight"],
        "execution_queued": bool(queued and queued.get("status") == "queued"),
        "queue": queued, "research_status": signal.get("research_status"),
        "trading_enabled": False,
    }


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


@app.get("/api/v1/strategies", dependencies=[Depends(require_bridge_token)])
def registered_strategies():
    """List available research strategies; registry entries cannot execute trades."""
    return {
        "strategies": list_strategies(),
        "execution_enabled": False,
        "trading_enabled": False,
    }


@app.get(
    "/api/v1/backtests/analytics/{symbol}/{timeframe}",
    dependencies=[Depends(require_bridge_token)],
)
def backtest_analytics(
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
    """Return supplemental distribution analytics for a fresh historical simulation."""
    result = run_historical_backtest(
        symbol=symbol,
        timeframe=timeframe,
        pip_value_per_lot=pip_value_per_lot,
        limit=limit,
        initial_equity=initial_equity,
        risk_per_trade_pct=risk_per_trade_pct,
        pip_size=pip_size,
        spread_pips=spread_pips,
        slippage_pips_per_side=slippage_pips_per_side,
        commission_per_lot_per_side=commission_per_lot_per_side,
    )
    return {
        "symbol": result["symbol"],
        "timeframe": result["timeframe"],
        "analytics": analyse_backtest(result),
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



def protective_stop_guard(payload: MT5ExecutionState, store: TelemetryStore) -> dict:
    """Detect absent/invalid broker stops; fail closed rather than modifying positions."""
    expected_magic = int(os.getenv("FOREX_AUTOPILOT_EXECUTION_MAGIC", "61119001"))
    quotes = {item["symbol"].upper(): item for item in store.latest_quotes()}
    alerts, unprotected = [], []
    for position in payload.positions:
        if position.magic != expected_magic:
            continue
        reasons = []
        if position.stop_loss <= 0:
            reasons.append("missing_stop_loss")
        else:
            quote = quotes.get(position.symbol.upper())
            specification = store.latest_symbol_specification(position.symbol)
            if quote and specification:
                observed = datetime.fromisoformat(quote["observed_at"].replace("Z", "+00:00"))
                age = (datetime.now(timezone.utc) - observed).total_seconds()
                if -5 <= age <= 10:
                    minimum = max(
                        float(specification["stops_level_points"]) * float(specification["point"]),
                        float(specification["freeze_level_points"]) * float(specification["point"]),
                    )
                    if position.side == "buy" and position.stop_loss >= float(quote["bid"]) - minimum:
                        reasons.append("buy_stop_wrong_side_or_inside_broker_distance")
                    elif position.side == "sell" and position.stop_loss <= float(quote["ask"]) + minimum:
                        reasons.append("sell_stop_wrong_side_or_inside_broker_distance")
        if reasons:
            item = {"ticket": position.ticket, "position_id": position.position_id,
                    "symbol": position.symbol, "side": position.side, "reasons": reasons}
            alerts.append(item)
            unprotected.append(item)
    return {
        "status": "critical" if unprotected else "healthy",
        "unprotected_positions": unprotected,
        "alerts": alerts,
        "automatic_action": "pause_and_kill_switch" if unprotected else "none",
        "broker_position_modified": False,
    }


@app.post(
    "/api/v1/mt5/execution/state",
    dependencies=[Depends(require_bridge_token)],
)
def mt5_execution_state(payload: MT5ExecutionState):
    """Persist a read-only open-position snapshot; this endpoint never places orders."""
    store = telemetry_store()
    store.save_execution_state(payload)
    guard = protective_stop_guard(payload, store)
    if guard["unprotected_positions"] and payload.environment == "demo":
        ledger = execution_ledger()
        controls = ledger.controls()
        if not controls["trading_paused"]:
            ledger.set_control("trading_paused", True)
        if not controls["kill_switch_active"]:
            ledger.set_control("kill_switch_active", True)
    return {
        "accepted": True, "stored": True,
        "terminal_id": payload.terminal_id, "environment": payload.environment,
        "positions_received": len(payload.positions),
        "protective_guard": guard,
        "new_entries_paused": bool(guard["unprotected_positions"] and payload.environment == "demo"),
        "trading_enabled": False,
    }


@app.post(
    "/api/v1/mt5/execution/history",
    dependencies=[Depends(require_bridge_token)],
)
def mt5_execution_history(payload: MT5ExecutionHistory):
    """Ingest broker deal history from the authenticated demo terminal."""
    count = telemetry_store().save_execution_history(payload)
    return {
        "accepted": True, "stored": True, "deals_received": count,
        "terminal_id": payload.terminal_id, "environment": payload.environment,
        "trading_enabled": False,
    }


@app.post(
    "/api/v1/mt5/execution/orders",
    dependencies=[Depends(require_bridge_token)],
)
def mt5_execution_order_history(payload: MT5ExecutionOrderHistory):
    """Ingest read-only broker order-state history from the demo terminal."""
    count = telemetry_store().save_execution_order_history(payload)
    return {
        "accepted": True, "stored": True, "orders_received": count,
        "terminal_id": payload.terminal_id, "environment": payload.environment,
        "trading_enabled": False,
    }


@app.get(
    "/api/v1/monitoring/reconciliation",
    dependencies=[Depends(require_admin_token)],
)
def execution_reconciliation():
    """Compare known execution intents with persisted broker deal evidence."""
    quarantine_expired_execution_commands()
    store = telemetry_store()
    terminal = store.latest_execution_state()
    if terminal is None:
        return {
            "status": "waiting_for_terminal_snapshot",
            "intents_checked": 0,
            "results": [],
            "trading_enabled": False,
        }
    observed = datetime.fromisoformat(terminal["observed_at"].replace("Z", "+00:00"))
    age = (datetime.now(timezone.utc) - observed).total_seconds()
    if terminal["environment"] != "demo" or age < -5 or age > 30:
        return {
            "status": "terminal_snapshot_stale_or_not_demo",
            "intents_checked": 0,
            "results": [],
            "trading_enabled": False,
        }
    result = reconcile_broker_history(
        execution_ledger(), store,
        expected_magic=int(os.getenv("FOREX_AUTOPILOT_EXECUTION_MAGIC", "61119001")),
        expected_terminal_id=terminal["terminal_id"],
        expected_server=terminal["server"],
    )
    result["operational_events_recorded"] = record_reconciliation_events(result)
    return result


def record_reconciliation_events(result: dict) -> int:
    """Publish durable, idempotent operator events for reconciliation exceptions."""
    outbox = EventOutbox()
    recorded = 0
    for item in result.get("results", []):
        outcome = item.get("result")
        if outcome not in {"manual_review_required", "reconciled_partial_fill"}:
            continue
        intent_id = str(item.get("intent_id", "unknown"))
        reasons = sorted(set(item.get("reasons", [])))
        fingerprint = hashlib.sha256(
            (outcome + "|" + "|".join(reasons)).encode("utf-8")
        ).hexdigest()[:16]
        severity = "critical" if outcome == "manual_review_required" else "warning"
        message = (
            "Broker execution evidence requires manual review."
            if severity == "critical"
            else "Broker reported a partial fill; remaining volume requires reconciliation."
        )
        event = outbox.record(
            event_key=f"exec-recon:{hashlib.sha256(intent_id.encode('utf-8')).hexdigest()[:32]}:{fingerprint}",
            event_type="execution_reconciliation_review",
            severity=severity,
            message=message,
            payload={
                "intent_id": intent_id,
                "outcome": outcome,
                "reasons": reasons,
                "broker_order_id": item.get("broker_order_id"),
                "filled_volume_lots": item.get("filled_volume_lots"),
                "requested_volume_lots": item.get("requested_volume_lots"),
                "source": "broker_history_reconciliation",
            },
        )
        if event:
            recorded += 1
    return recorded


@app.get(
    "/api/v1/monitoring/positions/reconciliation",
    dependencies=[Depends(require_admin_token)],
)
def open_position_reconciliation():
    """Flag managed broker positions that cannot be tied to a known intent."""
    store = telemetry_store()
    terminal = store.latest_execution_state()
    if terminal is None:
        return {"status": "waiting_for_terminal_snapshot",
                "managed_positions_checked": 0, "orphaned_positions": [],
                "trading_enabled": False}
    observed = datetime.fromisoformat(terminal["observed_at"].replace("Z", "+00:00"))
    age = (datetime.now(timezone.utc) - observed).total_seconds()
    if terminal["environment"] != "demo" or age < -5 or age > 30:
        return {"status": "terminal_snapshot_stale_or_not_demo",
                "managed_positions_checked": 0, "orphaned_positions": [],
                "trading_enabled": False}
    expected_magic = int(os.getenv("FOREX_AUTOPILOT_EXECUTION_MAGIC", "61119001"))
    result = reconcile_open_positions(
        terminal["positions"], execution_ledger().list_intents(),
        expected_magic=expected_magic,
    )
    outbox = EventOutbox()
    recorded = 0
    for position in result["orphaned_positions"]:
        ticket = position["ticket"]
        event = outbox.record(
            event_key=f"orphan-position:{hashlib.sha256(ticket.encode('utf-8')).hexdigest()[:32]}",
            event_type="orphan_broker_position",
            severity="critical",
            message="A managed MT5 position has no matching execution intent.",
            payload={
                "ticket": ticket, "position_id": position["position_id"],
                "symbol": position["symbol"], "side": position["side"],
                "volume_lots": position["volume_lots"],
                "reason": position["reason"],
                "source": "open_position_reconciliation",
            },
        )
        if event:
            recorded += 1
    result["operational_events_recorded"] = recorded
    return result


@app.get(
    "/api/v1/monitoring/positions/lifecycle",
    dependencies=[Depends(require_admin_token)],
)
def position_lifecycle_monitoring():
    """Compare fresh demo snapshots and deal history; never infer closure from absence alone."""
    store = telemetry_store()
    snapshots = store.recent_execution_states(limit=2)
    if not snapshots:
        return {"status": "waiting_for_terminal_snapshot", "events": [],
                "trading_enabled": False, "read_only": True}
    current = snapshots[0]
    observed = datetime.fromisoformat(current["observed_at"].replace("Z", "+00:00"))
    age = (datetime.now(timezone.utc) - observed).total_seconds()
    if current["environment"] != "demo" or age < -5 or age > 30:
        return {"status": "terminal_snapshot_stale_or_not_demo", "events": [],
                "trading_enabled": False, "read_only": True}
    previous = snapshots[1] if len(snapshots) > 1 else None
    expected_magic = int(os.getenv("FOREX_AUTOPILOT_EXECUTION_MAGIC", "61119001"))
    deals_by_position = {}
    if previous and previous.get("terminal_id") == current.get("terminal_id"):
        for position in previous["positions"]:
            if int(position.get("magic", -1)) != expected_magic:
                continue
            position_id = str(position.get("position_id") or "")
            if position_id:
                deals_by_position[position_id] = store.execution_deals_for_position(position_id)
    result = compare_position_lifecycle(
        previous, current, deals_by_position=deals_by_position,
        expected_magic=expected_magic,
    )
    outbox = EventOutbox()
    recorded = 0
    for item in result["events"]:
        identity = str(item.get("position_id") or item.get("ticket") or "unknown")
        fingerprint = hashlib.sha256(
            (str(item["event_type"]) + "|" + identity + "|" + current["observed_at"]).encode("utf-8")
        ).hexdigest()[:32]
        event = outbox.record(
            event_key="position-lifecycle:" + fingerprint,
            event_type=item["event_type"],
            severity="warning" if item["event_type"] == "position_disappearance_unconfirmed" else "info",
            message="MT5 position lifecycle change observed: " + item["event_type"],
            payload={"source": "position_lifecycle_monitor", **item,
                     "snapshot_at": current["observed_at"]},
        )
        if event:
            recorded += 1
    result["operational_events_recorded"] = recorded
    return result


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
    guard_payload = MT5ExecutionState(
        terminal_id=snapshot["terminal_id"], environment=snapshot["environment"],
        server=snapshot["server"], observed_at=observed,
        daily_loss_pct=snapshot["daily_loss_pct"],
        positions=[{key: value for key, value in position.items() if key != "related_deals"}
                   for position in managed],
    )
    guard = protective_stop_guard(guard_payload, telemetry_store())
    stop_alerts = [
        {**alert,
         "missing_stop_loss": "missing_stop_loss" in alert["reasons"],
         "missing_take_profit": next(
             (p["take_profit"] <= 0 for p in managed if p["ticket"] == alert["ticket"]), False
         ),
         "linked_deals": len(next(
             (p.get("related_deals", []) for p in managed if p["ticket"] == alert["ticket"]), []
         ))}
        for alert in guard["alerts"]
    ]
    for position in managed:
        if position["take_profit"] <= 0 and not any(
            item["ticket"] == position["ticket"] for item in stop_alerts
        ):
            stop_alerts.append({
                "ticket": position["ticket"], "position_id": position.get("position_id"),
                "symbol": position["symbol"], "missing_stop_loss": False,
                "missing_take_profit": True, "linked_deals": len(position.get("related_deals", [])),
                "reasons": ["missing_take_profit"],
            })
    issues = []
    if snapshot["environment"] != "demo":
        issues.append("terminal_not_on_demo_account")
    if age < -5 or age > stale_after:
        issues.append("execution_state_stale")
    max_daily_loss = float(os.getenv("FOREX_AUTOPILOT_MAX_DAILY_LOSS_PCT", "1.0"))
    if snapshot["daily_loss_pct"] >= max_daily_loss:
        issues.append("daily_loss_limit_reached")
    if guard["unprotected_positions"]:
        issues.append("managed_position_missing_or_invalid_stop_loss")
    if any(item["missing_take_profit"] for item in stop_alerts):
        issues.append("managed_position_missing_take_profit")
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
        "protective_guard": guard,
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
