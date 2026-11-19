from pathlib import Path


EA_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "mt5" / "Experts" / "ForexAutopilotDemoExecution.mq5"
)


def test_demo_execution_ea_is_separate_from_read_only_telemetry():
    source = EA_SOURCE.read_text(encoding="utf-8")
    telemetry = EA_SOURCE.with_name("ForexAutopilotTelemetry.mq5").read_text(encoding="utf-8")
    assert "#include <Trade/Trade.mqh>" in source
    assert "CTrade" in source
    assert "OrderSend(" not in telemetry
    assert "CTrade" not in telemetry
    assert "OrderSend(" not in telemetry


def test_demo_execution_ea_fails_closed_on_real_accounts_and_default_off():
    source = EA_SOURCE.read_text(encoding="utf-8")
    assert "input bool   InpEnableDemoExecution = false" in source
    assert "ACCOUNT_TRADE_MODE_DEMO" in source
    assert "if(!IsDemoAccount())" in source
    assert "InpMaxLotsPerTrade > 0.01" in source
    assert "InpMaxOpenPositions > 1" in source


def test_demo_execution_ea_checks_symbol_volume_stops_margin_and_trade_permissions():
    source = EA_SOURCE.read_text(encoding="utf-8")
    for required in (
        "IsAllowedSymbol(symbol)", "ValidVolume(symbol, volume)",
        "SYMBOL_TRADE_STOPS_LEVEL", "OrderCalcMargin(",
        "ACCOUNT_TRADE_ALLOWED", "TERMINAL_TRADE_ALLOWED",
        "MQL_TRADE_ALLOWED", "TRADE_RETCODE_DONE_PARTIAL",
    ):
        assert required in source


def test_demo_execution_ea_marks_attempt_before_broker_submission():
    source = EA_SOURCE.read_text(encoding="utf-8")
    assert source.index("MarkAttempted(command_id);", source.index("// Persist the attempt marker")) < source.index("g_trade.Buy(")
    assert 'SendResult(command_id, outcome, result);' in source
    assert '"unknown"' in source
