from datetime import datetime, timedelta, timezone

from app import main


class ComparisonStore:
    def candle_history(self, symbol, timeframe, limit):
        rows = []
        price = 1.10
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for index in range(180):
            close = price + 0.00004
            rows.append({
                "opened_at": (start + timedelta(minutes=15 * index)).isoformat(),
                "open": price,
                "high": close + 0.0001,
                "low": price - 0.0001,
                "close": close,
                "tick_volume": 100,
            })
            price = close
        return rows


def test_dashboard_strategy_comparison_returns_research_only_grid(monkeypatch):
    monkeypatch.setattr(main, "telemetry_store", lambda: ComparisonStore())
    monkeypatch.setattr(main, "dashboard_symbols", lambda: {"EURUSDM", "GBPUSDM"})
    monkeypatch.setattr(
        main, "resolve_backtest_pip_values",
        lambda store, symbol, pip_size, pip_value: (0.0001, 10.0, "test_fixture"),
    )

    result = main.dashboard_strategy_comparison(limit=1000)

    assert len(result["items"]) == 6
    assert {item["symbol"] for item in result["items"]} == {"EURUSDM", "GBPUSDM"}
    assert {item["timeframe"] for item in result["items"]} == {"M15", "H1", "H4"}
    assert all(item["status"] == "completed" for item in result["items"])
    assert result["ranked_count"] == 6
    assert result["trading_enabled"] is False
    assert result["execution_mode"] == "disabled"
    assert all(item["execution_enabled"] is False for item in result["items"])


def test_dashboard_strategy_comparison_handles_missing_market_history(monkeypatch):
    class EmptyStore:
        def candle_history(self, symbol, timeframe, limit):
            return []

    monkeypatch.setattr(main, "telemetry_store", lambda: EmptyStore())
    monkeypatch.setattr(main, "dashboard_symbols", lambda: {"EURUSDM"})

    result = main.dashboard_strategy_comparison(limit=1000)

    assert len(result["items"]) == 3
    assert all(item["status"] == "insufficient_data" for item in result["items"])
    assert result["ranked_count"] == 0
