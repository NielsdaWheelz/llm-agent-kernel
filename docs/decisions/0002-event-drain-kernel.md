# ADR 0002: Use host-owned inputs, checkpoints, and race-safe drains

- Status: Accepted
- Date: 2026-09-01

## Context

Input may arrive while a model turn or tool call is running. A naive loop can
decide it is finished after new input has been persisted but before the new
input has scheduled another worker, losing a wake-up. Codapt2 solves this with
ordered context events, one drain owner, and an atomic consumed-watermark check
at idle.

A reusable package cannot require Codapt2's event tables, leases, or workflow
engine. Jarvis already has canonical messages and a one-process ownership model.

## Decision

Model orchestration around host protocols:

- Semantic input is application-owned and read through an opaque ordered
  checkpoint.
- At most one drain owns an application thread.
- Each claim carries an opaque host `run_class` bound to the frozen plan. Reads
  expose only a maximal same-class input prefix; differently classified input
  forces an armed handoff rather than being consumed under the wrong plan.
- Material observations and protocol feedback are offered to an event sink
  before another model call. Sink failure is nonfatal and persistence is
  optional; read observations may be recomputed after a crash, while effectful
  outcomes use the host's existing action/effect boundary.
- Finalization asks the host to atomically compare the consumed checkpoint and
  commit the terminal outcome.
- If new waking input exists, finalization continues when budget permits or arms
  a deferred run before releasing ownership.
- Cancellation/error cleanup likewise arms recovery before releasing a claim
  that still owns unconsumed input.

The kernel specifies state transitions and conformance tests. It supplies no SQL
tables, migrations, distributed lease, queue, or durability implementation.
Durability guarantees are conditional on the host adapter. The package must not
describe an in-memory conformance double as crash-safe.

An isolated one-shot invocation does not use this checkpoint protocol. It
accepts only a non-effectful plan, opens a fresh session, and returns a validated
structured result for the caller to commit, which keeps recomputable helper work
out of the durable-thread contract.

## Consequences

Positive:

- Lost wake-ups and concurrent drains have one testable contract.
- Hosts can use PostgreSQL, another store, or an intentionally process-local
  implementation.
- Jarvis can adapt its existing messages without new columns or tables.

Costs:

- A production host must implement an atomic finalization boundary honestly.
- Cross-crash replay depends on host canonical input/conclusion state and
  `llm-tools` effect recording, not on the kernel alone.
- A crash may repeat model reasoning or safe reads when the host intentionally
  keeps intermediate observations turn-local.
- Applications with inherently serialized ingress still implement a small
  checkpoint adapter.
- Applications with multiple authority classes must classify waking input and
  atomically hand off between classes.

## Rejected alternatives

- Own a generic event database: violates the library boundary and application
  schemas.
- Assume ingress always schedules another run: leaves a real lost-wakeup race.
- Import a workflow framework: disproportionate to the state machine.
- Hold a database transaction or provider session open while awaiting approval:
  fragile and operationally unbounded.
