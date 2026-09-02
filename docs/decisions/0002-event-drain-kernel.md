# ADR 0002: Use host-owned claims, polling, settlement, and admission

- Status: Accepted
- Date: 2026-09-01
- Superseded in part: 2026-09-02

## Context

Input can arrive while a model turn or tool call runs. A naive batch read misses
mid-loop steering. A naive idle transition can lose a wake-up. More seriously,
per-run budgets do not bound a system whose cleanup automatically starts a new
run over the same poison input.

Codapt2's ordered queue and check-before-idle behavior are useful prior art. Its
workflow/database implementation is not a reusable Python library boundary, and
Jarvis v1 does not need its run-class negotiation.

The first version of this ADR required `release` and several stop paths to arm a
successor. That turns protocol exhaustion, cancellation, or a malformed input
into an unlimited sequence of fresh budgets. It also read one input batch only
outside the model/tool loop.

## Decision

Use host protocols with these semantics:

- `claim` returns no work/busy/deferred or one bounded non-empty input batch,
  its opaque checkpoint, durable attempt number, and host-selected frozen plan.
- The host owns priority, batching, and compatibility. The kernel has no
  `run_class`.
- `poll` runs before each provider turn, before dispatch, after a tool result,
  and before settlement. It appends compatible ordered input once or preempts.
- `settle` atomically and idempotently persists a host conclusion and consumes
  through the checkpoint. It reports whether later input remains.
- `release` is cleanup only and never arms a successor. Interrupted unconsumed
  input is recovered by explicit startup/recovery scanning.
- Deterministic no-progress exits settle a host-authored stopped conclusion and
  consume the poison input.
- A durable per-input attempt number bounds crash recovery.
- A host-issued rolling admission token is required before provider I/O and
  bounds provider turns, available token usage, no-progress attempts, and
  concurrency across runs.

V1 keeps a valid conclusion if ordinary follow-up input races with
finalization, then processes the follow-up next. It does not suppress and
regenerate a paid answer. Exact stop/pause input can preempt before settlement.

No database transaction remains open across provider or connector I/O. A host
signals work after a committed `settle(more_input)`, while canonical unconsumed
input and recovery scanning close the database/process-trigger gap.

## Consequences

Benefits:

- Human steering can affect the next model/tool boundary.
- Cancellation and poison input cannot silently replenish their budget forever.
- Cross-run spend and concurrency become enforceable system properties.
- A host can use its existing persistence without importing a workflow engine.

Costs:

- Hosts must durably count attempts and rolling usage.
- Ordinary follow-up input may receive a prior valid answer before its own run;
  exact answer suppression/rewrite is intentionally absent.
- Process interruption can leave visible unconsumed work for recovery rather
  than immediately scheduling an automatic successor.

## Rejected alternatives

- Unconditional rearm on cleanup: unbounded subscription/spend failure.
- Read input once per run: prevents conversational steering.
- Kernel run classes: duplicates host priority/compatibility and complicates the
  crash-critical claim port.
- Always suppress a final answer if input raced: discards paid valid work and
  requires more durable provider-output state.
- Own a generic event database or workflow engine: exceeds the library boundary.
