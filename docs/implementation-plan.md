# Implementation plan

Implementation begins only after an explicit request. Each slice closes one
boundary and passes its assigned acceptance criteria before the next begins.

## Slice 0: dependency truth and package contract

The pinned `llm-tools` revision provides:

- Pure strict argument validation with no dispatch-side mutation.
- Public frozen-plan/catalog consistency and full tightening proof.
- Public `HostTable` publication/rendering.
- Async durable executor/recorder operations.

It is qualified against existing replay, uncertainty, `ToolEffect`,
`ReplayPolicy`, `InvocationPosition`, `EffectId`, and budget behavior, plus
cross-catalog effect/schema/handler-implementation/replay-policy/revision
substitution before publication. Every binding declares an owner-controlled
implementation revision covering its handler and transitive execution behavior.
The immutable revision is recorded in the kernel spec and reachable from the
durable remote; Slice 0 must lock that exact commit rather than import a sibling
worktree.

Then deliver:

- Python 3.12 package skeleton and public typed vocabulary.
- Dependency-boundary tests preventing private imports and duplicate provider
  or tool machinery.
- Definition, limit, plan, input-claim, dispatch, provider, session-ref,
  checkpoint, admission, context, event, cancellation, and outcome contracts.
- Deterministic fakes explicitly labelled non-durable.
- Executable documentation examples against fakes.

Exit: K001–K007 pass. No model or application tool is called in this slice.

## Slice 1: Codex agent sessions and context

Deliver:

- The exact `AgentRuntime` open/stream/close adapter, not a synthetic stateless
  provider façade or the event-discarding `run_turn` convenience projection.
- `JsonSchemaAgentOutput` mapping for one Codex-compatible closed-object wire
  envelope, with the provider-certified Codex SDK/runtime version pinned
  directly by the distribution.
- Fully fingerprinted `AgentSessionRequest`, `PermissionPolicy`, native options,
  private cwd lifecycle, and empty environment/MCP/network configuration.
- Complete stream consumption and event fail-stop for native tool-use or
  permission requests, plus suppression of streaming text delivery.
- Live continuing-session leases, isolated lifecycle, shutdown close, and typed
  provider terminal mapping.
- Generation-CAS session-ref port, resume compatibility, speculative-ref
  discard, and one safe cold-bootstrap fallback.
- Provider-neutral continuation and bootstrap sections using qualified
  `llm-tools` rendering and frozen `HostTable` publication.
- Cold-bootstrap fixtures built only from canonical host and durable action
  state.

Exit: K008–K024 pass, including a contract canary compiled and exercised against
the exact pinned dependency APIs.

## Slice 2: strict serial protocol and tool boundary

Deliver:

- Closed logical `say | call_tool | finish` models, a separate required/nullable
  provider wire envelope, strict JSON-string argument decoding, and independent
  semantic validation.
- Conversational and structured output-contract enforcement, including
  construction-time compilation/checking of nested, optional, and empty result
  schemas and deterministic rejection of unsupported/map-shaped contracts.
- Bounded protocol correction with a terminal poison stop.
- Pure plan lookup and argument validation before any mutation.
- Exactly one serial dispatcher call per model step.
- Explicit separation between `KernelLimits` and `llm_tools.RunLimits`.
- Host-owned action/effect identity mapping for `Write` and attempt-scoped
  `Pure`/`Read` behavior.
- Completed and suspended dispatch results with typed defect paths.
- Bounded observation projection, context omission markers, cancellation, and
  host activity events without model-authored progress prose.
- Fuzz and failure-injection tests proving whole-step atomic validation.

Exit: K025–K036 pass. No parallel code path or multi-call compatibility shim is
introduced.

## Slice 3: polling, settlement, and admission

Deliver:

- Exclusive claim of one bounded non-empty host batch with its frozen plan.
- Polling before provider turns, dispatch, after tool completion, and before
  settlement.
- Compatible input append-once and host preemption/cancellation choreography.
- Atomic idempotent conclusion/checkpoint settlement and idempotent cleanup
  release with no successor arming.
- Host-authored stopped conclusions for deterministic no-progress exits.
- Durable attempt number and pre-I/O no-progress ceiling.
- Durable pre-I/O admission reservation, clean settlement/refund, and startup
  release of orphaned concurrency without refunding rolling turn/token charge.
- Circuit-breaker/parking behavior for configuration defects.
- Multi-run, restart, race, and crash-order fixtures, including ordinary input
  arriving during finalization.

The package still supplies no database implementation. A conformance host must
prove canonical recovery scanning and the required durable semantics.

Exit: K037–K045 pass.

## Slice 4: one-shot, assurance, and release

Deliver:

- Isolated structured one-shot façade rejecting every `Write` plan.
- Fresh-session/finally-close behavior with no thread-state port access.
- Default-private tracing and opt-in redacted diagnostics.
- Full deterministic seam matrix and an opt-in paid live qualification suite.
- Evidence containing dependency revisions, request shape, route, status,
  normalized usage, and trace IDs but no private payload.
- Package build, type check, lint, dependency audit, and release checklist.
- One real Jarvis integration and boundary review before 0.1.0.

Exit: K046–K052 pass.

## Explicitly deferred

- Stateless root provider generation.
- Provider-native and MCP application tools.
- Parallel or multi-call model steps.
- Model-authored progress delivery.
- Generic durable observed-value storage.
- Semantic tool discovery in the kernel.
- Lua, QuickJS, WASM, CodeAct, or other model-authored program runtimes.
- General delegation, persistent peers, task trees, join, and cancellation
  propagation.
- Kernel-owned SQL, queues, workflows, schedulers, or distributed leases.
