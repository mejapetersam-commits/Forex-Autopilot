import pytest\n\nfrom app.strategy.engine import StrategyConfig, evaluate_signal


def make_trend_candles(direction: int, count: int = 100):
    rows = []
    price = 1.10
    for index in range(count):
        next_price = price + direction * (0.0002 + index * 0.00001)
        rows.append({
            "open": price,
            "high": max(price, next_price) + 0.0002,
            "low": min(price, next_price) - 0.0002,
            "close": next_price,
            "opened_at": f"2026-01-{(index % 28) + 1:02d}T00:00:00+00:00",
        })
        price = next_price
    return rows


def test_bullish_alignment_produces_candidate_only():
    result = evaluate_signal(make_trend_candles(1))
    assert result["signal"] == "buy"
    assert result["candidate_levels"]["stop_loss"] < result["candidate_levels"]["reference_close"]
    assert result["candidate_levels"]["take_profit"] > result["candidate_levels"]["reference_close"]
    assert result["execution_enabled"] is False
    assert result["research_status"] == "unvalidated_hypothesis"


def test_bearish_alignment_produces_candidate_only():
    result = evaluate_signal(make_trend_candles(-1))
    assert result["signal"] == "sell"
    assert result["candidate_levels"]["stop_loss"] > result["candidate_levels"]["reference_close"]
    assert result["candidate_levels"]["take_profit"] < result["candidate_levels"]["reference_close"]
    assert result["execution_enabled"] is False


def test_insufficient_history_never_generates_signal():
    result = evaluate_signal(make_trend_candles(1, 20))
    assert result["signal"] == "insufficient_data"
    assert "candidate_levels" not in result


def test_strategy_configuration_rejects_unsafe_parameters():
    try:
        StrategyConfig(minimum_candles=20)
    except ValueError as exc:
        assert "50" in str(exc)
    else:
        raise AssertionError("Expected minimum history validation")


@pytest.mark.parametrize("field,value", [
    ("long_rsi_min", float("nan")),
    ("short_rsi_max", float("inf")),
    ("atr_stop_multiple", float("nan")),
    ("reward_risk_ratio", float("inf")),
])
def test_strategy_configuration_rejects_non_finite_parameters(field, value):
    with pytest.raises(ValueError, match="finite"):
        StrategyConfig(**{field: value})
