# ADR 0001: Create a narrow Python agent kernel

- Status: Accepted
- Date: 2026-09-01

## Context

Codapt2 demonstrates a strong event-driven agent control plane, but its agent
implementation is coupled to a TypeScript/Effect/PostgreSQL workflow framework,
multi-tenant workspaces, billing, machines, semantic discovery, and UI
projections. Jarvis and future Python applications need the orchestration
semantics without that product substrate.

`provider-runtime` already owns LLM provider calls and native Codex/Claude agent
sessions. `llm-tools` already owns typed tools, closed capability plans,
execution, and effect contracts. Applications own their product data and
authority.

## Decision

Create `llm-agent-kernel`, imported as `llm_agent_kernel`, for Python 3.12 or
newer.

The package owns:

- Agent definitions and explicit run limits.
- Immutable maximum capability envelopes with host-selected frozen per-run
  subsets.
- Conversational and closed structured output contracts.
- Provider-neutral continuation and bootstrap context projections.
- A strict model-step protocol and bounded corrective feedback.
- Bounded model/tool step loops and cancellation.
- Fresh read-only one-shot invocation for recomputable internal roles.
- Continuing thread drains and isolated structured one-shot runs are distinct
  v1 façades rather than one ambiguous mode branch.
- Session, input-checkpoint, drain/finalization, dispatcher, and event-sink
  ports.
- Normalized kernel events, terminal outcomes, fakes, and conformance tests.

It owns no database schema, workflow engine, provider implementation, tool
registry, application policy, approval state, connector, memory system,
transport, or user interface.

## Consequences

Positive:

- Agent-loop correctness can be tested once and reused.
- Applications retain their existing persistence and product boundaries.
- Jarvis can keep exactly four application tables.
- Native sessions remain an optimization over rebuildable canonical context.

Costs:

- A third package introduces version and integration coordination.
- Python reimplementation cannot assume Codapt2's behavior was preserved; new
  black-box and race conformance tests are mandatory.
- Strict boundaries may leave small application adapters repetitive.

## Rejected alternatives

- Extract Codapt2 code directly: imports its language, durability, and product
  coupling.
- Put orchestration in `provider-runtime`: collapses stateful application loops
  into a library intentionally scoped to provider/session execution.
- Put orchestration in `llm-tools`: mixes tool authority with agent lifecycle.
- Keep a private loop in every application: duplicates subtle race and protocol
  behavior that is hard to extract later.
