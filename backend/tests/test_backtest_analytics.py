import pytest

from app.backtesting.analytics import BacktestAnalyticsError, analyse_backtest


def sample_result(trades):
    return {
        "status": "completed",
        "initial_equity": 10000,
        "final_equity": 10025,
        "max_drawdown_pct": 1.25,
        "trades": [{"net_pnl": value} for value in trades],
    }


def test_analytics_reports_distribution_and_streaks():
    result = analyse_backtest(sample_result([10, 5, -4, -6, -2, 0, 7]))
    assert result["total_trades"] == 7
    assert result["wins"] == 3
    assert result["losses"] == 3
    assert result["breakeven"] == 1
    assert result["max_consecutive_wins"] == 2
    assert result["max_consecutive_losses"] == 3
    assert result["payoff_ratio"] == pytest.approx(2.2)
    assert result["execution_enabled"] is False


def test_analytics_rejects_incomplete_or_non_finite_results():
    with pytest.raises(BacktestAnalyticsError):
        analyse_backtest({"status": "running", "trades": []})
    result = sample_result([1])
    result["trades"][0]["net_pnl"] = float("nan")
    with pytest.raises(BacktestAnalyticsError):
        analyse_backtest(result)


def test_analytics_handles_no_trades():
    result = analyse_backtest(sample_result([]))
    assert result["total_trades"] == 0
    assert result["median_trade_pnl"] == 0
    assert result["payoff_ratio"] is None
