from app.backtesting.engine import BacktestConfig
from app.backtesting.optimization import optimize_walk_forward


def make_candles(count=500):
    rows = []
    price = 1.10
    for index in range(count):
        # Alternating regimes reduce the chance that a test only sees one
        # perfectly monotonic synthetic trend.
        direction = 1 if (index // 90) % 2 == 0 else -1
        move = direction * (0.00012 + (index % 17) * 0.000004)
        next_price = price + move
        rows.append({
            "opened_at": f"2026-01-{index // 24 + 1:02d}T{index % 24:02d}:00:00+00:00",
            "open": price,
            "high": max(price, next_price) + 0.0002,
            "low": min(price, next_price) - 0.0002,
            "close": next_price,
        })
        price = next_price
    return rows


def test_walk_forward_requires_minimum_history():
    result = optimize_walk_forward(make_candles(200), BacktestConfig())
    assert result["status"] == "insufficient_data"
    assert result["execution_enabled"] is False


def test_walk_forward_returns_two_chronological_validation_folds():
    result = optimize_walk_forward(make_candles(), BacktestConfig(), minimum_trades=1)
    assert result["status"] == "completed"
    assert result["candidate_count_per_fold"] == 16
    assert result["fold_count"] == 2
    assert result["folds"][0]["training_candles"] < result["folds"][1]["training_candles"]
    assert result["execution_enabled"] is False
    assert "not_live_validation" in result["research_status"]


def test_walk_forward_rejects_invalid_trade_sample():
    try:
        optimize_walk_forward(make_candles(), BacktestConfig(), minimum_trades=0)
    except ValueError as exc:
        assert "minimum_trades" in str(exc)
    else:
        raise AssertionError("Expected invalid minimum trade count")
