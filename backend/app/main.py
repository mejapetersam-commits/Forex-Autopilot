import os
from datetime import datetime, timezone
from hmac import compare_digest

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.responses import FileResponse
from pathlib import Path

from app.broker.bridge import MT5AccountSnapshot, MT5CandleBatch, MT5CandleBulk, MT5Heartbeat, MT5Quote
from app.market_data.telemetry_store import TelemetryStore
from app.market_data.indicators import calculate_indicators
from app.strategy.engine import StrategyConfig, evaluate_signal
from app.backtesting.engine import BacktestConfig, run_backtest
from app.backtesting.optimization import optimize_walk_forward
from app.market_data.quality import assess_candle_quality

app = FastAPI(title="FOREX AUTOPILOT API", version="0.3.0")


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
        "stale_after_seconds": stale_after,
        "updated_at": now.isoformat(),
    }


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


@app.get(
    "/api/v1/backtests/run/{symbol}/{timeframe}",
    dependencies=[Depends(require_bridge_token)],
)
def run_historical_backtest(
    symbol: str,
    timeframe: str,
    pip_value_per_lot: float = Query(..., gt=0),
    limit: int = Query(default=5000, ge=61, le=5000),
    initial_equity: float = Query(default=10000, gt=0),
    risk_per_trade_pct: float = Query(default=0.25, gt=0, le=1.0),
    pip_size: float = Query(default=0.0001, gt=0),
    spread_pips: float = Query(default=1.0, ge=0, le=100),
    slippage_pips_per_side: float = Query(default=0.2, ge=0, le=100),
    commission_per_lot_per_side: float = Query(default=3.5, ge=0, le=1000),
):
    """Run an authenticated historical simulation on stored MT5 OHLC candles."""
    normalized_symbol = symbol.strip().upper()
    normalized_timeframe = timeframe.strip().upper()
    candles = telemetry_store().candle_history(normalized_symbol, normalized_timeframe, limit)
    config = BacktestConfig(
        initial_equity=initial_equity,
        risk_per_trade_pct=risk_per_trade_pct,
        pip_size=pip_size,
        pip_value_per_lot=pip_value_per_lot,
        spread_pips=spread_pips,
        slippage_pips_per_side=slippage_pips_per_side,
        commission_per_lot_per_side=commission_per_lot_per_side,
    )
    result = run_backtest(candles, config)
    return {
        "symbol": normalized_symbol,
        "timeframe": normalized_timeframe,
        "account_currency_note": "pip_value_per_lot must be supplied in the account currency for one standard lot.",
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
    pip_value_per_lot: float = Query(..., gt=0),
    limit: int = Query(default=1500, ge=400, le=5000),
    initial_equity: float = Query(default=10000, gt=0),
    risk_per_trade_pct: float = Query(default=0.25, gt=0, le=1.0),
    pip_size: float = Query(default=0.0001, gt=0),
    spread_pips: float = Query(default=1.0, ge=0, le=100),
    slippage_pips_per_side: float = Query(default=0.2, ge=0, le=100),
    commission_per_lot_per_side: float = Query(default=3.5, ge=0, le=1000),
    minimum_trades: int = Query(default=5, ge=1, le=100),
):
    """Tune on earlier candles and evaluate on later, untouched windows."""
    normalized_symbol = symbol.strip().upper()
    normalized_timeframe = timeframe.strip().upper()
    candles = telemetry_store().candle_history(normalized_symbol, normalized_timeframe, limit)
    config = BacktestConfig(
        initial_equity=initial_equity,
        risk_per_trade_pct=risk_per_trade_pct,
        pip_size=pip_size,
        pip_value_per_lot=pip_value_per_lot,
        spread_pips=spread_pips,
        slippage_pips_per_side=slippage_pips_per_side,
        commission_per_lot_per_side=commission_per_lot_per_side,
    )
    result = optimize_walk_forward(candles, config, minimum_trades=minimum_trades)
    return {
        "symbol": normalized_symbol,
        "timeframe": normalized_timeframe,
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
