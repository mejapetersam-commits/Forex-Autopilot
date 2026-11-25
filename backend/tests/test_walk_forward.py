from app.backtesting.engine import BacktestConfig
from app.backtesting import optimization
from app.backtesting.optimization import optimize_walk_forward


def make_candles(count=500):
    rows = []
    price = 1.10

    for index in range(count):
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


def test_walk_forward_stops_when_no_candidate_meets_training_sample(monkeypatch):
    calls = []

    def insufficient_backtest(candles, config):
        calls.append(len(candles))
        return {
            "status": "insufficient_data",
            "total_trades": 0,
        }

    monkeypatch.setattr(optimization, "run_backtest", insufficient_backtest)

    result = optimize_walk_forward(
        make_candles(),
        BacktestConfig(),
        minimum_trades=5,
    )

    assert result["status"] == "insufficient_evidence"
    assert result["folds"][-1]["eligible_candidate_count"] == 0
    assert len(calls) == 16
    assert result["execution_enabled"] is False


def test_walk_forward_uses_configured_warmup_for_validation(monkeypatch):
    calls = []

    def completed_backtest(candles, config):
        calls.append(len(candles))
        return {
            "status": "completed",
            "total_trades": 10,
            "return_pct": 1.0,
            "profit_factor": 1.5,
            "max_drawdown_pct": 1.0,
            "expectancy_per_trade": 1.0,
            "win_rate_pct": 60.0,
        }

    monkeypatch.setattr(optimization, "run_backtest", completed_backtest)

    config = BacktestConfig(minimum_candles=75)
    result = optimize_walk_forward(make_candles(500), config, minimum_trades=5)

    assert result["status"] == "completed"
    # Last two calls are the two validation backtests, after 16 training
    # candidate evaluations in each fold.
    assert calls[16] == 175
    assert calls[33] == 200
    assert result["folds"][0]["validation_candles_including_warmup"] == 175
    assert result["folds"][1]["validation_candles_including_warmup"] == 200
