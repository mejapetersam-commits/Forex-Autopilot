from pathlib import Path


EA_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "mt5"
    / "Experts"
    / "ForexAutopilotTelemetry.mq5"
)


def test_mt5_ea_posts_all_backend_telemetry_routes():
    source = EA_SOURCE.read_text(encoding="utf-8")
    assert '"/api/v1/mt5/heartbeat"' in source
    assert '"/api/v1/mt5/account"' in source
    assert '"/api/v1/mt5/quote"' in source


def test_mt5_ea_payload_fields_match_backend_contract():
    source = EA_SOURCE.read_text(encoding="utf-8")
    expected_fields = [
        "\\\"server\\\"",
        "\\\"terminal_connected\\\"",
        "\\\"observed_at\\\"",
        "\\\"account_currency\\\"",
        "\\\"balance\\\"",
        "\\\"equity\\\"",
        "\\\"margin\\\"",
        "\\\"free_margin\\\"",
        "\\\"leverage\\\"",
        "\\\"symbol\\\"",
        "\\\"bid\\\"",
        "\\\"ask\\\"",
        "\\\"timestamp\\\"",
    ]
    for field in expected_fields:
        assert field in source


def test_mt5_ea_source_contains_no_order_execution_calls():
    source = EA_SOURCE.read_text(encoding="utf-8")
    forbidden = [
        "OrderSend(",
        "OrderSendAsync(",
        "PositionClose(",
        "PositionOpen(",
        "CTrade",
        "TRADE_ACTION_DEAL",
        "TRADE_ACTION_PENDING",
    ]
    for function_name in forbidden:
        assert function_name not in source


def test_mt5_ea_requires_https_and_a_long_bridge_token():
    source = EA_SOURCE.read_text(encoding="utf-8")
    assert 'StringFind(InpApiBaseUrl, "https://") != 0' in source
    assert "StringLen(Trimmed(InpBridgeToken)) < 32" in source
