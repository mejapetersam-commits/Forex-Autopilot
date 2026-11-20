from pathlib import Path


EA_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "mt5"
    / "Experts"
    / "ForexAutopilotTelemetry.mq5"
)


def test_mt5_ea_posts_all_backend_telemetry_routes():
    source = EA_SOURCE.read_text(encoding="utf-8")
    expected_routes = [
        'PostJson("/api/v1/mt5/heartbeat",',
        'PostJson("/api/v1/mt5/account",',
        'PostJson("/api/v1/mt5/quote",',
        'PostJson("/api/v1/mt5/specifications",',
        'PostJson("/api/v1/mt5/execution/state",',
        'PostJson("/api/v1/mt5/execution/history",',
        'PostJson("/api/v1/mt5/execution/orders",',
        'PostJson("/api/v1/mt5/candles/bulk",',
    ]
    for route in expected_routes:
        assert route in source, f"Missing MT5 telemetry route: {route}"


def test_mt5_ea_payload_fields_match_backend_contract():
    source = EA_SOURCE.read_text(encoding="utf-8")
    expected_fields = [
        "server",
        "terminal_connected",
        "observed_at",
        "account_currency",
        "balance",
        "equity",
        "margin",
        "free_margin",
        "leverage",
        "symbol",
        "bid",
        "ask",
        "timestamp",
        "position_id",
        "profit",
        "commission",
        "swap",
        "fee",
        "stop_loss",
        "take_profit",
    ]
    for field in expected_fields:
        assert field in source, f"Missing telemetry payload field: {field}"


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


def test_mt5_ea_publishes_broker_symbol_specifications_read_only():
    source = EA_SOURCE.read_text(encoding="utf-8")
    assert "void SendSymbolSpecifications()" in source
    assert 'PostJson("/api/v1/mt5/specifications", body)' in source
    assert "SYMBOL_TRADE_TICK_VALUE_LOSS" in source
    assert "SYMBOL_VOLUME_STEP" in source
    assert "SYMBOL_TRADE_STOPS_LEVEL" in source
    assert "SYMBOL_TRADE_MODE_FULL" in source


def test_read_only_telemetry_ea_sends_open_position_state():
    source = EA_SOURCE.read_text(encoding="utf-8")
    assert "void SendExecutionState()" in source
    assert 'PostJson("/api/v1/mt5/execution/state", body)' in source
    assert "CalculateDailyLossPct()" in source
    assert "daily_loss_pct" in source
    for field in (
        "\\\\"ticket\\\\"",
        "\\\\"symbol\\\\"",
        "\\\\"volume_lots\\\\"",
        "\\\\"stop_loss\\\\"",
        "\\\\"take_profit\\\\"",
        "\\\\"magic\\\\"",
    ):
        assert field in source


def test_read_only_mt5_bridge_uploads_broker_deal_and_order_history():
    source = EA_SOURCE.read_text(encoding="utf-8")
    assert "void SendExecutionHistory()" in source
    assert "HistorySelect(" in source
    assert "DEAL_POSITION_ID" in source
    assert 'PostJson("/api/v1/mt5/execution/history", body)' in source
    assert "demo broker history accepted; matching deals=" in source

    assert "void SendExecutionOrderHistory()" in source
    assert "HistoryOrdersTotal()" in source
    assert "HistoryOrderGetTicket(i)" in source
    assert 'PostJson("/api/v1/mt5/execution/orders", body)' in source
    for state in (
        "ORDER_STATE_CANCELED",
        "ORDER_STATE_REJECTED",
        "ORDER_STATE_EXPIRED",
        "ORDER_STATE_PLACED",
        "ORDER_STATE_PARTIAL",
        "ORDER_STATE_FILLED",
    ):
        assert state in source


def test_position_identity_is_transmitted_for_recovery_linking():
    source = EA_SOURCE.read_text(encoding="utf-8")
    assert "POSITION_IDENTIFIER" in source
    assert "DEAL_POSITION_ID" in source
    assert "position_id" in source


def test_bulk_candle_ingestion_is_bounded_and_refreshes_closed_candles():
    source = EA_SOURCE.read_text(encoding="utf-8")
    assert "InpCandleBootstrapBars = 500" in source
    assert "PERIOD_M5, PERIOD_M15, PERIOD_H1, PERIOD_H4" in source
    assert 'PostJson("/api/v1/mt5/candles/bulk", body)' in source
    assert "g_candle_bootstrap_complete = true" in source
    assert "InpCandleRefreshSeconds" in source


def test_telemetry_timer_refreshes_history_positions_and_specifications():
    source = EA_SOURCE.read_text(encoding="utf-8")
    assert "SendExecutionHistory();" in source
    assert "SendExecutionOrderHistory();" in source
    assert "SendExecutionState();" in source
    assert "SendSymbolSpecifications();" in source
    assert "EventSetTimer(1)" in source
