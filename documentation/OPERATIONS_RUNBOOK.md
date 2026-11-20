# FOREX AUTOPILOT operations runbook

## Local development

From the repository root:

```bash
cd backend
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
```

Run the API locally:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/dashboard`.

## Docker deployment

From the repository root, ensure the deployment environment contains a long random `FOREX_AUTOPILOT_BRIDGE_TOKEN` (at least 32 characters). Do not put it in source control or paste it into chat. Configure a separate random `FOREX_AUTOPILOT_ADMIN_TOKEN` (at least 32 characters) if the local dashboard pause and emergency-stop controls are to be administered.

```bash
docker compose config -q
docker compose up -d --build api telemetry-gateway telemetry-backup telemetry-health-monitor
docker compose ps
curl -fsS http://127.0.0.1:8000/health
docker compose logs --tail=100 api telemetry-gateway telemetry-backup telemetry-health-monitor
```

The API and gateway are bound to loopback addresses. Do not expose the API directly to the public internet. Keep the SQLite volume persistent and backed up.

## Research endpoints

Use the `X-Bridge-Token` header for authenticated endpoints:

- `/api/v1/mt5/specifications` (broker tick value, tick size, contract and volume constraints)
- `/api/v1/mt5/execution/state` (read-only open-position and protective-level snapshot)
- `POST /api/v1/mt5/execution/history` (authenticated demo broker-deal history ingestion with POSITION_IDENTIFIER links)
- `POST /api/v1/mt5/execution/orders` (authenticated pending/filled/cancelled/rejected/expired broker order history)
- Admin-only `POST /api/v1/admin/strategy/dispatch/{symbol}/{timeframe}` (turns a closed-candle strategy candidate into a deterministic risk-preflighted intent; optional queue request is still subject to all demo gates)
- Admin-only `GET /api/v1/monitoring/reconciliation` (compare unresolved intents with fresh matching terminal history)
- `/api/v1/monitoring/execution-state` (position-to-deal links and protective-stop alerts)
- `/api/v1/monitoring/execution-state` (snapshot freshness, daily-loss status and managed-position stop/target alerts)
- Admin-only `POST /api/v1/admin/execution/intents/preflight` (server-derived preflight; does not submit an order)
- Admin-only `POST /api/v1/admin/execution/intents/{intent_id}/queue` (revalidates current telemetry before queuing)
- Authenticated MT5 polling/result routes under `/api/v1/mt5/execution/commands/`
- `/api/v1/mt5/history/candles/{symbol}/{timeframe}`
- `/api/v1/market-analysis/{symbol}/{timeframe}`
- `/api/v1/strategy/signal/{symbol}/{timeframe}`
- `/api/v1/backtests/run/{symbol}/{timeframe}`
- `/api/v1/backtests/walk-forward/{symbol}/{timeframe}`
- `/api/v1/market-data/quality/{symbol}/{timeframe}`
- Local read-only `/api/v1/dashboard/events` (recent health journal and notification outbox state)
- Read-only `GET /api/v1/dashboard/portfolio` (fresh demo positions, gross/net currency exposure and estimated stop risk)

The local dashboard displays connection state, account telemetry, quotes, research signals, operational events, and read-only portfolio concentration/stop-risk estimates. Portfolio estimates require fresh account, position, quote and broker-specification telemetry; unsupported currency conversions or missing stops are flagged rather than guessed. Its pause/resume and emergency-stop controls require the separate admin token and write an audit trail. Clearing the pause or kill switch alone does not enable command delivery.

## Current safety posture

- `ForexAutopilotTelemetry.mq5` remains read-only and reports open positions every five seconds plus bounded demo deal and order-history snapshots every 60 seconds. It sends MT5 POSITION_IDENTIFIER and DEAL_POSITION_ID so the backend can link fills and exits to open positions. It does not submit, modify or close orders.
- `ForexAutopilotDemoExecution.mq5` is a separate demo-only adapter. The previous version compiled locally with 0 errors and 0 warnings; recompile the latest broker-tag changes before any demo pilot.
- The demo adapter's `InpEnableDemoExecution` defaults to `false` and refuses non-demo accounts.
- Backend `FOREX_AUTOPILOT_DEMO_EXECUTION_ENABLED` defaults to `false`; the execution symbol allowlist defaults to empty.
- Dispatch requires an admin-authenticated request for an existing preflight-approved ledger intent, explicit demo configuration, an allowlisted symbol, and cleared pause/kill-switch controls.
- Command delivery uses 60-second at-most-once leases and is bound to the latest fresh demo terminal identity. Expired leases move approved intents to `unknown`; broker-history reconciliation searches by broker order ticket or deterministic `FA:` intent tag. The terminal persists the full command ID marker across restarts. Missing history never becomes an inferred rejection or fill. Never blindly retry an order.
- Managed demo positions missing a valid stop-loss automatically activate both pause and the emergency kill switch. The guard never edits or closes broker positions; an operator must inspect broker state, apply a verified protective level manually, confirm the updated telemetry, and only then follow the controlled resume procedure.
- Never enable live execution based on a successful build or a profitable-looking in-sample backtest.


## Demo adapter preparation (not yet authorised for order flow)

The separate source file is `mt5/Experts/ForexAutopilotDemoExecution.mq5`. Compile it in MetaEditor before attaching it to a chart. Configure the HTTPS API base URL, the existing bridge token locally in MT5, a unique terminal ID containing only letters/numbers/hyphens/underscores, and the exact broker symbols. Keep `InpEnableDemoExecution=false`.

In MetaTrader, add the API host to **Tools → Options → Expert Advisors → Allow WebRequest for listed URL**. Do not paste tokens into source control or chat.

The EA enforces demo account mode, terminal trading permissions, the local symbol allowlist, a 0.01-lot hard ceiling, one open position maximum, broker volume step, stop distance, a free-margin buffer and a persistent command-attempt marker. The telemetry EA estimates daily loss from today's broker trade deals plus current floating PnL; if history cannot be read or ambiguous balance operations occur, it reports a fail-closed loss value. This is an operational guard, not an audited broker statement. Preflight also enforces a 0.25% estimated stop-risk ceiling, a 0.01-lot local cap, broker volume-step constraints, a 2-pip spread cap, one open position and a 1% daily-loss threshold by default. The adapter source has static CI checks, but these do not replace an actual MetaEditor compile or broker demo test.

Do not set `FOREX_AUTOPILOT_DEMO_EXECUTION_ENABLED=true`, clear the pause/kill switch, or set `InpEnableDemoExecution=true` until the EA compiles cleanly and the dedicated demo validation plan has been completed. No live-account use is supported.

## Before a demo execution pilot

1. Verify all symbol specifications from the connected broker: digits, point, tick size, tick value, contract size, volume minimum/maximum/step, stop and freeze levels, allowed filling modes, and trading sessions.
2. Verify account currency and pip/tick-value conversion for each symbol.
3. Confirm quote, account and position telemetry freshness, correct terminal identity/server, and position-to-deal links.
4. Exercise emergency halt, stale-data denial, spread denial, margin denial, duplicate-intent denial, terminal restart quarantine and automatic protective-stop kill-switch activation.
5. Validate the broker adapter on a dedicated demo account, including order acknowledgement, partial fills, re-quotes, rejects, disconnects, restarts and reconciliation.
6. Run a continuous forward-demo trial across different market conditions and reconcile every intended order against broker-side history.
7. Keep a human-operated emergency stop available.

Live trading remains disabled until those controls are implemented, independently tested and explicitly deployed.


## Scheduled telemetry backups

The telemetry-backup Compose service runs independently of the API and
gateway. Its SQLite source connection is read-only; the volume mount also allows SQLite WAL shared-memory coordination. It takes a verified online SQLite snapshot at startup, then follows
the configured interval and retention window. Defaults are 24 hours and 30
days. The snapshots live in the separate telemetry_backups Docker volume.

```bash
docker compose logs --tail=100 telemetry-backup
docker compose exec telemetry-backup python -m app.operations.backup verify --backup /var/backups/forex-autopilot/telemetry-YYYYMMDDTHHMMSSZ.sqlite3
```

The named volume protects against ordinary application/container replacement,
but it is not a substitute for encrypted off-device copies. Include this volume
in the host's encrypted backup and disaster-recovery policy. Restore remains a
controlled offline procedure: stop the API and backup service first, preserve
the current database, verify the selected snapshot, then restore and validate
telemetry before restarting.


## Broker position reconciliation

The admin-only `GET /api/v1/monitoring/positions/reconciliation` endpoint
compares open positions carrying the configured execution magic number against
known durable intent tags. A managed position without a matching deterministic
`FA:` intent tag is reported as an orphan and recorded as a critical
operational event. Other magic numbers are excluded.

This is a read-only audit. It does not close, modify or hedge positions. A
matching tag is correlation evidence, not proof that all broker-side position
details are correct; operators should still compare ticket, symbol, side,
volume, stop and target with broker history. The endpoint requires a fresh demo
terminal snapshot and admin authentication.

Backtest results also expose a per-candle mark-to-market equity/drawdown
approximation. Review its documented OHLC, spread, slippage and commission
limitations before using it to compare strategies.


## Read-only position lifecycle monitoring

The admin-only `GET /api/v1/monitoring/positions/lifecycle` endpoint compares
the two most recent execution snapshots from the same demo terminal and server.
It reports newly observed positions, volume reductions, ticket replacements,
stop-loss/take-profit changes and positions that disappear from the snapshot.

A missing position is **not** automatically labelled closed. The endpoint
requires linked broker deal evidence showing entry volume and at least the same
volume closed, and refuses to treat MT5 reversal (`inout`) deals as unambiguous
full-close evidence. Otherwise it reports
`position_disappearance_unconfirmed` for operator review. This is a read-only
observation layer, not a broker instruction or accounting statement.

Lifecycle events are recorded in the operational event journal using the
snapshot timestamp for idempotency. The endpoint requires a fresh demo
snapshot and admin authentication. It never closes, modifies or opens a
position; trading remains disabled.


## Aggregate portfolio stop-risk dispatch gate

Immediately before an approved intent is queued, the API rebuilds the portfolio estimate from current MT5 execution state, account equity, quotes and symbol specifications. Dispatch is blocked unless the portfolio is healthy and complete, every open position has a valid protective stop with a supported fresh conversion, and aggregate estimated stop risk is at or below `FOREX_AUTOPILOT_MAX_PORTFOLIO_STOP_RISK_PCT` (default `0.50` percent of account equity). Unknown or stale risk is a hard denial, never treated as zero. The gate is read-only and does not change positions. This estimate uses current quotes and broker tick values; gaps, slippage, commissions, swaps and execution failures can increase realized losses. Trading remains disabled by default and live execution is prohibited.


## Broker-reported realized P&L and trade attribution

The read-only `GET /api/v1/dashboard/trade-attribution` endpoint reports
closed demo position cycles reconstructed from broker deal history. The MT5
telemetry EA sends each deal's `DEAL_PROFIT`, `DEAL_COMMISSION`,
`DEAL_SWAP` and `DEAL_FEE`; these values are retained in account-currency
units without conversion.

A cycle is keyed by terminal identity plus MT5 `POSITION_IDENTIFIER`.
Partial entry fills accumulate into the same cycle. Partial exits reduce the
remaining volume and do not complete a cycle until the full observed exposure
is closed. An `INOUT` reversal closes the prior direction and starts a new
cycle for the residual reversed volume. Unmatched exits, missing position IDs,
over-closes and inconsistent reversal volumes are surfaced as incomplete
evidence, not silently repaired.

Only closed cycles with all four cash fields present contribute to net realized
P&L, win rate, profit factor, expectancy, average win/loss and realized
drawdown. Open positions and cycles with legacy missing cash fields are
excluded. The dashboard reports the number of missing cash fields, unmatched
deals, ambiguous over-closes, open positions and incomplete cycles. Profit
factor is left unavailable when there is no realized gross loss rather than
presenting an infinite ratio.

The latest account snapshot supplies the displayed account currency. Verify
that snapshot belongs to the same account/server as the deal history before
using figures for formal accounting. Magic number and symbol are grouping
keys only; they do not independently prove strategy attribution. This
dashboard is not an audited broker statement and does not calculate daily
loss or unrealized P&L. Reconcile results against the Exness demo statement
before using them for strategy decisions. No trading action is available from
this endpoint.
