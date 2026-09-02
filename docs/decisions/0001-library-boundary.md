# ADR 0001: Create a narrow Python agent kernel

- Status: Accepted
- Date: 2026-09-01
- Amended: 2026-09-02

## Context

Codapt2 demonstrates a strong event-driven control plane, but its agent loop is
coupled to TypeScript/Effect/PostgreSQL, multi-tenant workspaces, billing,
machines, discovery, and UI projections. Jarvis and future Python applications
need the reusable loop semantics without that product substrate.

`provider-runtime` already owns native provider sessions. `llm-tools` already
owns typed tools, plans, execution, budgets, replay positions, and result
envelopes. Applications own product state and authority.

The first draft overclaimed that library adoption required no persistent table.
Schema ownership and durable-state requirements are different questions. An
effectful continuing application needs canonical input/conclusion/delivery,
session-reference generation state, durable effect recording, and cross-run
admission facts even if it maps them into existing storage.

## Decision

Create `llm-agent-kernel`, imported as `llm_agent_kernel`, for Python 3.12 or
newer.

The package owns:

- Immutable agent definitions and complete containment fingerprints.
- Provider-neutral context projections and disposable-session choreography.
- A closed structured step protocol and whole-step semantic validation.
- A bounded serial model/tool loop with input polling and cancellation.
- Cross-run admission enforcement through a host port.
- Continuing thread and isolated structured one-shot façades.
- Provider-session, checkpoint, context, dispatch, admission, and event ports.
- Typed outcomes, deterministic fakes, and conformance tests.

It owns no application schema, workflow engine, provider implementation, tool
registry/executor/recorder, application policy, effect identity, connector,
memory system, delivery system, transport, or UI.

The library states the durable facts its ports require and tests them through a
conformance host. It does not dictate whether a host uses tables, files, an
atomic document, or a workflow substrate. In-memory adapters are test doubles,
not production durability.

## Consequences

Benefits:

- The difficult control loop and its seam tests can be reused.
- Provider/tool behavior keeps one owner.
- Applications choose their persistence layout and product policy.
- Native sessions remain optimizations over canonical rebuildable context.

Costs:

- Three packages require explicit revision qualification.
- Every production host must honestly implement canonical settlement, durable
  write recording, session-ref CAS, and rolling admission.
- A small host adapter remains application-specific.

## Rejected alternatives

- Extract Codapt2 wholesale: imports unrelated runtime and product coupling.
- Put orchestration in `provider-runtime`: conflates native sessions with host
  work consumption and authority.
- Put orchestration in `llm-tools`: conflates tool execution with agent
  lifecycle and conversation settlement.
- Claim no durable-state requirement: makes crash safety untestable and false.
- Keep a private loop in every application: duplicates subtle race and replay
  behavior that becomes harder to extract later.
