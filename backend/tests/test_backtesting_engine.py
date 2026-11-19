from app.backtesting.engine import BacktestConfig, run_backtest


def candles(count=180, direction=1):
    result = []
    price = 1.10
    for index in range(count):
        move = direction * (0.0002 + index * 0.000008)
        next_price = price + move
        result.append({
            "opened_at": f"2026-01-{index // 24 + 1:02d}T{index % 24:02d}:00:00+00:00",
            "open": price,
            "high": max(price, next_price) + 0.00015,
            "low": min(price, next_price) - 0.00015,
            "close": next_price,
        })
        price = next_price
    return result


def test_backtest_runs_and_reports_costs_and_risk():
    result = run_backtest(candles())
    assert result["status"] == "completed"
    assert result["candles_tested"] == 180
    assert result["execution_enabled"] is False
    assert result["assumptions"]["signal_timing"].startswith("completed candle")
    assert result["assumptions"]["spread_pips"] == 1.0
    assert result["max_drawdown_pct"] >= 0
    assert all(trade["commission"] >= 0 for trade in result["trades"])


def test_backtest_insufficient_history_returns_no_trades():
    result = run_backtest(candles(40))
    assert result["status"] == "insufficient_data"
    assert result["trades"] == []


def test_backtest_rejects_unsorted_or_duplicate_timestamps():
    rows = candles(100)
    rows[5]["opened_at"] = rows[4]["opened_at"]
    try:
        run_backtest(rows)
    except ValueError as exc:
        assert "strictly increasing" in str(exc)
    else:
        raise AssertionError("Expected chronological data validation")


def test_backtest_rejects_risk_over_one_percent():
    try:
        BacktestConfig(risk_per_trade_pct=1.5)
    except ValueError as exc:
        assert "1%" in str(exc)
    else:
        raise AssertionError("Expected risk cap validation")
