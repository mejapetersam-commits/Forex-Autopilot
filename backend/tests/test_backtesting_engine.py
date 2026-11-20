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
    curve = result["equity_curve"]
    assert curve[0]["event"] == "initial"
    assert curve[0]["equity"] == result["initial_equity"]
    assert all(point["time"] for point in curve)
    assert all(
        curve[index]["time"] < curve[index + 1]["time"]
        for index in range(len(curve) - 1)
    )
    assert curve[-1]["equity"] == result["final_equity"]


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



def test_backtest_halts_after_daily_loss_and_max_drawdown(monkeypatch):
    import app.backtesting.engine as engine

    def forced_buy_signal(*args, **kwargs):
        return {
            "signal": "buy",
            "candidate_levels": {
                "reference_close": 1.1000,
                "stop_loss": 1.0998,
                "take_profit": 1.1040,
            },
        }

    monkeypatch.setattr(engine, "evaluate_signal", forced_buy_signal)
    rows = []
    price = 1.1000
    for index in range(70):
        op = price
        low = price - 0.00005
        high = price + 0.0001
        if index == 61:
            op = 1.0950  # Adverse weekend/news-style gap through the stop.
            low = 1.0940
        rows.append({
            "opened_at": f"2026-01-{index // 24 + 1:02d}T{index % 24:02d}:00:00+00:00",
            "open": op, "high": max(op, high), "low": min(op, low), "close": op,
        })
        price = op

    result = run_backtest(
        rows,
        BacktestConfig(
            initial_equity=10_000,
            risk_per_trade_pct=0.25,
            max_daily_loss_pct=1.0,
            max_drawdown_pct=5.0,
        ),
    )
    assert result["total_trades"] == 1
    assert result["risk_limits"]["daily_loss_halt_triggered_at_least_once"] is True
    assert result["halt_events"][0]["type"] == "daily_loss_limit"
    assert result["execution_enabled"] is False


def test_backtest_rejects_loss_limits_above_hard_caps():
    try:
        BacktestConfig(max_daily_loss_pct=4.0)
    except ValueError as exc:
        assert "hard safety caps" in str(exc)
    else:
        raise AssertionError("Expected daily loss hard cap rejection")
