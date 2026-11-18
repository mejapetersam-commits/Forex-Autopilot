# Architecture v1

## Components
1. MT5 Expert Advisor (MQL5): local signal evaluation, execution and hard risk checks.
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
