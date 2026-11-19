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
- Authenticated demo broker-deal history ingestion, idempotent deal-ticket storage, partial-fill aggregation, full-fill confirmation, deterministic intent-tag recovery for uncertain/expired leases, and manual-review flags for broker identity, magic, symbol, side or volume discrepancies.
- Existing portfolio risk controls remain the source of truth for currency exposure, correlation, projected drawdown, open-position count and emergency halt.

## Still required before demo execution can be enabled

- Both MT5 Expert Advisors have been compiled locally in MetaEditor with 0 errors and 0 warnings. Recompile after the latest history/tagging changes; CI does not compile MQL5.
- Validate EA account-mode detection, symbol specifications, lot step, filling policy, stop/target placement and margin checks on an Exness demo account.
- Validate the new broker-history reconciliation against actual Exness demo deal records, including multiple partial fills, no-fill/pending orders, order comments, ticket mapping, disconnects and terminal restarts. Expired or uncertain commands remain quarantined; never blindly retry them.
- Complete broker-verified position/order state transitions, including pending/cancelled order history, close/reversal deals, and terminal position reconciliation.
- Broker-side protective-stop monitoring now flags managed positions missing SL/TP; automated repair/flatten escalation remains required.
- Daily P&L and realised/unrealised exposure sourced from broker records, not estimates.
- Broker-verified restart/disconnect recovery and end-to-end duplicate-event testing; backend lease quarantine and intent-tag lookup are implemented but not yet proven against live broker demo history.
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
