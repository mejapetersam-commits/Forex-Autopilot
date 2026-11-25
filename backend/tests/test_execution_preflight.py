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
        trading_paused=False, broker_connected=True, account_equity=1000, free_margin=900,
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



def test_persisted_pause_and_kill_switch_override_preflight(tmp_path):
    from app.execution.ledger import ExecutionLedger
    from app.execution.preflight import evaluate_with_runtime_controls

    intent, snapshot = valid_inputs()
    ledger = ExecutionLedger(str(tmp_path / "runtime-controls.sqlite3"))
    paused = evaluate_with_runtime_controls(intent, snapshot, ledger)
    assert paused["approved"] is False
    assert any("paused" in reason for reason in paused["reasons"])

    ledger.set_control("trading_paused", False)
    ledger.set_control("kill_switch_active", False)
    allowed = evaluate_with_runtime_controls(intent, snapshot, ledger)
    assert allowed["approved"] is True
    assert allowed["execution_submitted"] is False


def test_preflight_enforces_broker_volume_step_and_trade_permission():
    from dataclasses import replace
    intent, snapshot = valid_inputs()
    broker = replace(
        snapshot, require_broker_specification=True,
        broker_trade_allowed=True, broker_volume_min=0.01,
        broker_volume_max=10.0, broker_volume_step=0.01,
        broker_tick_size=0.00001, broker_tick_value_loss=1.0,
    )
    result = evaluate_execution_preflight(intent, broker)
    assert result["approved"] is False
    assert any("risk ceiling" in reason for reason in result["reasons"])

    safe_intent = replace(intent, stop_loss=1.0991)
    safe = evaluate_execution_preflight(safe_intent, broker)
    assert safe["approved"] is True

    invalid_volume = replace(intent, volume_lots=0.015, stop_loss=1.0991)
    result = evaluate_execution_preflight(invalid_volume, broker)
    assert result["approved"] is False
    assert any("volume step" in reason for reason in result["reasons"])


def test_preflight_fails_closed_without_trade_enabled_broker_specification():
    from dataclasses import replace
    intent, snapshot = valid_inputs()
    result = evaluate_execution_preflight(
        intent, replace(snapshot, require_broker_specification=True)
    )
    assert result["approved"] is False
    assert any("broker symbol specifications" in reason for reason in result["reasons"])
