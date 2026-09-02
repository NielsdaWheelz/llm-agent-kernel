# Architecture

## System boundary

`llm-agent-kernel` is orchestration glue between an application, a model
provider, and a capability executor. It owns the control flow but none of the
domain authority.

```text
┌──────────────────────── application ─────────────────────────┐
│ canonical thread/history policy  approvals  memory  delivery │
│        │                   │                                  │
│        ├── persistence ports ───────┐                         │
│        └── context source           │                         │
└─────────────────────────────────────┼─────────────────────────┘
                                      v
                         ┌────────────────────────┐
                         │   llm-agent-kernel     │
                         │ bounded event drain    │
                         │ context projections    │
                         │ strict step protocol   │
                         └──────────┬─────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    v                               v
          ┌──────────────────┐            ┌──────────────────┐
          │ provider-runtime │            │    llm-tools     │
          │ calls + sessions │            │ plans + executor │
          └──────────────────┘            └────────┬─────────┘
                                                   v
                                          application bindings
```

Dependencies point downward only. Jarvis may depend on all three packages;
neither dependency knows about the kernel, and the kernel does not know about
Jarvis.

The ownership split is fixed by [ADR 0001](decisions/0001-library-boundary.md)
and [ADR 0003](decisions/0003-provider-and-tool-ownership.md).

## Core components

### `model.py`

Defines immutable provider-neutral values:

- `AgentDefinition`, immutable capability envelope, `Role`, `RunLimits`,
  `SessionMode`, and `ContextPolicy`.
- Conversational and closed structured `OutputContract` values.
- `SayStep`, `CallToolsStep`, and `FinishStep`.
- Tool dispatch outcomes and public run outcomes.
- Typed waking input, including host-authored `ActionResolutionInput` correlated
  by an opaque durable host reference rather than a turn-local call ID.
- Opaque thread, checkpoint, event, invocation, and session-reference types.

These values contain no ORM, connector, SDK response, or UI types.

### `protocol.py`

Owns the closed step grammar and validation choreography. Structural validation
runs first; every proposed call is then resolved and validated against the
already-frozen per-run `llm-tools` plan, which must be a subset of the definition
envelope. The module returns either one fully valid step or one bounded
corrective diagnostic. It never dispatches incrementally.

Provider-specific structured-output decoding belongs in the provider adapter,
but it must produce the same semantic `Step` and cannot weaken validation.

### `context.py`

Builds typed semantic sections from host material. It has two projections:

- **Continuation:** as-yet unseen input, fresh retrieved material, current
  capability context, and new current-run observations for an existing
  compatible session. An accepted response makes that input seen, so later tool
  or protocol continuations do not repeat it.
- **Cold bootstrap:** stable role/instructions and bounded canonical history,
  followed by the same current-turn material.

Both use `llm-tools` prompt-section and rendering facilities. Source IDs,
timestamps, and omission markers survive selection. The module contains no XML
implementation and does not treat presentation markup as a security boundary.

### `loop.py`

Owns the bounded run/drain state machine described in
[SPEC section 8](../SPEC.md#8-drain-algorithm). Its important invariant is:

> No model-proposed text or effect crosses a host boundary until the entire
> model step is valid.

It ensures observations are normalized before another model step, stopping
outcomes do not invite blind retries, and all loops consume finite budgets.
Intermediate observations may remain turn-local; effect durability is enforced
at the tool boundary.

The loop has two narrow façades: a thread drain with checkpoint/session ports,
and an isolated one-shot invocation with neither. Both share validation,
dispatch, correction, budgets, and cancellation. One-shot structured roles
accept only non-effectful plans and return a schema-valid `finish.result` for the
application to commit; the kernel does not pretend that result was durable.
Thread drains require continuing definitions in v1; isolated definitions use
the one-shot façade.

### `coordination.py`

Defines the input-checkpoint protocol and normalized event-sink hooks. The
application supplies exclusive claim and atomic terminal finalization behavior
using its existing durability mechanism.

Each thread claim is bound to an opaque host `run_class` and its frozen plan.
The checkpoint adapter returns only the maximal ordered input prefix eligible
for that class. If the next input belongs to another class, finalization arms
the appropriate run and defers even when the current run has budget. This
prevents a narrow proactive run and a broad interactive run from consuming each
other's work.

The idle transition is a compare-and-set over an opaque consumed watermark:

```text
model concludes input through W
          |
          v
atomically persist conclusion + consume through W
          |
          v
is there waking input after W?
     yes /                 \ no
 same-class + budget?       commit idle
 continue / arm defer
```

An input arriving before the test forces `continue` when budget remains or an
atomically armed deferred run before ownership is released. An input arriving
after idle commits observes an idle thread and starts a new run. There is no
interval in which waking input is both unclaimed and believed consumed.

### `adapters/`

The initial adapters are intentionally thin:

- `provider_runtime.py` opens/resumes calls and translates completed responses
  and usage without making provider state canonical.
- `llm_tools.py` validates against a frozen plan and dispatches through the
  dependency's executor/effect boundary.

Application packages implement context, persistence, and policy adapters.
Reusable SQL repositories, workflow adapters, or provider-specific helpers may
be separate optional packages later; they are not v1 kernel responsibilities.

## State machine

```text
START
  |
  +-- claim denied ------------------------------> BUSY
  |
  v
LOAD_INPUT --> BUILD_CONTEXT --> MODEL_CALL --> VALIDATE
                                             invalid |
                                      RECORD_FEEDBACK
                                             |
                                             +--> BUILD_CONTEXT
                                                (within budget)

VALIDATE -- call_tools --> DISPATCH --> OBSERVE_OUTCOMES
                                |             |
           pending_approval/uncertain         +--> BUILD_CONTEXT
                                v
                       SETTLE_CHECKPOINT
                         /            \
            newer input                no newer input
          continue/defer                  WAITING

VALIDATE -- say/finish --> SETTLE_CHECKPOINT
                                  |
                      newer input | no newer input
                                  v
                            LOAD_INPUT     IDLE

Any boundary --> CANCELLED / BUDGET_EXHAUSTED / typed failure
```

The compact diagram omits one required ordering edge: after a valid provider
response, the generation-checked session reference advances before canonical
checkpoint settlement. If settlement is interrupted, the input is still
unconsumed and recovery discards that speculative reference. Effect-free work
may then replay; possible effects must reconcile through host state instead.
This prevents both resuming behind a committed conclusion and replaying
unresolved input into a session that already contains its response.

The drain claim is idempotently released in a `finally` path. No SQL transaction or
blocking database row lock is held across a model or connector network call;
exclusive ownership is a logical claim whose implementation belongs to the
host. Idempotent cleanup release arms a recovery run before relinquishing any
claim that still has unconsumed waking input.

## Persistence ports

### Kernel event sink

The event sink receives normalized lifecycle, protocol, provider, dispatch,
budget, and cancellation events for metrics and tracing. The host may persist a
redacted subset, but the sink is not the reconstruction source and requires no
table. Turn-local protocol feedback and read observations may disappear on a
crash and be recomputed. The kernel attempts emission before reuse, but a sink
failure is nonfatal. Durable effect state lives behind the dispatcher.

### Input checkpoint

The checkpoint is an opaque host value with only an ordering contract. The
kernel never assumes an integer, timestamp, database sequence, or provider
message ID. The host binds an equally opaque `run_class` to a frozen plan and
input-eligibility rule. `settle` combines idempotent host terminal-conclusion
persistence, advancement through the observed checkpoint, and an atomic choice
among same-class continuation, idle release, or an armed deferred run. Pending
approval is a terminal-conclusion kind, not a lock on the whole thread.

### Provider session reference

Session references are stored by `(thread_id, definition_fingerprint)` with a
generation for compare-and-set. They may live in a file, database, or application
runtime store. They are disposable and intentionally excluded from canonical
restore guarantees.

A fingerprint mismatch or safe resume failure discards the reference and uses a
cold bootstrap. Provider state is never used to infer that application input was
consumed. Every successful compare-and-set returns the next expected generation;
a stale result stops before dispatch or settlement. Crash recovery replays only
when durable host state proves that no effectful dispatch began; otherwise the
host action/effect record drives reconciliation.

## Authority flow

The kernel sees only the capability plan the application selected before the
drain. A role cannot expand it. A model cannot claim permission. The kernel asks
`llm-tools` to validate all proposed calls and then passes them to the host
dispatcher.

The host dispatcher may:

- Execute an automatic call through the normal tool/effect boundary.
- Persist an approval proposal and return `pending_approval` without executing
  it.
- Reconcile an ambiguous effect and return `executed` or `uncertain`.
- Reject a call according to application policy and return a declared failure.

The kernel handles and emits the outcome it is given. A pending-approval outcome
settles the proposing input and releases every live resource unless newer input
is already ready to drain. A later host-authored action-resolution input
correlates by the dispatcher's opaque host reference, not the turn-local call
ID. The kernel does not contain an approval matrix, build previews, handle
buttons, or mutate an application action ledger.

## Failure and recovery

Failure handling follows four rules:

1. **Canonical before derived.** Waking input, terminal conclusions, and effect
   state survive the provider session and traces.
2. **Validate before authority.** A malformed multi-call step performs nothing.
3. **Effects before claims.** A dispatcher reports an effect as executed only
   after its `llm-tools` recording contract is satisfied; read observations may
   remain turn-local and be recomputed after a crash.
4. **Do not guess effects.** Pending and uncertain work concludes the proposing
   input for host resolution instead of inviting a blind retry; unrelated newer
   input may still drain.

Provider transport retry is delegated to `provider-runtime`. Tool retry and
reconciliation are delegated to `llm-tools` plus the application binding. The
kernel itself retries only a bounded protocol correction and, before any valid
response, one safe continuation-to-bootstrap fallback.

## Deferred designs

Codapt2 demonstrates that a deterministic program step can reduce model/tool
round trips, and that persistent peer agents can coordinate through event
mailboxes. Neither is necessary to establish the v1 control plane.

Program agents would introduce a language runtime, resource accounting,
syscall/effect replay semantics, and a hostile-code isolation claim. Delegation
would require task identity, parentage, capability narrowing, budgets,
structured results, join/cancel behavior, and cancellation propagation. They
remain separate evaluable additions under
[ADR 0004](decisions/0004-defer-program-agents-and-delegation.md), not empty hooks
inside the core.

## Design tests

The package test suite should use deterministic fake ports to exercise the state
machine, then run adapter conformance against real dependency interfaces. The
highest-value fault injections are:

- Crash before and after every durable boundary.
- Concurrent run claims and waking input during idle settlement.
- Budget-exhausted input handoff that arms the next run before claim release.
- Invalid second call in an otherwise valid multi-call step.
- Provider-session loss, stale session compare-and-set, and cold bootstrap.
- Crash immediately before and after session-reference advancement and terminal
  settlement.
- Pending approval, uncertain effect, cancellation, and each budget edge.
- Context truncation with source/omission preservation.

These tests encode the event-drain rationale in
[ADR 0002](decisions/0002-event-drain-kernel.md) without requiring any particular
database or workflow engine.
