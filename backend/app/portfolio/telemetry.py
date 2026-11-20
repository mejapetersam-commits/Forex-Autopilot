"""Read-only portfolio exposure estimates from fresh MT5 telemetry.

Amounts are converted into the account currency using the broker quote for the
instrument. Unsupported conversion paths and stale inputs are reported rather
than silently estimated.
"""
from __future__ import annotations
from datetime import datetime, timezone
from math import isfinite
from typing import Any
from app.portfolio.currency_exposure import CurrencyExposure, CurrencyExposureCalculator

def _timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None

def _age(value: Any, now: datetime) -> float | None:
    stamp = _timestamp(value)
    if stamp is None:
        return None
    seconds = (now - stamp).total_seconds()
    return seconds if seconds >= -5 else None

def build_portfolio_exposure(
    *,
    execution_state: dict[str, Any] | None,
    account: dict[str, Any] | None,
    quotes: list[dict[str, Any]],
    specifications: list[dict[str, Any]],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Summarize current positions, gross currency concentration and stop risk."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("Portfolio calculation time must be timezone-aware.")
    current = current.astimezone(timezone.utc)
    reasons: list[str] = []
    if not execution_state or not account:
        return {
            "status": "unavailable", "reason": "Fresh execution and account telemetry are required.",
            "positions": [], "currencies": [], "open_position_count": 0,
            "total_open_stop_risk": None, "account_equity": None,
            "account_currency": None, "execution_mode": "disabled", "trading_enabled": False,
            "updated_at": current.isoformat(),
        }
    state_age = _age(execution_state.get("observed_at"), current)
    account_age = _age(account.get("observed_at"), current)
    if execution_state.get("environment") != "demo":
        reasons.append("Execution snapshot is not from the configured demo environment.")
    if state_age is None or state_age > 20:
        reasons.append("Execution-state telemetry is missing, future-dated or stale.")
    if account_age is None or account_age > 30:
        reasons.append("Account telemetry is missing, future-dated or stale.")
    equity = float(account.get("equity") or 0)
    account_currency = str(account.get("account_currency") or "").upper()
    if not isfinite(equity) or equity <= 0 or len(account_currency) != 3:
        reasons.append("Account equity or currency is invalid.")
    if reasons:
        return {
            "status": "stale", "reasons": reasons, "positions": [], "currencies": [],
            "open_position_count": len(execution_state.get("positions", [])),
            "total_open_stop_risk": None, "account_equity": equity if isfinite(equity) else None,
            "account_currency": account_currency or None,
            "execution_mode": "disabled", "trading_enabled": False, "updated_at": current.isoformat(),
        }

    quote_map = {str(row.get("symbol", "")).upper(): row for row in quotes}
    spec_map = {str(row.get("symbol", "")).upper(): row for row in specifications}
    exposures: list[CurrencyExposure] = []
    position_rows: list[dict[str, Any]] = []
    all_stop_risk_known = True
    total_stop_risk = 0.0

    for position in execution_state.get("positions", []):
        symbol = str(position.get("symbol", "")).upper()
        spec, quote = spec_map.get(symbol), quote_map.get(symbol)
        if not spec or not quote:
            reasons.append(f"{symbol}: broker specification or live quote is missing.")
            all_stop_risk_known = False
            continue
        quote_age = _age(quote.get("observed_at"), current)
        spec_age = _age(spec.get("observed_at"), current)
        if quote_age is None or quote_age > 15 or spec_age is None or spec_age > 300:
            reasons.append(f"{symbol}: quote or broker specification is stale.")
            all_stop_risk_known = False
            continue
        bid, ask = float(quote.get("bid") or 0), float(quote.get("ask") or 0)
        volume = float(position.get("volume_lots") or 0)
        contract = float(spec.get("contract_size") or 0)
        tick_size = float(spec.get("tick_size") or 0)
        tick_value = float(spec.get("tick_value_loss") or 0)
        base = str(spec.get("base_currency") or "").upper()
        profit = str(spec.get("profit_currency") or "").upper()
        if (not all(isfinite(x) for x in (bid, ask, volume, contract, tick_size, tick_value))
                or bid <= 0 or ask < bid or volume <= 0 or contract <= 0
                or tick_size <= 0 or tick_value <= 0 or len(base) != 3
                or profit != account_currency or base == profit):
            reasons.append(f"{symbol}: unsupported or invalid quote/specification conversion.")
            all_stop_risk_known = False
            continue
        mid = (bid + ask) / 2
        signed_base_units = volume * contract * (1 if position.get("side") == "buy" else -1)
        base_value = signed_base_units * mid
        quote_value = -base_value
        ticket = str(position.get("ticket", ""))
        exposures.append(CurrencyExposure(ticket=ticket, currency=base, amount_account_currency=base_value))
        exposures.append(CurrencyExposure(ticket=ticket, currency=profit, amount_account_currency=quote_value))

        stop = float(position.get("stop_loss") or 0)
        market_close = bid if position.get("side") == "buy" else ask
        risk = None
        if stop <= 0:
            all_stop_risk_known = False
            reasons.append(f"{symbol} ticket {ticket}: no protective stop; stop risk is unknown.")
        else:
            distance = (market_close - stop) if position.get("side") == "buy" else (stop - market_close)
            if distance <= 0:
                all_stop_risk_known = False
                reasons.append(f"{symbol} ticket {ticket}: stop is not on the protective side of market.")
            else:
                risk = (distance / tick_size) * tick_value * volume
                total_stop_risk += risk
        position_rows.append({
            "ticket": ticket, "symbol": symbol, "side": position.get("side"),
            "volume_lots": volume, "mark_price": mid, "stop_loss": stop or None,
            "notional_account_currency": round(abs(base_value), 2),
            "estimated_stop_risk": round(risk, 2) if risk is not None else None,
        })

    summaries = CurrencyExposureCalculator.aggregate(exposures, equity)
    return {
        "status": "healthy" if not reasons else "incomplete",
        "reasons": reasons,
        "positions": position_rows,
        "currencies": [item.model_dump() for item in summaries.values()],
        "open_position_count": len(execution_state.get("positions", [])),
        "total_open_stop_risk": round(total_stop_risk, 2) if all_stop_risk_known else None,
        "account_equity": equity,
        "account_currency": account_currency,
        "execution_environment": execution_state.get("environment"),
        "execution_state_age_seconds": round(state_age, 1),
        "account_age_seconds": round(account_age, 1),
        "execution_mode": "disabled",
        "trading_enabled": False,
        "updated_at": current.isoformat(),
    }
