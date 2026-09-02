# ADR 0004: Defer program agents, discovery, and delegation

- Status: Accepted
- Date: 2026-09-01
- Amended: 2026-09-02

## Context

Codapt2 gives a model a deterministic Lua program surface over a large host
function table and supports persistent peer agents. Those are promising for
large catalogs and long-running coordination. Jarvis v1 has a small fixed tool
catalog and no concrete task requiring a program VM or general delegation.

The current `llm-tools` discovery matcher is lexical ranking, not semantic
retrieval. Its existence does not justify making discovery part of the kernel.

## Decision

V1 contains no model-authored program runtime, kernel tool discovery, or
delegation graph. It uses an explicit frozen `HostTable` and one serial
`call_tool` per model step.

A program runtime may later be evaluated as a separate optional package. It must
beat structured calls on representative tasks across quality, provider turns,
tokens, latency, invalid programs, crash recovery, and write correctness. Any
sandbox claim must distinguish language-capability isolation from OS isolation.

Delegation may be proposed after a consumer requires it. A future task contract
must define identity, parentage, role/objective, strictly narrowed plan, budgets,
deadline, structured result, observe/join, terminal state, cancellation, and
downward cancellation propagation.

Discovery may be added at the host/`llm-tools` exposure boundary only after
catalog size and measured selection quality justify it.

## Consequences

Benefits:

- V1 establishes the authority, recovery, and run-bounding seams without a VM or
  task scheduler.
- Future children cannot silently inherit the parent's full authority.
- Tool selection behavior remains explicit and measurable.

Costs:

- Large catalogs may use more prompt tokens or provider turns.
- Applications cannot claim general program agents or delegation in 0.1.

## Rejected alternatives

- Port Codapt2 Lua immediately: unmeasured complexity for the first consumer.
- Embed Python/JavaScript instead: changes familiarity, not replay or sandbox
  correctness.
- Describe lexical substring ranking as semantic discovery: factually wrong.
- Copy Codapt2 peers: lacks the complete narrowed-task contract required here.
