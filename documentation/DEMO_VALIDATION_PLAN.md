# Dedicated MT5 Demo Validation Plan

## Purpose and safety boundary

This plan validates the broker-facing adapter on a dedicated demo account only.
It is not permission to enable execution. The repository defaults remain
fail-closed: backend demo dispatch disabled, runtime pause active, kill switch
active, and the demo execution EA disabled. Do not change those settings as
part of ordinary dashboard or telemetry testing.

Never use a live account. Never share passwords, investor passwords, API
tokens, account numbers, or private account identifiers in screenshots,
terminal output, issues, or chat.

## Gate 0 — source and environment review

- Confirm the terminal is logged into the intended broker demo account.
- Confirm MT5 reports the account trade mode as demo.
- Confirm the broker server and symbol suffixes match the configured
  allowlist and current symbol-specification telemetry.
- Confirm the public telemetry tunnel exposes only the explicitly permitted
  telemetry routes; admin and execution command routes must remain private.
- Confirm backups are fresh and verified before any controlled test.
- Keep the execution EA disabled while completing compilation and telemetry
  checks.

Expected result: the telemetry EA can report heartbeat, account, quotes,
symbol specifications, candles, positions, broker orders and demo deal
history without placing or modifying an order.

## Gate 1 — compile both Expert Advisors

Compile these files in MetaEditor:

- `mt5/Experts/ForexAutopilotTelemetry.mq5`
- `mt5/Experts/ForexAutopilotDemoExecution.mq5`

Record the MetaEditor build number and compile output. Resolve every compiler
error and review warnings. A CI source-contract pass is not a substitute for
this compile.

Expected result: both EAs compile cleanly; the execution EA remains disabled.

## Gate 2 — read-only broker telemetry

Run the telemetry EA on the dedicated demo terminal and verify:

- heartbeat and account snapshots are fresh and identify the expected demo
  server;
- quotes and symbol specifications arrive for the intended symbols;
- candle batches pass integrity checks and coverage increases;
- current positions include broker-reported stop-loss and take-profit values;
- broker order and deal history uploads are accepted and match the demo
  terminal's own history for the configured magic number.

An HTTP success with zero matching deals is not proof of a history failure or
proof that there were no broker deals. Compare the matching-deal count with
the terminal's broker history and confirm the magic-number filter.

Expected result: read-only telemetry remains stable and no order is sent.

## Gate 3 — controlled demo execution scenarios

This gate requires a separate, explicit operator decision after Gates 0–2.
Do not enable dispatch or the EA automatically. Before a controlled test,
review the exact demo account, symbol allowlist, maximum volume, risk limits,
stop/target distance, emergency stop, pause control and rollback procedure.

On the dedicated demo account, validate one scenario at a time:

1. A normal accepted order with broker order/deal confirmation.
2. Multiple partial entry deals for one order; cumulative fill volume must
   reconcile idempotently and the weighted average price must match the deals.
3. A broker rejection; the intent must be recorded as rejected, not retried.
4. A cancellation or expiry; any partially filled remainder must be surfaced
   for review, not silently treated as a full cancellation.
5. A terminal disconnect after dispatch but before acknowledgement; the
   outcome must remain unknown/quarantined until broker history resolves it.
6. Duplicate polling and repeated rolling history uploads; no duplicate
   dispatch or duplicate deal accounting may occur.
7. Missing broker-confirmed stop-loss or take-profit; new entries must be
   paused and the emergency control engaged by the protective guard.
8. Stale account, quote, terminal or symbol-specification telemetry; preflight
   must fail closed.

Expected result: every outcome is matched to broker-side evidence, uncertain
outcomes are never automatically resent, and no position is silently modified
or closed by reconciliation.

## Gate 4 — restart and recovery

- Restart the MT5 terminal while an intent is pending or its result is
  uncertain.
- Confirm the persistent command marker prevents duplicate dispatch.
- Confirm expired leases and uncertain outcomes remain quarantined.
- Restart the API and verify the durable intent ledger and broker history
  survive.
- Verify the backup inventory and perform an isolated restore drill to a new
  temporary database path; never restore over the live database during a drill.

Expected result: no duplicate order is created, evidence can recover an
uncertain acknowledgement, and recovery never invents a rejection or fill.

## Gate 5 — sustained forward-demo observation

Run the agreed multi-week demo observation period across varied market
conditions. Reconcile every managed order and closed position against the
broker statement. Track:

- requested, filled and remaining volume;
- broker order/deal/position identifiers;
- average fill price and all split fills;
- stop-loss and take-profit protection;
- realized profit, commission, swap and fees in account currency;
- unmatched deals, incomplete P&L cycles and manual-review events;
- telemetry outages, terminal restarts and backup freshness.

The dashboard's trade attribution is an operational reconstruction, not an
audited broker statement. Preserve broker statements as the authoritative
evidence for the test.

## Evidence and sign-off

For each gate, record the date, software commit, terminal build, demo server,
test scenario, expected result, observed result, and broker evidence reference.
Redact account identifiers and all credentials.

The release-readiness dashboard intentionally leaves these operator gates
open. Passing automated tests or dashboard checks does not mark a manual gate
complete and does not authorize live trading.
