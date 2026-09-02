# Repository instructions

This repository specifies and, after an explicit implementation request, will
contain `llm-agent-kernel`, imported in Python as `llm_agent_kernel`.

## Current phase

- The repository is documentation-only.
- Do not add runtime code, packaging, generated artifacts, or dependencies until
  the user explicitly requests implementation.
- Canonical product requirements live in `SPEC.md`.
- Architecture, acceptance criteria, implementation slices, and decisions live
  under `docs/`.

## Permanent boundaries

- Target Python 3.12 or newer.
- Consume `provider-runtime` for provider calls and native agent-session
  lifecycle.
- Consume `llm-tools` for prompt sections, tool declarations, frozen capability
  plans, validation, execution, budgets at the tool boundary, and replay/effect
  contracts.
- Own only provider-neutral agent orchestration: roles, context projections,
  strict model steps and output contracts, bounded step loops, isolated one-shot
  runs, cancellation, session/checkpoint ports, drain/finalization semantics,
  normalized kernel events, and conformance tests.
- Own no SQL schema, migration, workflow engine, queue, lease service, connector,
  credential store, memory system, user interface, transport, application tool,
  approval policy, or effect ledger.
- Do not duplicate provider adapters or the `llm-tools` registry, profiles,
  executor, discovery implementation, or prompt renderer.
- V1 contains no Lua/CodeAct runtime and no general delegation or subagent graph.

## Change rules

- Prefer the smallest reusable contract proven by a real consumer.
- A second consumer is required before generalizing a Jarvis-specific adapter
  into a new framework abstraction.
- New persistent-state requirements, workflow semantics, program execution,
  delegation, provider ownership, or tool-kernel ownership require an ADR.
- Keep provider sessions disposable. A host's canonical context must be able to
  bootstrap a replacement session.
- Validate a complete model step before emitting output or dispatching any tool.
- Keep v1 one-shot runs non-effectful; effectful work requires the thread,
  checkpoint, and host reconciliation boundary.
- V1 thread runs use continuing definitions. V1 one-shot runs use isolated,
  structured definitions; reject other façade/mode combinations before I/O.
- Parallel dispatch is only for calls declared non-effectful and classified by
  the host as automatic/non-stopping.
- The kernel never decides application authority. A host dispatcher may report
  executed, pending approval, denied, failed, or uncertain outcomes.
- Agent definitions contain immutable maximum capability envelopes; applications
  supply frozen per-run plans that may narrow but never expand them.
- Each thread claim carries an opaque host run class bound to its frozen plan;
  never drain input that the host classifies for a different plan.
- Kernel trace events are observability, not a mandatory canonical event store.
  Hosts persist terminal conclusions and effectful outcomes through state they
  already own; read observations may remain turn-local.
- Never describe XML-like prompt formatting as a security boundary.

## Documentation quality

- Acceptance IDs are unique and are assigned to exactly one implementation
  slice in `docs/acceptance.md`.
- Keep terminology aligned with `SPEC.md`; do not use agent, thread, run, step,
  role, or provider session interchangeably.
- Every trade-off is explicit. Do not hide operational requirements behind a
  generic adapter or "production implementation" placeholder.
- Use relative Markdown links inside this repository and verify every link and
  anchor after edits.
