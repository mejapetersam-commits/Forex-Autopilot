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


def test_demo_execution_ea_persists_attempt_before_broker_submission():
    source = EA_SOURCE.read_text(encoding="utf-8")
    marker = source.index("if(!MarkAttempted(command_id))", source.index("// Persist the attempt marker"))
    assert marker < source.index("g_trade.Buy(")
    assert "GlobalVariableSet(key" in source
    assert "GlobalVariablesFlush();" in source
    assert 'SendResult(command_id, outcome, result);' in source
    assert '"unknown"' in source


def test_demo_execution_ea_runs_broker_order_check_before_submission():
    source = EA_SOURCE.read_text(encoding="utf-8")
    assert "bool CheckBrokerOrder(" in source
    assert "OrderCheck(request, check)" in source
    assert source.index("CheckBrokerOrder(" , source.index("void ProcessCommand")) < source.index("g_trade.Buy(")


def test_demo_execution_ea_can_be_attached_safely_while_disabled():
    source = EA_SOURCE.read_text(encoding="utf-8")
    disabled = source.index("if(!InpEnableDemoExecution)", source.index("int OnInit"))
    assert "return INIT_SUCCEEDED;" in source[disabled:disabled + 500]
    assert "if(!InpEnableDemoExecution || !IsTradingPermitted())" in source

def test_demo_execution_ea_sanitizes_external_broker_comment_control_characters():
    source = EA_SOURCE.read_text(encoding="utf-8")
    assert 'StringReplace(safe_comment, ShortToString(13), " ");' in source
    assert 'StringReplace(safe_comment, ShortToString(10), " ");' in source
    assert 'StringReplace(safe_comment, ShortToString(9), " ");' in source
    assert r'StringReplace(safe_comment, "\"", "\\\"");' in source