# ADR 0006: Bound work across runs

- Status: Accepted
- Date: 2026-09-02

## Context

Eleven finite counters inside one run do not bound a system that automatically
starts unlimited successor runs. The original release contract required cleanup
to rearm whenever input remained unconsumed. A protocol-poisoning input,
subscription quota error, or cancellation could therefore consume fresh budgets
overnight.

Subscription-backed `AgentRuntime` exposes turns, normalized token usage when
available, and quota exhaustion—not the stateless root lane's priceable
`CallMeta`. A fictional dollar estimate would not improve control.

## Decision

Bound the complete run sequence:

- `release` never schedules a successor.
- Protocol exhaustion, kernel-budget exhaustion, quota exhaustion, declared
  stop, and repeated provider failure persist a host-authored stopped conclusion
  and consume the logical input.
- Process interruption may leave input unconsumed, but the host increments a
  durable no-progress attempt number on reclaim. Exceeding its ceiling stops or
  parks before provider I/O.
- Configuration defects park input and trip a host circuit breaker.
- Every thread run requires a host-issued rolling admission token before
  provider I/O. At minimum the policy bounds provider turns, available reported
  input/output tokens, no-progress attempts, and concurrent cognitive work.
- Usage settles against admission on success, failure, cancellation, and
  interruption paths.
- Canonical unconsumed input plus explicit startup/recovery scanning, not
  cleanup recursion, drives recovery.

Cost is an optional dimension only for a future provider lane whose normalized
terminal is actually priceable.

## Consequences

Benefits:

- A single input cannot renew its provider budget indefinitely.
- Cancellation truly stops instead of reproducing the cancelled work.
- Subscription quota and provider failures stay visible and actionable.

Costs:

- The host must persist attempt and rolling-usage facts.
- Interrupted work may wait for recovery scanning rather than an immediate
  automatic successor.
- A conservative ceiling can stop legitimate expensive work; the stopped
  conclusion must make that visible to the owner.

## Rejected alternatives

- Per-run limits alone: do not bound run count.
- Blind retry/backoff forever: delays but does not cap spend.
- Estimate subscription dollars from token counts: the selected provider
  surface does not expose that pricing contract.
- Treat configuration defects as model-visible tool failures: invites the model
  to loop over an operator problem.
