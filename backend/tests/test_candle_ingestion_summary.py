from app.broker.bridge import MT5CandleBatch
from datetime import datetime, timedelta, timezone

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



def test_single_batch_saves_are_recorded_in_the_ingestion_ledger(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry.sqlite3")

    assert store.save_candle_batch(batch()) == 1
    assert store.save_candle_batch(batch()) == 1

    summary = store.candle_ingestion_summary()
    assert summary["batch_count"] == 2
    assert summary["series_count"] == 1
    series = summary["series"][0]
    assert series["candles_received"] == 2
    assert series["unique_candles_stored"] == 1
    assert series["first_stored_candle_at"] == "2026-11-20T09:00:00+00:00"
    assert series["latest_stored_candle_at"] == "2026-11-20T09:00:00+00:00"


def test_ingestion_summary_reports_lifetime_totals_beyond_recent_receipt_window(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry.sqlite3")

    for _ in range(105):
        store.save_candle_batch(batch())

    summary = store.candle_ingestion_summary(limit=100)

    assert summary["batch_count"] == 105
    assert summary["recent_batch_count"] == 100
    assert summary["candles_received_total"] == 105
    assert len(summary["recent_batches"]) == 100
    assert summary["series_count"] == 1
    assert summary["series"][0]["batch_count"] == 105
    assert summary["series"][0]["candles_received"] == 105
    assert summary["series"][0]["unique_candles_stored"] == 1


def test_candle_rows_roll_back_when_ingestion_receipt_cannot_be_written(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry.sqlite3")
    with store._connect() as connection:
        connection.execute(
            """CREATE TRIGGER reject_candle_receipt
               BEFORE INSERT ON candle_ingestion_batches
               BEGIN
                   SELECT RAISE(ABORT, 'receipt write rejected');
               END"""
        )

    try:
        store.save_candle_batch(batch())
    except Exception as exc:
        assert "receipt write rejected" in str(exc)
    else:
        raise AssertionError("Expected receipt failure to abort the ingestion transaction")

    assert store.candle_history("EURUSDm", "M5") == []
    summary = store.candle_ingestion_summary()
    assert summary["batch_count"] == 0
    assert summary["series_count"] == 0



def test_ingestion_summary_classifies_upload_inactivity_with_injected_clock(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry.sqlite3")
    store.save_candle_batch(batch())

    first = store.candle_ingestion_summary(stale_after_seconds=900)
    series = first["series"][0]
    assert series["upload_freshness"] == "recent"
    assert first["freshness_status"] == "recent"
    assert first["stale_series_count"] == 0
    assert first["last_successful_upload_at"] == series["last_ingested_at"]
    assert first["last_successful_upload_age_seconds"] is not None

    ingested_at = datetime.fromisoformat(series["last_ingested_at"])
    aging = store.candle_ingestion_summary(
        stale_after_seconds=900,
        now=ingested_at + timedelta(seconds=600),
    )
    assert aging["series"][0]["upload_freshness"] == "aging"
    assert aging["aging_series_count"] == 1
    assert aging["stale_series_count"] == 0

    stale = store.candle_ingestion_summary(
        stale_after_seconds=900,
        now=ingested_at + timedelta(seconds=901),
    )
    assert stale["series"][0]["upload_freshness"] == "stale"
    assert stale["freshness_status"] == "stale"
    assert stale["stale_series_count"] == 1


def test_empty_ingestion_summary_reports_no_data_not_healthy(tmp_path):
    summary = TelemetryStore(tmp_path / "telemetry.sqlite3").candle_ingestion_summary()
    assert summary["freshness_status"] == "no_data"
    assert summary["last_successful_upload_at"] is None
    assert summary["last_successful_upload_age_seconds"] is None
    assert summary["stale_series_count"] == 0
