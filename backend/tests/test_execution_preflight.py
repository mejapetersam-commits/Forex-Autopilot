from datetime import datetime, timezone

from app.execution.preflight import ExecutionSnapshot, TradeIntent, evaluate_execution_preflight


def valid_inputs():
    intent = TradeIntent(
        symbol="EURUSDm", side="buy", volume_lots=0.01,
        stop_loss=1.09, take_profit=1.12,
        requested_at=datetime.now(timezone.utc),
    )
    snapshot = ExecutionSnapshot(
        environment="demo", trading_enabled=True, kill_switch_active=False,
        broker_connected=True, account_equity=1000, free_margin=900,
        quote_bid=1.1000, quote_ask=1.1001, quote_age_seconds=0.5,
        account_age_seconds=1, open_positions=0, daily_loss_pct=0.1,
        symbol_allowlist=("EURUSDm",), max_spread_pips=2, pip_size=0.0001,
    )
    return intent, snapshot


def test_preflight_approves_only_when_every_gate_passes():
    intent, snapshot = valid_inputs()
    result = evaluate_execution_preflight(intent, snapshot)
    assert result["approved"] is True
    assert result["execution_submitted"] is False


def test_preflight_denies_when_trading_disabled_or_kill_switch_active():
    intent, snapshot = valid_inputs()
    from dataclasses import replace
    result = evaluate_execution_preflight(
        intent, replace(snapshot, trading_enabled=False, kill_switch_active=True)
    )
    assert result["approved"] is False
    assert any("disabled" in reason for reason in result["reasons"])
    assert any("kill switch" in reason for reason in result["reasons"])


def test_preflight_denies_stale_data_missing_stop_and_excess_spread():
    intent, snapshot = valid_inputs()
    from dataclasses import replace
    result = evaluate_execution_preflight(
        replace(intent, stop_loss=None),
        replace(snapshot, quote_age_seconds=30, quote_ask=1.1010),
    )
    assert result["approved"] is False
    assert any("stale" in reason for reason in result["reasons"])
    assert any("stop-loss" in reason for reason in result["reasons"])
    assert any("spread" in reason for reason in result["reasons"])


def test_preflight_denies_live_environment_and_unapproved_symbol():
    intent, snapshot = valid_inputs()
    from dataclasses import replace
    result = evaluate_execution_preflight(
        replace(intent, symbol="XAUUSD"),
        replace(snapshot, environment="live"),
    )
    assert result["approved"] is False
    assert any("demo" in reason for reason in result["reasons"])
    assert any("allowlisted" in reason for reason in result["reasons"])
