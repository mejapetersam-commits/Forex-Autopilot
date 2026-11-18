# Architecture v1

## Components
1. MT5 Expert Advisor (MQL5): eventual local signal evaluation, execution and hard risk checks; the current EA is telemetry-only.
2. Python research layer: historical data preparation, backtesting and statistical evaluation.
3. FastAPI: configuration and telemetry interface; never the sole authority for trade safety.
4. PostgreSQL/Supabase: configurations, trades, events and performance snapshots.
5. React/TypeScript: monitoring and controlled configuration interface.
6. Telegram: operational notifications.

## Fail-safe principles
- Trading disabled by default.
- EA must fail closed if configuration is missing, stale, invalid or inconsistent.
- Local risk limits cannot be relaxed by remote commands.
- Dashboard/API outage must not disable local stop-loss or risk protections.
- All configuration changes are versioned and audited.
- Secrets are kept outside source control.

## Deployment boundary
The Mac is the development workstation. A Windows MT5 environment is the target for repeatable testing and eventual VPS deployment. Do not deploy a live account in this phase.

## Market-data foundation

The backend market-data package defines validated completed OHLC candles, a normalized instrument/timeframe series, and a provider protocol. A broker or vendor adapter must implement the provider contract; no external feed is connected yet.

Historical return calculations use consecutive candle closes. Correlation calculations require identical candle timestamps and matching timeframes, enforce a configurable minimum observation count, and reject stale or future-dated data. The current implementation deliberately does not fill missing candles, interpolate prices, or silently align partial overlaps.

The provider is responsible for returning completed candles in chronological order. Production adapters must additionally document their source, timezone semantics, candle completion rules, rate limits, outage behaviour and licensing. Correlation checks remain disabled until a real provider and integration tests are in place.

## MT5 bridge foundation (read-only phase)

The FastAPI service now exposes authenticated, read-only endpoints for MT5 heartbeat, account telemetry and individual quotes:

- `POST /api/v1/mt5/heartbeat`
- `POST /api/v1/mt5/account`
- `POST /api/v1/mt5/quote`

Requests require the `X-Bridge-Token` header. The backend reads the expected token from `FOREX_AUTOPILOT_BRIDGE_TOKEN`; it returns a service-unavailable response when the secret is not configured and rejects missing or incorrect tokens. The secret must be generated and stored outside source control.

The telemetry models intentionally exclude account login numbers, passwords and broker credentials. Timestamps must be timezone-aware, prices and account amounts must be finite, and quote spreads must be valid. These endpoints validate and persist incoming telemetry in the SQLite store described below; they do not establish a live broker connection.

The bridge is strictly read-only: no order-submission endpoint or remote trade command exists, and system status continues to report trading disabled. Before a VPS is exposed to any network, deploy behind HTTPS, restrict inbound access, configure a strong unique secret, and apply host firewall rules. The next implementation step is an MT5 Expert Advisor that sends heartbeat, account and quote telemetry to this API using MT5's explicitly allowed WebRequest URL list. Execution remains out of scope until separately reviewed and explicitly approved.

## MT5 Expert Advisor source

The initial read-only EA source is at `mt5/Experts/ForexAutopilotTelemetry.mq5`, with installation and configuration guidance in `mt5/README.md`. It reports terminal connectivity, account telemetry and configured symbol quotes to the authenticated API. It contains no trade execution functions. The EA must be compiled and exercised in a Windows MT5 terminal; the Python CI workflow does not compile MQL5. Its API URL and bridge token are runtime inputs and must never be committed. Deployment and end-to-end verification remain outstanding.


## MT5 telemetry persistence

Read-only MT5 telemetry is persisted in SQLite by `app.market_data.telemetry_store.TelemetryStore`. The database path is configured with `FOREX_AUTOPILOT_TELEMETRY_DB` and defaults to `data/telemetry.sqlite3`. Deployment must mount this path on persistent, access-restricted storage and include it in backups. SQLite WAL mode is enabled for reliable local reads and writes.

The authenticated write endpoints store heartbeat observations, account snapshots and quote observations. Protected read endpoints expose the latest heartbeat, latest account snapshot, latest quote per symbol, and bounded quote history (maximum 1,000 rows). Read routes require the same `X-Bridge-Token` authentication as writes. Account login numbers and passwords are not part of the accepted models or stored records.

This is an initial single-instance persistence layer for demo telemetry. It is not a substitute for a managed production database for multi-instance/high-volume deployment. Retention, backup/restore drills, monitoring and a production database migration must be addressed before live use. The service continues to report execution disabled; no trading endpoints are present.
