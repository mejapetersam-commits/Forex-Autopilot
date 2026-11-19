"""Strict CSV import/export helpers for offline historical market datasets."""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Iterable

from app.market_data.models import MarketDataSeries, PriceBar


class CSVMarketDataError(ValueError):
    """Raised when a historical CSV dataset is malformed or unsafe."""


REQUIRED_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")


def import_csv(
    content: str,
    *,
    symbol: str,
    timeframe: str,
    maximum_rows: int = 250_000,
) -> MarketDataSeries:
    if not isinstance(content, str) or not content.strip():
        raise CSVMarketDataError("CSV content is empty.")
    if maximum_rows < 1:
        raise CSVMarketDataError("maximum_rows must be positive.")
    reader = csv.DictReader(io.StringIO(content))
    if reader.fieldnames is None:
        raise CSVMarketDataError("CSV header is missing.")
    normalized = [name.strip().lower() for name in reader.fieldnames]
    if len(normalized) != len(set(normalized)):
        raise CSVMarketDataError("CSV contains duplicate column names.")
    if any(name not in normalized for name in REQUIRED_COLUMNS):
        raise CSVMarketDataError(
            "CSV must contain timestamp, open, high, low, close and volume columns."
        )

    bars: list[PriceBar] = []
    for row_number, row in enumerate(reader, start=2):
        if len(bars) >= maximum_rows:
            raise CSVMarketDataError("CSV exceeds the configured row limit.")
        try:
            values = {str(k).strip().lower(): v for k, v in row.items() if k is not None}
            raw_timestamp = (values.get("timestamp") or "").strip()
            timestamp = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError("timestamp must include a timezone")
            bars.append(PriceBar(
                timestamp=timestamp.astimezone(timezone.utc),
                open=float(values["open"]),
                high=float(values["high"]),
                low=float(values["low"]),
                close=float(values["close"]),
                volume=float(values["volume"]),
            ))
        except Exception as exc:
            raise CSVMarketDataError(f"Invalid CSV row {row_number}: {exc}") from exc

    if not bars:
        raise CSVMarketDataError("CSV contains no data rows.")
    try:
        return MarketDataSeries(symbol=symbol, timeframe=timeframe, bars=bars)
    except Exception as exc:
        raise CSVMarketDataError(f"Dataset validation failed: {exc}") from exc


def export_csv(series: MarketDataSeries) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(REQUIRED_COLUMNS)
    for bar in series.bars:
        writer.writerow([
            bar.timestamp.astimezone(timezone.utc).isoformat(),
            format(bar.open, ".12g"),
            format(bar.high, ".12g"),
            format(bar.low, ".12g"),
            format(bar.close, ".12g"),
            format(bar.volume, ".12g"),
        ])
    return output.getvalue()
