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
resume, streamed turns, events, interruption, references, close, containment
policy, native options, structured-output lowering, quota, and normalized usage.
The kernel consumes the public event stream rather than the convenience
terminal projection because containment depends on observing native authority
events.

Use public `llm-tools` contracts for prompt sections, declarations, catalogs,
bindings, frozen profiles/plans, plan/catalog consistency and tightening,
`HostTable`, schemas, pure argument validation, `ToolEffect`, `ReplayPolicy`,
owner-controlled binding implementation revisions, tool budgets, positions,
effect IDs, recorder semantics, execution, and results.

Use the qualified `llm-tools` revision recorded in SPEC section 2, which adds
the four previously missing public seams. Do not import private modules or
reimplement them locally.

The kernel owns semantic step/output validation and requires the dependency's
public proof that the exact plan/catalog view being published is internally
consistent and tightens a definition maximum. A profile-only comparison cannot
authorize publication. An implementation revision covers the handler and its
transitive execution behavior; it must change when that behavior changes unless
revisioned policy inputs already represent the change. The host owns policy,
plan selection, effect-ID minting, the durable recorder implementation,
external reconciliation, and product state.

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

- The kernel requires the qualified upgraded `llm-tools` revision rather than
  the earlier release baseline.
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
