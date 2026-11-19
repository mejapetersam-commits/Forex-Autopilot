"""Execution preflight gate. Deliberately contains no broker order submission."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from math import isfinite


@dataclass(frozen=True)
class TradeIntent:
    symbol: str
    side: str
    volume_lots: float
    stop_loss: float | None
    take_profit: float | None
    requested_at: datetime


@dataclass(frozen=True)
class ExecutionSnapshot:
    environment: str
    trading_enabled: bool
    kill_switch_active: bool
    broker_connected: bool
    account_equity: float
    free_margin: float
    quote_bid: float
    quote_ask: float
    quote_age_seconds: float
    account_age_seconds: float
    open_positions: int
    daily_loss_pct: float
    symbol_allowlist: tuple[str, ...]
    max_spread_pips: float = 2.0
    pip_size: float = 0.0001
    max_open_positions: int = 2
    max_daily_loss_pct: float = 1.0
    trading_paused: bool = True
    require_broker_specification: bool = False
    broker_trade_allowed: bool | None = None
    broker_volume_min: float | None = None
    broker_volume_max: float | None = None
    broker_volume_step: float | None = None
    broker_tick_size: float | None = None
    broker_tick_value_loss: float | None = None
    max_volume_lots: float = 0.01
    max_risk_per_trade_pct: float = 0.25


def evaluate_execution_preflight(
    intent: TradeIntent,
    snapshot: ExecutionSnapshot,
    *,
    max_quote_age_seconds: float = 5.0,
    max_account_age_seconds: float = 30.0,
) -> dict[str, object]:
    """Return explicit allow/deny reasons; never calls a broker or places an order."""
    reasons: list[str] = []
    symbol = intent.symbol.strip().upper()
    side = intent.side.strip().lower()
    numeric = (
        intent.volume_lots, snapshot.account_equity, snapshot.free_margin,
        snapshot.quote_bid, snapshot.quote_ask, snapshot.quote_age_seconds,
        snapshot.account_age_seconds, snapshot.daily_loss_pct,
        snapshot.max_spread_pips, snapshot.pip_size,
    )
    if not all(isfinite(float(value)) for value in numeric):
        reasons.append("Non-finite numeric input.")
    if not snapshot.trading_enabled:
        reasons.append("Trading is disabled by configuration.")
    if snapshot.kill_switch_active:
        reasons.append("Emergency kill switch is active.")
    if snapshot.trading_paused:
        reasons.append("Automation is paused.")
    if snapshot.environment.strip().lower() != "demo":
        reasons.append("Only demo environment is permitted by this execution gate.")
    if not snapshot.broker_connected:
        reasons.append("Broker terminal is not connected.")
    if symbol not in {item.upper() for item in snapshot.symbol_allowlist}:
        reasons.append("Symbol is not allowlisted.")
    if side not in {"buy", "sell"}:
        reasons.append("Side must be buy or sell.")
    if intent.volume_lots <= 0:
        reasons.append("Volume must be positive.")
    if intent.volume_lots > snapshot.max_volume_lots:
        reasons.append("Volume exceeds the configured local per-trade ceiling.")
    if snapshot.require_broker_specification:
        spec_values = (
            snapshot.broker_volume_min, snapshot.broker_volume_max,
            snapshot.broker_volume_step, snapshot.broker_tick_size,
            snapshot.broker_tick_value_loss,
        )
        if snapshot.broker_trade_allowed is not True or any(
            value is None or not isfinite(float(value)) or float(value) <= 0
            for value in spec_values
        ):
            reasons.append("Fresh, trade-enabled broker symbol specifications are required.")
        else:
            minimum = float(snapshot.broker_volume_min)
            maximum = float(snapshot.broker_volume_max)
            step = float(snapshot.broker_volume_step)
            if intent.volume_lots < minimum or intent.volume_lots > maximum:
                reasons.append("Volume is outside broker minimum/maximum limits.")
            elif abs((intent.volume_lots - minimum) / step - round((intent.volume_lots - minimum) / step)) > 1e-6:
                reasons.append("Volume does not align with the broker volume step.")
            elif intent.stop_loss is not None and snapshot.account_equity > 0:
                entry = snapshot.quote_ask if side == "buy" else snapshot.quote_bid
                risk_cash = (
                    abs(entry - intent.stop_loss) / float(snapshot.broker_tick_size)
                    * float(snapshot.broker_tick_value_loss) * intent.volume_lots
                )
                risk_pct = risk_cash / snapshot.account_equity * 100.0
                if risk_pct > snapshot.max_risk_per_trade_pct:
                    reasons.append("Estimated stop-loss risk exceeds the per-trade risk ceiling.")
    if intent.stop_loss is None or not isfinite(float(intent.stop_loss)) or intent.stop_loss <= 0:
        reasons.append("A valid protective stop-loss is mandatory.")
    if intent.take_profit is None or not isfinite(float(intent.take_profit)) or intent.take_profit <= 0:
        reasons.append("A valid take-profit is mandatory.")
    if intent.stop_loss is not None and intent.take_profit is not None:
        if side == "buy" and not (intent.stop_loss < snapshot.quote_bid and intent.take_profit > snapshot.quote_ask):
            reasons.append("Buy stop-loss must be below bid and take-profit above ask.")
        if side == "sell" and not (intent.stop_loss > snapshot.quote_ask and intent.take_profit < snapshot.quote_bid):
            reasons.append("Sell stop-loss must be above ask and take-profit below bid.")
    if snapshot.account_equity <= 0 or snapshot.free_margin <= 0:
        reasons.append("Account equity and free margin must be positive.")
    if snapshot.quote_bid <= 0 or snapshot.quote_ask <= snapshot.quote_bid:
        reasons.append("Quote is invalid or crossed.")
    if snapshot.quote_age_seconds < 0 or snapshot.quote_age_seconds > max_quote_age_seconds:
        reasons.append("Quote is stale.")
    if snapshot.account_age_seconds < 0 or snapshot.account_age_seconds > max_account_age_seconds:
        reasons.append("Account snapshot is stale.")
    if snapshot.pip_size <= 0:
        reasons.append("Pip size must be positive.")
    elif snapshot.quote_ask > snapshot.quote_bid:
        spread = (snapshot.quote_ask - snapshot.quote_bid) / snapshot.pip_size
        if spread > snapshot.max_spread_pips:
            reasons.append("Current spread exceeds configured maximum.")
    if snapshot.open_positions >= snapshot.max_open_positions:
        reasons.append("Maximum open-position count reached.")
    if snapshot.daily_loss_pct >= snapshot.max_daily_loss_pct:
        reasons.append("Daily loss limit reached.")
    if intent.requested_at.tzinfo is None or intent.requested_at.utcoffset() is None:
        reasons.append("Intent timestamp must be timezone-aware.")

    return {
        "approved": not reasons,
        "symbol": symbol,
        "side": side,
        "volume_lots": intent.volume_lots,
        "reasons": reasons,
        "execution_submitted": False,
        "note": "Preflight only. This module does not submit, modify or close broker orders.",
    }



def evaluate_with_runtime_controls(intent, snapshot, ledger, **kwargs):
    """Apply persisted pause/kill-switch state before evaluating every intent."""
    controls = ledger.controls()
    effective = replace(
        snapshot,
        trading_paused=controls["trading_paused"],
        kill_switch_active=controls["kill_switch_active"],
    )
    return evaluate_execution_preflight(intent, effective, **kwargs)
