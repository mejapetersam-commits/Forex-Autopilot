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


def test_quality_classifies_common_weekend_closure_as_possible_not_confirmed():
    result = assess_candle_quality(rows(
        "2026-11-20T20:55:00+00:00",  # Friday before common weekend pause
        "2026-11-22T21:05:00+00:00",  # Sunday reopening
    ), "M5")

    assert result["gap_count"] == 1
    assert result["possible_weekend_gap_count"] == 1
    assert result["calendar_review_gap_count"] == 0
    assert result["gaps"][0]["classification"] == "possible_weekend_closure"
    assert "verify" in result["gaps"][0]["classification_note"].lower()
    assert result["issue_count"] == 0


def test_weekend_heuristic_normalizes_non_utc_broker_timestamps():
    result = assess_candle_quality(rows(
        "2026-11-20T23:55:00+03:00",  # Friday 20:55 UTC
        "2026-11-23T00:05:00+03:00",  # Sunday 21:05 UTC
    ), "M5")

    assert result["possible_weekend_gap_count"] == 1
    assert result["calendar_review_gap_count"] == 0


def test_quality_flags_midweek_gap_for_broker_calendar_review():
    result = assess_candle_quality(rows(
        "2026-11-18T09:00:00+00:00",
        "2026-11-18T09:20:00+00:00",
    ), "M5")

    assert result["gap_count"] == 1
    assert result["possible_weekend_gap_count"] == 0
    assert result["calendar_review_gap_count"] == 1
    assert result["gaps"][0]["classification"] == "calendar_review_required"


def test_quality_does_not_excuse_long_gaps_merely_because_they_cross_weekend():
    result = assess_candle_quality(rows(
        "2026-11-19T09:00:00+00:00",
        "2026-11-23T09:00:00+00:00",
    ), "H1")

    assert result["calendar_review_gap_count"] == 1
    assert result["gaps"][0]["classification"] == "calendar_review_required"


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
