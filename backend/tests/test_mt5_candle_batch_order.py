import pytest
from pydantic import ValidationError

from app.broker.bridge import MT5CandleBatch


def candle(opened_at: str) -> dict:
    return {
        "opened_at": opened_at,
        "open": 1.1000,
        "high": 1.1020,
        "low": 1.0990,
        "close": 1.1010,
        "tick_volume": 100,
    }


def test_candle_batch_accepts_strictly_chronological_history():
    batch = MT5CandleBatch(
        symbol="EURUSDm",
        timeframe="M5",
        candles=[
            candle("2026-11-20T09:00:00Z"),
            candle("2026-11-20T09:05:00Z"),
            candle("2026-11-20T09:10:00Z"),
        ],
    )
    assert len(batch.candles) == 3
    assert batch.symbol == "EURUSDM"


@pytest.mark.parametrize(
    "timestamps",
    [
        ["2026-11-20T09:00:00Z", "2026-11-20T09:00:00Z"],
        ["2026-11-20T09:05:00Z", "2026-11-20T09:00:00Z"],
    ],
)
def test_candle_batch_rejects_duplicate_or_out_of_order_history(timestamps):
    with pytest.raises(ValidationError, match="strictly increasing"):
        MT5CandleBatch(
            symbol="EURUSDm",
            timeframe="M5",
            candles=[candle(value) for value in timestamps],
        )
