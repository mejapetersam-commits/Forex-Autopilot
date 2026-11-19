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
docker compose up -d --build api telemetry-gateway
docker compose ps
curl -fsS http://127.0.0.1:8000/health
docker compose logs --tail=100 api telemetry-gateway
```

The API and gateway are bound to loopback addresses. Do not expose the API directly to the public internet. Keep the SQLite volume persistent and backed up.

## Research endpoints

Use the `X-Bridge-Token` header for authenticated endpoints:

- `/api/v1/mt5/specifications` (broker tick value, tick size, contract and volume constraints)
- `/api/v1/mt5/history/candles/{symbol}/{timeframe}`
- `/api/v1/market-analysis/{symbol}/{timeframe}`
- `/api/v1/strategy/signal/{symbol}/{timeframe}`
- `/api/v1/backtests/run/{symbol}/{timeframe}`
- `/api/v1/backtests/walk-forward/{symbol}/{timeframe}`
- `/api/v1/market-data/quality/{symbol}/{timeframe}`

The local dashboard displays connection state, account telemetry, quotes, research signals and candle-quality summaries. Its pause/resume and emergency-stop controls require the separate admin token and write an audit trail. Clearing the pause or kill switch does not enable trading; trading remains hard-disabled in this build.

## Current safety posture

- MT5 Expert Advisor is a read-only telemetry bridge.
- Backend trading configuration defaults to disabled.
- Execution preflight is a fail-closed validation component only.
- There is no active broker order-submission adapter in this release.
- Never enable live execution based on a successful build or a profitable-looking in-sample backtest.

## Before a demo execution pilot

1. Verify all symbol specifications from the connected broker: digits, point, tick size, tick value, contract size, volume minimum/maximum/step, stop and freeze levels, allowed filling modes, and trading sessions.
2. Verify account currency and pip/tick-value conversion for each symbol.
3. Confirm quote and account telemetry freshness and correct server/account environment.
4. Exercise emergency halt, stale-data denial, spread denial, margin denial, duplicate-intent denial and protective-stop rejection.
5. Validate the broker adapter on a dedicated demo account, including order acknowledgement, partial fills, re-quotes, rejects, disconnects, restarts and reconciliation.
6. Run a continuous forward-demo trial across different market conditions and reconcile every intended order against broker-side history.
7. Keep a human-operated emergency stop available.

Live trading remains disabled until those controls are implemented, independently tested and explicitly deployed.
