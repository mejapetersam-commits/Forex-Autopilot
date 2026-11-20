# FOREX AUTOPILOT

A demo-first MT5 market-data, research, risk-management and execution platform.

## Current safety posture

- The telemetry Expert Advisor is read-only.
- The separate demo execution Expert Advisor is default-off and refuses non-demo accounts.
- Backend demo dispatch is disabled by default and requires an explicit symbol allowlist, fresh broker telemetry, preflight approval, and inactive pause/kill-switch controls.
- Live trading is not enabled. Strategy rules remain research hypotheses until validated through out-of-sample and sustained forward-demo testing.
- Never enable execution merely because the software compiles or a backtest looks profitable.

## Architecture

- `backend/app/market_data/`: MT5 telemetry validation, candle quality and persistent SQLite storage.
- `backend/app/strategy/`: closed-candle EMA, RSI and MACD candidate signal generation.
- `backend/app/backtesting/`: next-candle-open OHLC simulation, transaction costs and walk-forward optimisation.
- `backend/app/risk/` and `backend/app/portfolio/`: position sizing, currency exposure, correlation and portfolio risk controls.
- `backend/app/execution/`: fail-closed preflight, intent ledger, audit trail, at-most-once command queue, partial-fill reconciliation and expired-lease recovery.
- `backend/app/monitoring/`: telemetry freshness, connectivity and operational health checks.
- `backend/app/dashboard.html`: local read-only dashboard.
- `mt5/Experts/ForexAutopilotTelemetry.mq5`: read-only MT5 telemetry bridge, including demo broker deal-history upload.
- `mt5/Experts/ForexAutopilotDemoExecution.mq5`: separate demo-only execution adapter; disabled by default.
- `deploy/telemetry-gateway/` and `docker-compose.yml`: loopback-bound API, restricted telemetry gateway, periodic health-event monitor and verified backup/retention worker.
- `documentation/`: operations, backtesting, architecture and release gates.

## Local setup (macOS)

1. Install Xcode Command Line Tools: `xcode-select --install`.
2. Install Homebrew, then run `brew install python git`.
3. Create the backend environment:
   ```bash
   cd backend
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
4. Configure local secrets from `backend/.env.example`. Never commit the resulting `.env` file.
5. Start the API locally with `uvicorn app.main:app --reload`, or use the repository's Docker Compose deployment from the project root.

## Verification

Run the backend suite from `backend/`:

```bash
pytest -q
```

Compile both MQL5 Expert Advisors in MetaEditor. CI can test source contracts and backend behavior, but does not replace MetaEditor compilation or broker-demo integration tests.

## Release discipline

Before any demo execution is enabled, complete broker-history reconciliation, partial-fill and restart recovery, protective-stop verification, terminal disconnect tests, and sustained Exness demo validation. Keep the public telemetry gateway restricted to its explicitly allowed telemetry routes; do not expose admin or execution command routes through the public tunnel.

For repeatable 24/5 operation, evaluate a dedicated Windows VPS only after the demo prototype and recovery controls have passed validation.

## Never commit

Broker passwords, investor passwords, API keys, bridge/admin tokens, `.env` files, account numbers, private keys, or personal account identifiers.
