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
- The backend currently validates and acknowledges telemetry but does not persist it.
- Do not use a live account. This stage is demo-only.
