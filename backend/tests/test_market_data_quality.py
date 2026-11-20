from app.market_data.quality import assess_candle_quality, assess_candle_readiness


def rows(*times):
    return [
        {"opened_at": time, "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.15}
        for time in times
    ]


def test_quality_reports_valid_series_and_gap():
    result = assess_candle_quality(rows(
        "2026-11-02T09:00:00+00:00",
        "2026-11-02T09:05:00+00:00",
        "2026-11-02T09:20:00+00:00",
    ), "M5")
    assert result["status"] == "healthy"
    assert result["valid_ohlc_candles"] == 3
    assert result["gap_count"] == 1
    assert result["gaps"][0]["missing_interval_estimate"] == 2
    assert result["issue_count"] == 0


def test_quality_detects_invalid_ohlc_and_timezone():
    result = assess_candle_quality([{
        "opened_at": "2026-11-02T09:00:00",
        "open": 1.1, "high": 1.0, "low": 1.2, "close": 1.15,
    }], "M5")
    assert result["status"] == "issues_found"
    assert result["issue_count"] == 2


def test_quality_detects_duplicate_and_out_of_order_timestamps():
    result = assess_candle_quality(rows(
        "2026-11-02T09:05:00+00:00",
        "2026-11-02T09:05:00+00:00",
        "2026-11-02T09:00:00+00:00",
    ), "M5")
    assert result["issue_count"] == 2
    assert {item["type"] for item in result["issues"]} == {
        "duplicate_timestamp", "out_of_order_timestamp"
    }


def test_quality_rejects_unknown_timeframe():
    try:
        assess_candle_quality([], "TICK")
    except ValueError as exc:
        assert "Unsupported timeframe" in str(exc)
    else:
        raise AssertionError("Expected unsupported timeframe")


def test_readiness_requires_minimum_valid_history():
    result = assess_candle_readiness(rows(
        "2026-11-02T09:00:00+00:00",
        "2026-11-02T09:05:00+00:00",
    ), "M5", minimum_candles=3)
    assert result["status"] == "insufficient_history"
    assert result["coverage_pct"] == 66.67
    assert result["ready_for_research"] is False
    assert result["trading_enabled"] is False


def test_readiness_blocks_integrity_issues_even_when_count_is_met():
    candles = rows(
        "2026-11-02T09:00:00+00:00",
        "2026-11-02T09:05:00+00:00",
        "2026-11-02T09:05:00+00:00",
    )
    result = assess_candle_readiness(candles, "M5", minimum_candles=3)
    assert result["status"] == "integrity_review_required"
    assert result["ready_for_research"] is False


def test_readiness_rejects_invalid_minimum():
    try:
        assess_candle_readiness([], "M5", minimum_candles=0)
    except ValueError as exc:
        assert "at least one" in str(exc)
    else:
        raise AssertionError("Expected invalid minimum")
