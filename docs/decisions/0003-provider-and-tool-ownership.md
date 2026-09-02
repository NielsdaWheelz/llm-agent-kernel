# ADR 0003: Preserve real provider-runtime and llm-tools ownership

- Status: Accepted
- Date: 2026-09-01
- Amended: 2026-09-02

## Context

The original design described dependency behavior that the pinned public APIs
did not provide. `AgentSessionRequest` takes `PermissionPolicy` and MCP servers,
not a host-tool list. `llm-tools` distinguishes `ToolEffect` from
`ReplayPolicy`; its executor validates during occupied, budgeted dispatch, while
the kernel needs pure pre-dispatch validation. `RunLimits` in `llm-tools` is a
tool budget, not a kernel model-loop budget.

Inventing lookalike types inside the kernel would create a false security
boundary and divergent replay behavior.

## Decision

Use public `provider-runtime` contracts for native Codex session creation,
resume, turns, events, interruption, references, close, containment policy,
native options, structured-output lowering, quota, and normalized usage.

Use public `llm-tools` contracts for prompt sections, declarations, catalogs,
bindings, frozen profiles/plans, `HostTable`, schemas, pure argument validation,
`ToolEffect`, `ReplayPolicy`, tool budgets, positions, effect IDs, recorder
semantics, execution, and results.

Before implementation, add the four missing public `llm-tools` seams enumerated
in SPEC section 2. Do not import private modules or reimplement them locally.

The kernel owns semantic step/output validation and enforces proof that a run
plan tightens a definition maximum. The host owns policy, plan selection,
effect-ID minting, the durable recorder implementation, external
reconciliation, and product state.

The host dispatcher returns a completed `llm_tools.ToolResult` or a durable
suspension. It does not compress approval, denial, failure, and uncertainty into
a kernel-owned application state machine. A later host resolution contains the
original validated call and safe evidence.

## Consequences

Benefits:

- Security and replay behavior have one truthful owner.
- Kernel and tool budgets cannot silently double-charge the same operation.
- Dependency drift is detected by contract canaries and qualification.

Costs:

- `llm-tools` must be upgraded before kernel implementation.
- Compatibility spans three packages and requires an integration matrix.
- Applications remain responsible for durable action/effect storage and
  reconciliation.

## Rejected alternatives

- Validate by calling the executor: mutates position, recorder, and budget before
  whole-step validation finishes.
- Treat `Pure`/`Read` as “non-effectful”: erases the independent replay-policy
  dimension and billed-read cost.
- Build capability containment inside the kernel: duplicates the plan owner.
- Put application approval states in the kernel: turns product authority into a
  misleading generic vocabulary.
- Treat prompt markup as a security boundary: structure cannot neutralize
  semantic prompt injection.
