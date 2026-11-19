# Release gates

## Implemented in the current development branch

- Authenticated read-only MT5 telemetry bridge and bulk candle ingestion.
- Persistent SQLite candle, quote, account and heartbeat storage.
- Closed-candle EMA20/EMA50 + RSI14 + MACD signal research.
- ATR-based candidate stop and target levels.
- OHLC backtesting with next-open entries, spread, slippage, commission, risk sizing, gap-aware stops and conservative same-bar conflict handling.
- Daily-loss and maximum-drawdown entry halts in historical simulations.
- Bounded parameter grid search with chronological walk-forward validation.
- Candle integrity, timestamp ordering and gap assessment.
- Local dashboard research feed.
- Fail-closed execution preflight checks and tests.
- Existing portfolio risk controls remain the source of truth for currency exposure, correlation, projected drawdown, open-position count and emergency halt.

## Still required before any demo order execution

- A broker-specific MT5 execution adapter; current EA is deliberately read-only.
- Live adapter verification against the now-ingested broker symbol specifications and account-currency tick values.
- Durable idempotent order-intent ledger and append-only order/control audit trail are implemented; broker-side reconciliation loop remains required.
- Position/order state machine covering pending, acknowledged, partially filled, filled, rejected, cancelled and unknown states.
- Broker-side protective stop verification and repair/flatten escalation.
- Daily P&L and realised/unrealised exposure sourced from broker records, not estimates.
- Restart recovery, duplicate event handling and disconnect recovery.
- Authenticated local dashboard pause/resume and emergency-stop controls with a separate admin token and audit history are implemented; multi-user role separation remains required.
- Operational alert delivery and an independently reachable kill switch.
- Dedicated demo-account integration tests and a sustained forward-demo evaluation.

## Live release gates

Live execution must remain disabled until the demo gates pass and all of the following are signed off:

- Independent review of broker adapter and secret handling.
- Reproducible out-of-sample results across multiple regimes and symbols after broker costs.
- Forward-demo performance and risk limits within policy.
- No unresolved critical execution, reconciliation or kill-switch defects.
- Verified maximum loss, margin, exposure and position limits.
- Tested backup, restore, monitoring and incident response.
- Explicit deployment-time enablement with a tested rollback path.

A code-complete system is not necessarily a safe or profitable trading system. The platform must fail closed whenever data, account state, broker state or risk state is uncertain.
