# ADR 0004: Defer program agents and delegation

- Status: Accepted
- Date: 2026-09-01

## Context

Codapt2 gives the model one `run(code)` tool backed by deterministic Lua and a
large host-function table. This can reduce round trips for a broad catalog.
Codapt2 also lets agents create and notify persistent peers, but those peers have
no task result, parentage, capability narrowing, join, deadline, or cancellation
contract.

Jarvis v1 has a small fixed catalog, batched structured calls, subscription
Codex sessions without an equivalent arbitrary host callback, and no concrete
need for general delegation. The bitter-lesson baseline is to use model-native
structured capabilities before adding a custom interpreter.

## Decision

V1 contains neither a model-authored program runtime nor a delegation graph.
Semantic tool discovery remains an optional `llm-tools` exposure, not a kernel
requirement.

Program execution may be evaluated later as a separate optional package or
extra. It must beat structured tool calls on real tasks across quality, model
calls, tokens, latency, invalid programs, crash recovery, and external-effect
correctness. Any sandbox claim must distinguish language-capability isolation
from OS isolation.

Delegation may be proposed after a real consumer requires it. A future task
contract must include an ID, parent ID, role/objective, strictly narrowed
capability plan, explicit budgets and deadline, structured result, terminal
status, observe/join, cancellation, and downward cancellation propagation.

## Consequences

Positive:

- Jarvis receives the reusable loop without a VM or task scheduler.
- The core package has no native-process or sandbox dependency.
- Future delegation cannot silently inherit the caller's complete authority.

Costs:

- Large-catalog agents may initially use more model round trips.
- Applications cannot claim generic subagents from the first release.
- A later program runtime, if justified, will require another package boundary.

## Rejected alternatives

- Port Codapt2 Lua immediately: unmeasured complexity for Jarvis's small catalog.
- Embed Python or JavaScript instead: changes familiarity, not the correctness or
  sandbox burden.
- Copy Codapt2 peer agents: lacks the semantics required for safe delegation.
- Build a generic task graph speculatively: no v1 consumer has earned it.

