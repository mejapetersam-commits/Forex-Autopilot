# Release gates

## Implemented in the current development branch

- Authenticated read-only MT5 telemetry bridge, bulk candle ingestion and broker symbol-specification telemetry.
- Persistent SQLite candle, quote, account and heartbeat storage.
- Closed-candle EMA20/EMA50 + RSI14 + MACD signal research.
- ATR-based candidate stop and target levels.
- OHLC backtesting with next-open entries, spread, slippage, commission, risk sizing, gap-aware stops and conservative same-bar conflict handling.
- Daily-loss and maximum-drawdown entry halts in historical simulations.
- Bounded parameter grid search with chronological walk-forward validation.
- Candle integrity, timestamp ordering and gap assessment.
- Local dashboard research feed and severity-ranked operational health alerts.
- Fail-closed execution preflight, persistent operator-control enforcement and idempotent order-intent ledger.
- Separate MT5 demo execution EA source with hard demo-account check, explicit default-off switch, local symbol allowlist, 0.01-lot ceiling, one-position cap, stop/target-side and broker stop-distance checks, margin buffer and terminal-side duplicate-attempt marker.
- Authenticated demo command polling/result endpoints, admin-gated dispatch of preflight-approved intents, persistent 60-second at-most-once leases and uncertain-result quarantine; execution remains disabled by default.
- Existing portfolio risk controls remain the source of truth for currency exposure, correlation, projected drawdown, open-position count and emergency halt.

## Still required before demo execution can be enabled

- Compile the separate `ForexAutopilotDemoExecution.mq5` in MetaEditor and resolve any compiler warnings/errors; CI checks its source contract but does not compile MQL5.
- Validate EA account-mode detection, symbol specifications, lot step, filling policy, stop/target placement and margin checks on an Exness demo account.
- Build broker-history reconciliation for orders, deals and positions, including restart recovery and partial fills. Expired or uncertain commands must be reconciled manually/automatically before any further action; never blindly retry them.
- Complete position/order state machine covering pending, acknowledged, partially filled, filled, rejected, cancelled and unknown states.
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
