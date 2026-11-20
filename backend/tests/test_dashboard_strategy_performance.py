from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from app import main


class FakeStore:
    def candle_history(self, symbol, timeframe, limit):
        rows = []
        price = 1.10
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for index in range(180):
            close = price + 0.00005
            rows.append({
                "opened_at": (start + timedelta(hours=index)).isoformat(),
                "open": price,
                "high": close + 0.0001,
                "low": price - 0.0001,
                "close": close,
                "tick_volume": 100,
            })
            price = close
        return rows


def test_dashboard_strategy_performance_is_read_only(monkeypatch):
    monkeypatch.setattr(main, "telemetry_store", lambda: FakeStore())
    monkeypatch.setattr(main, "dashboard_symbols", lambda: {"EURUSDM", "GBPUSDM"})
    monkeypatch.setattr(
        main, "resolve_backtest_pip_values",
        lambda store, symbol, pip_size, pip_value: (0.0001, 10.0, "test_fixture"),
    )

    result = main.dashboard_strategy_performance(
        symbol="EURUSDm", timeframe="H1",
        include_walk_forward=False, limit=1000,
    )

    assert result["symbol"] == "EURUSDM"
    assert result["timeframe"] == "H1"
    assert result["candles_available"] == 180
    assert result["backtest"]["status"] == "completed"
    assert result["analytics"]["status"] == "completed"
    assert result["walk_forward"] is None
    assert result["trading_enabled"] is False
    assert result["execution_mode"] == "disabled"


def test_dashboard_strategy_performance_rejects_non_allowlisted_symbol(monkeypatch):
    monkeypatch.setattr(main, "dashboard_symbols", lambda: {"EURUSDM"})
    try:
        main.dashboard_strategy_performance(
            symbol="XAUUSD", timeframe="H1",
            include_walk_forward=False, limit=1000,
        )
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("Non-allowlisted dashboard symbol was accepted.")
