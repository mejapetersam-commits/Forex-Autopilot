# FOREX AUTOPILOT — MetaTrader 5 integration

This directory contains two deliberately separate Expert Advisors. Keep their roles distinct:

| Expert Advisor | Role | Trading capability |
|---|---|---|
| `ForexAutopilotTelemetry.mq5` | Market, account, position and broker-history telemetry | Read-only; cannot submit, modify or close orders |
| `ForexAutopilotDemoExecution.mq5` | Receives and processes approved execution commands | Demo account only; explicit input defaults OFF |

The telemetry EA is the normal integration component. The execution EA is a separate, disabled-by-default adapter and is not required for research, candle ingestion or dashboard monitoring.

## Telemetry EA

### What it sends

- Terminal heartbeat and broker server.
- Account currency, balance, equity, margin, free margin and leverage.
- Bid/ask quotes for configured symbols when a new tick is observed.
- Broker symbol specifications: digits, point, tick size/value, contract size, volume limits/step, stop/freeze levels and currency metadata.
- Open-position snapshots, including ticket, stable position identifier, symbol, side, volume, open price, stop, target, magic and comment.
- Bounded demo deal history, including deal/order/position identifiers, volume, price, magic, comment, profit, commission, swap, fee and broker event time.
- Broker order history, including pending, placed, partial, filled, cancelled, rejected and expired states.
- Bulk closed-candle history for M5, M15, H1 and H4 across configured symbols.

### Default collection settings

- Candle bootstrap target: 500 closed bars per symbol/timeframe group.
- Candle refresh: 60 seconds.
- Execution position state: every 5 seconds.
- Deal and order history refresh: every 60 seconds.
- Broker-history lookback: 2 days.
- Heartbeat/account refresh: every 15 seconds.
- Symbol specifications refresh: every 5 minutes.

The history upload is bounded by the configured lookback and execution magic number. A successful HTTP response does not prove that matching deals were found; check the EA's reported included-deal/order counts and compare with the broker's actual history. Manual trades with a different magic number are not necessarily included.

### Install

1. In MT5, choose **File → Open Data Folder**.
2. Open **MQL5 → Experts**.
3. Copy `ForexAutopilotTelemetry.mq5` into that folder.
4. Open MetaEditor and compile the file.
5. Return to MT5 and attach the EA to a chart on the intended demo terminal.
6. Set the HTTPS API base URL, bridge token, exact broker symbols and terminal ID in the EA inputs.
7. Add the exact HTTPS API origin under **Tools → Options → Expert Advisors → Allow WebRequest for listed URL**.
8. Confirm heartbeat, quotes, specifications, candle groups, position state and broker-history upload in the backend/dashboard.

The EA may require MT5's global Algo Trading setting to be enabled to run an Expert Advisor. The telemetry EA itself contains no order-execution functions. Do not attach unrelated trading robots.

### Inputs

- `InpApiBaseUrl`: HTTPS API origin, without a trailing slash.
- `InpBridgeToken`: unique secret of at least 32 characters; configure locally only.
- `InpSymbols`: comma-separated exact broker symbols (defaults are EURUSDm and GBPUSDm).
- `InpTerminalId`: stable identifier shared with the separate execution adapter.
- `InpExecutionStateSeconds`: position snapshot interval.
- `InpHeartbeatSeconds`: heartbeat/account interval.
- `InpHttpTimeoutMs`: HTTP timeout.
- `InpCandleBootstrapBars`: initial closed bars per symbol/timeframe (20–500).
- `InpCandleRefreshSeconds`: candle refresh interval.
- `InpHistoryRefreshSeconds`: broker history refresh interval.
- `InpHistoryLookbackDays`: broker history lookback (1–7 days).
- `InpExecutionMagicNumber`: magic number used to select managed execution history.

### Safety and limitations

- The telemetry EA is read-only. It does not poll execution commands and does not call order submission, modification or close functions.
- The EA requires HTTPS and a bridge token of at least 32 characters.
- The telemetry EA's daily-loss figure is an operational fail-closed estimate, not an audited broker statement.
- The backend health check confirms API process readiness, not broker connectivity or data completeness.
- Static Python contract tests do not compile MQL5. Compile the latest source in MetaEditor and validate against the broker demo terminal.
- Do not use a live account.

## Demo execution EA — separate and default-off

`ForexAutopilotDemoExecution.mq5` is a separate adapter. It is not the telemetry EA and should not replace it.

Its `InpEnableDemoExecution` input defaults to `false`; it refuses non-demo accounts and applies local symbol, volume, position, stop/target, margin and terminal-permission checks. Backend dispatch is independently disabled by default and also requires approved intents, fresh telemetry, an explicit symbol allowlist and cleared operator controls.

For the current development and validation phase:

- Keep `InpEnableDemoExecution=false`.
- Keep backend `FOREX_AUTOPILOT_DEMO_EXECUTION_ENABLED=false`.
- Keep the backend execution symbol allowlist empty.
- Do not clear the pause/kill switch to test order flow.
- Never retry an uncertain broker command blindly; reconcile it against broker order/deal history.

No demo execution pilot is authorised by a successful compile or passing backend tests alone.

## Credentials and network

Use a unique random bridge token of at least 32 characters in the deployment environment and enter the same value locally in MT5. Never commit credentials, screenshots containing tokens, account identifiers or `.env` files. Do not paste secrets into chat.

The API should remain bound to loopback behind the restricted HTTPS telemetry gateway. Do not expose the API/admin surface directly to the public internet.
