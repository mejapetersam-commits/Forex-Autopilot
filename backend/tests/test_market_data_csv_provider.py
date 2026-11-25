import pytest

from app.market_data.csv_provider import CSVMarketDataError, export_csv, import_csv


CSV = """timestamp,open,high,low,close,volume
2026-01-05T10:00:00Z,1.1000,1.1010,1.0990,1.1005,12
2026-01-05T10:05:00Z,1.1005,1.1020,1.1000,1.1015,15
"""


def test_csv_import_export_round_trip():
    series = import_csv(CSV, symbol="EURUSDm", timeframe="M5")
    assert series.symbol == "EURUSDM"
    assert len(series.bars) == 2
    exported = export_csv(series)
    restored = import_csv(exported, symbol="EURUSDm", timeframe="M5")
    assert [bar.close for bar in restored.bars] == [bar.close for bar in series.bars]


def test_csv_import_rejects_naive_timestamps_and_bad_ohlc():
    naive = CSV.replace("2026-01-05T10:00:00Z", "2026-01-05T10:00:00")
    with pytest.raises(CSVMarketDataError):
        import_csv(naive, symbol="EURUSDm", timeframe="M5")
    invalid = CSV.replace("1.1010,1.0990", "1.0900,1.0990")
    with pytest.raises(CSVMarketDataError):
        import_csv(invalid, symbol="EURUSDm", timeframe="M5")


def test_csv_import_enforces_row_limit_and_required_columns():
    with pytest.raises(CSVMarketDataError):
        import_csv(CSV, symbol="EURUSDm", timeframe="M5", maximum_rows=1)
    with pytest.raises(CSVMarketDataError):
        import_csv("timestamp,close\n2026-01-05T10:00:00Z,1.1", symbol="EURUSDm", timeframe="M5")
