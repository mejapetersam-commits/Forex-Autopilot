from app.broker.bridge import MT5CandleBatch
from app.market_data.telemetry_store import TelemetryStore


def batch() -> MT5CandleBatch:
    return MT5CandleBatch(
        symbol="EURUSDm",
        timeframe="M5",
        candles=[{
            "opened_at": "2026-11-20T09:00:00Z",
            "open": 1.1000,
            "high": 1.1020,
            "low": 1.0990,
            "close": 1.1010,
            "tick_volume": 100,
        }],
    )


def test_ingestion_summary_separates_receipts_from_unique_stored_candles(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry.sqlite3")

    store.save_candle_batches([batch()])
    store.save_candle_batches([batch()])

    summary = store.candle_ingestion_summary()
    assert summary["batch_count"] == 2
    assert summary["series_count"] == 1
    series = summary["series"][0]
    assert series["candles_received"] == 2
    assert series["unique_candles_stored"] == 1
    assert series["first_stored_candle_at"] == "2026-11-20T09:00:00+00:00"
    assert series["latest_stored_candle_at"] == "2026-11-20T09:00:00+00:00"
