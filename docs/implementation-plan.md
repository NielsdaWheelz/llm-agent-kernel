# Implementation plan

Implementation begins only after an explicit user request. Each slice must be
usable and tested before the next begins.

## Slice 0: contract and package

Deliver:

- Python 3.12 package skeleton and public typed vocabulary.
- Reproducible lock against the qualified `provider-runtime` and `llm-tools` git
  revisions, never mutable sibling worktrees.
- `AgentDefinition`, role/session-mode/limit values, kernel events, terminal
  outcomes, conversational/structured output contracts, and public ports.
- Immutable definition envelopes and before-I/O validation that every frozen
  per-run plan is a subset.
- Façade validation: thread runs require continuing mode; one-shot runs require
  isolated mode and structured output.
- No-op-safe imports and deterministic fakes for every port.
- Dependency-boundary tests preventing provider SDK, application, database, and
  duplicate tool-kernel imports.
- Documentation examples that execute entirely against fakes.

Exit: K001–K007 and K028 pass.

## Slice 1: context and provider sessions

Deliver:

- Provider-neutral continuation and cold-bootstrap context projections using
  `llm-tools` prompt sections.
- Source timestamps and one host-provided `as_of` value.
- `provider-runtime` adapter for new, resumed, and fresh isolated sessions.
- Session-reference compatibility checks, discard-on-resume-failure, and at most
  one host-authorized cold-bootstrap attempt.
- Stateless fake adapter proving that useful context does not depend on native
  session history.

Exit: K008–K010 and K025 pass.

## Slice 2: strict step and tool loop

Deliver:

- Closed `say | call_tools | finish` schema and complete-step validation.
- Conversational output plus closed structured `finish.result` validation.
- Bounded corrective feedback for invalid model output.
- Frozen `llm-tools` plan integration and application `ToolDispatcher` port.
- Deterministic observation ordering for bounded concurrent calls that are both
  declared non-effectful and host-classified automatic/non-stopping.
- Executed, pending-approval, denied, failed, and uncertain dispatch outcomes.
- Suspension on pending approval without an open provider turn, transaction, or
  worker.
- Explicit budgets, cancellation, best-effort event-sink attempts, and terminal
  taxonomy.
- Stable run/step/call invocation positions supplied to the tool boundary.
- An isolated one-shot façade that rejects effectful plans, opens a fresh
  session, touches no checkpoint or saved-session-reference port, and returns a
  validated structured terminal result.

Exit: K011–K020, K024, K026–K027, K031, and K034 pass.

## Slice 3: drain and finalization

Deliver:

- Application-thread claim and release protocol with one active drainer.
- Idempotent cleanup release that arms recovery before relinquishing a claim
  with any unconsumed input.
- Opaque ordered input checkpoints.
- Atomic host finalization contract that detects newly arrived waking input and
  either continues or arms a deferred run before releasing ownership.
- Opaque run-class binding that limits each claim to a maximal same-class input
  prefix and forces an armed handoff before differently authorized input.
- Crash-order fixtures proving session-reference advancement before canonical
  settlement, generation advancement, stale-CAS failure, and discard of a
  speculative reference when effect-free settlement does not commit.
- Pending-approval/resolution fixtures correlated by opaque host reference and
  driven by host action state rather than replay.
- Failure-injection suite across claim, model, trace, effectful dispatch, and
  finalization boundaries.
- Race tests with deterministic scheduling.

The package still ships no database implementation. A reference in-memory
adapter is a conformance double, not a production durability claim.

Exit: K021–K023, K029–K030, and K032–K033 pass.

## Slice 4: qualification and release

Deliver:

- Opt-in paid live qualification through `provider-runtime`.
- Evidence records containing versions, route, status, usage, and trace IDs but
  no prompts, credentials, or private payloads.
- Package build, type checking, linting, deterministic tests, dependency audit,
  and release checklist.
- One real Jarvis integration and a documented boundary review before 0.1.0.

Exit: K035 passes and Jarvis can use the package without adding an application
table.

## Explicitly deferred

- Lua, QuickJS, WASM, CodeAct, or any model-authored program runtime.
- Semantic tool discovery as a kernel requirement; consumers may opt into the
  existing `llm-tools` capability.
- General delegation, persistent peer agents, task trees, join, or cancellation
  propagation.
- SQL adapters, workflow engines, queues, distributed leases, schedulers, and
  dead-letter processing.
- Provider SDK adapters outside `provider-runtime`.
