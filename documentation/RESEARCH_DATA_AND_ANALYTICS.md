# Research data and analytics architecture

## Historical dataset interchange

`app.market_data.csv_provider` provides strict, offline CSV import/export for the canonical `MarketDataSeries` model. Imports require timezone-aware ISO-8601 timestamps and OHLCV columns, enforce a configurable row ceiling, and delegate OHLC ordering and value validation to the shared Pydantic models. Import/export is deliberately separate from broker telemetry storage: external files are not silently merged into live MT5 observations.

Canonical CSV columns:

`timestamp,open,high,low,close,volume`

All exported timestamps are UTC ISO-8601 values. Preserve original broker/source, timezone, symbol mapping and data licensing information alongside datasets when storing research files. Never treat imported candles as current quotes.

## Strategy registry

`app.strategy.registry` provides a stable identifier and metadata for each research strategy. Strategy registration does not grant execution authority. Unknown identifiers fail explicitly.

## Backtest analytics

`app.backtesting.analytics` derives trade-distribution and streak diagnostics from completed backtest output. It rejects non-finite PnL/equity inputs. These statistics supplement, rather than replace, walk-forward validation and cost-aware backtesting.

## Safety boundary

All three modules are research-only. They do not connect to MT5, create execution intents, alter runtime controls or enable trading. Imported datasets and simulated returns are not guarantees of future performance.
