from app.market_data.quality import assess_candle_quality


def test_quality_reports_valid_series_and_gap():
    rows = [
        {"opened_at": "2026-11-02T09:00:00+00:00", "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.15},
        {"opened_at": "2026-11-02T09:05:00+00:00", "open": 1.15, "high": 1.2, "low": 1.1, "close": 1.18},
        {"opened_at": "2026-11-02T09:20:00+00:00", "open": 1.18, "high": 1.2, "low": 1.1, "close": 1.17},
    ]
    result = assess_candle_quality(rows, "M5")
    assert result["status"] == "healthy"
    assert result["valid_ohlc_candles"] == 3
    assert result["gap_count"] == 1


def test_quality_detects_invalid_ohlc_and_timezone():
    rows = [{
        "opened_at": "2026-11-02T09:00:00",
        "open": 1.1, "high": 1.0, "low": 1.2, "close": 1.15,
    }]
    result = assess_candle_quality(rows, "M5")
    assert result["status"] == "issues_found"
    assert len(result["issues"]) == 2


def test_quality_rejects_unknown_timeframe():
    try:
        assess_candle_quality([], "TICK")
    except ValueError as exc:
        assert "Unsupported timeframe" in str(exc)
    else:
        raise AssertionError("Expected unsupported timeframe")
