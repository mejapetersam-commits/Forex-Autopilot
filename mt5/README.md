# FOREX AUTOPILOT MT5 read-only Expert Advisor

## Purpose

This Expert Advisor (EA) sends MT5 connection status, a limited account snapshot and selected bid/ask quotes to the FOREX AUTOPILOT FastAPI service. It is intentionally telemetry-only.

**It cannot open, modify or close trades.** No trade execution functions or remote command polling are included.

## Current prerequisites

- A Windows installation of MetaTrader 5 connected to the Exness demo account.
- The FOREX AUTOPILOT API deployed at an HTTPS address reachable from that Windows terminal.
- A strong unique bridge token configured as the API environment variable `FOREX_AUTOPILOT_BRIDGE_TOKEN`.
- The same token entered locally in the EA input parameters. Never put a real token in this repository, source code, screenshots or chat.
- In MT5, add the exact HTTPS API origin to Tools → Options → Expert Advisors → Allow WebRequest for listed URL.

The API host must use valid HTTPS. Do not expose an unencrypted HTTP endpoint to the public internet.

## Install

1. In MT5, select File → Open Data Folder.
2. Open MQL5 → Experts.
3. Copy `ForexAutopilotTelemetry.mq5` into that folder.
4. Open MetaEditor, compile the file, and return to MT5.
5. Attach the EA to a chart in the demo account.
6. In EA inputs, set the API base URL, bridge token, symbols and heartbeat interval.
7. Enable algorithmic trading only if MT5 requires it to run an EA; this EA has no trade execution code. Do not enable any other trading robot.
8. Add the API origin to the WebRequest allowlist as described above.

## Inputs

- `InpApiBaseUrl`: HTTPS origin of the deployed API, without a trailing slash.
- `InpBridgeToken`: unique secret of at least 32 characters; enter locally, never commit.
- `InpSymbols`: comma-separated symbols exactly as named by the broker (for example, EURUSD,GBPUSD). Broker suffixes may be required.
- `InpHeartbeatSeconds`: telemetry interval; minimum 5 seconds.
- `InpHttpTimeoutMs`: request timeout; minimum 1000 ms.

## Data sent

- Heartbeat: server, terminal connectivity and UTC observation time.
- Account: account currency, balance, equity, margin, free margin, leverage, server and UTC observation time. No account login or password is sent.
- Quote: symbol, bid, ask and UTC observation time.

The quote timestamp is the time the EA observed the tick, expressed in UTC. It is not represented as the broker's raw tick timestamp because MT5 server-time offset semantics must be configured explicitly before using broker timestamps for historical analysis.

## Important limitations

- The EA has not been compiled against MetaEditor in this repository's CI environment. Compile and test it on the Windows MT5 terminal before use.
- This code does not establish a connection by itself; the API must first be deployed and secured.
- The backend persists heartbeat, account and quote observations in SQLite. The latest-value and bounded quote-history read endpoints are protected by the same bridge token. The deployment uses a persistent Docker volume; backups and retention monitoring must still be configured.
- Do not use a live account. This stage is demo-only.


## API deployment preparation

The repository includes a container build at `backend/Dockerfile` and a hardened single-service Compose deployment at the repository root. The API binds to loopback port 8000 only; place it behind a reverse proxy or managed ingress that terminates valid HTTPS before allowing the MT5 terminal to connect. Do not expose port 8000 directly to the public internet.

Set `FOREX_AUTOPILOT_BRIDGE_TOKEN` in the deployment environment to a cryptographically random secret of at least 32 characters. Do not store it in Git, source code, screenshots or chat. Compose persists SQLite data in the named `telemetry_data` volume and runs the API as a non-root user. Back up that volume and verify restore before relying on the telemetry history.

The API container health check verifies process readiness only; it does not verify Exness connectivity or MT5 telemetry. The EA must be compiled in MetaEditor and tested against a deployed HTTPS endpoint before this integration is considered operational.


The authenticated monitoring endpoint `GET /api/v1/mt5/status` summarizes heartbeat and quote freshness. Its default stale threshold is 60 seconds and can be changed with `FOREX_AUTOPILOT_TELEMETRY_STALE_AFTER_SECONDS`. This is a monitoring aid, not proof that the broker is healthy and not a permission to trade.
