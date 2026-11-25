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
- Authenticated demo broker deal and order-history ingestion, idempotent deal/order ticket storage, partial-fill aggregation, full-fill confirmation, pending/cancelled/rejected/expired order-state reconciliation, deterministic intent-tag recovery for uncertain/expired leases, and manual-review flags for conflicting or incomplete broker evidence.
- Stable MT5 POSITION_IDENTIFIER and DEAL_POSITION_ID linkage, so open positions can be joined to their entry/exit deals after partial fills and terminal restarts.
- Strategy-candidate-to-execution-intent integration: closed-candle research signals become deterministic, idempotent intents and pass the same live broker/risk preflight before they can be queued. Queueing remains separately gated and opt-in.
- Protective-stop guard: missing or wrong-side stops on managed demo positions automatically activate pause + emergency kill switch; it never silently modifies or closes broker positions.
- Terminal restart protection uses the complete persistent command ID as an MT5 Global Variable marker; expired leases are quarantined to unknown and can only be recovered from authenticated broker order/deal history.
- Existing portfolio risk controls remain the source of truth for currency exposure, correlation, projected drawdown, open-position count and emergency halt.


- On-demand strategy qualification with minimum out-of-sample sample size, two valid chronological folds, positive mean out-of-sample return, minimum mean profit factor, maximum drawdown and healthy candle-quality gates. "Eligible for demo observation" is a research label only; it is not strategy approval or execution authorization.
- Read-only Demo Observation Centre summarises broker-confirmed demo deal/order counts, symbol/magic groupings and latest terminal position snapshots.
- Broker deal ingestion now captures profit, commission, swap and fee in account-currency units, with idempotent ticket storage, immutable cash-evidence conflict checks and nullable migrations that preserve unknown legacy values.
- Same-second deals are ordered by numeric MT5 ticket; the bridge reports the actual broker deal magic. Account currency is matched to a single observed broker server and left unknown when mixed-server history makes the currency ambiguous. Complete-only net P&L excludes incomplete cycles; standalone balance/commission adjustments are not silently allocated.
- Read-only realized P&L and trade attribution reconstructs closed position cycles by terminal plus MT5 POSITION_IDENTIFIER, handles partial fills/exits and INOUT reversals, and excludes open, unmatched, ambiguous or cash-incomplete cycles from performance metrics. Dashboard reports cash coverage, account currency, unmatched counts, open positions, win rate, expectancy, profit factor and realized cash drawdown. Magic number remains a grouping key, not proof of strategy attribution.

## Still required before demo execution can be enabled

- Both MT5 Expert Advisors have been compiled locally in MetaEditor with 0 errors and 0 warnings. Recompile after the latest history/tagging changes; CI does not compile MQL5.
- Validate EA account-mode detection, symbol specifications, lot step, filling policy, stop/target placement and margin checks on an Exness demo account.
- Validate the new broker-history reconciliation against actual Exness demo deal records, including multiple partial fills, no-fill/pending orders, order comments, ticket mapping, disconnects and terminal restarts. Expired or uncertain commands remain quarantined; never blindly retry them.
- Validate broker-verified position/order state transitions, close/reversal deals and position-to-deal links against actual Exness demo history.
- Protective-stop monitoring and fail-safe pause/kill-switch recovery are implemented; automated broker-side SL modification/flattening is intentionally not automatic and requires an independently reviewed recovery policy.
- Validate realized P&L aggregation against Exness demo statements, including broker cash rounding, fees, swap timing, close-by deals and reversals. Daily loss and unrealized exposure still require independent broker-record validation; the current daily-loss monitor remains an operational estimate.
- Broker-verified restart/disconnect recovery and end-to-end duplicate-event testing; backend lease quarantine, terminal identity checks, persistent terminal attempt markers and intent-tag lookup are implemented but not yet proven against live broker demo history.
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
