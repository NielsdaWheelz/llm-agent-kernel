# Implementation plan

Implementation begins only after an explicit request. Each slice closes one
boundary and passes its assigned acceptance criteria before the next begins.

The 2026-09-09 Nexus implementation is authorized by ADR 0008. Slice 5 owns
K053–K058: first establish the portable behavior reds, then move Nexus's
native-child and ordered-tool choreography into `generation.py`, qualify the
consumer adapters and durable stores, and remove the local duplicate loop.
Preserve the full contained AgentRuntime suite throughout. The library suite
does not replace consumer durability or paid/live qualification.

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
The qualified pin also carries `web.search`'s revisioned whole-operation
deadline, started-attempt callback contract, cancellation propagation, and
policy-identity input without moving tool timing or accounting into the kernel.
It carries `web.read` implementation revision `llm-tools-web-read-v2` and the
`plain-text-v2` and `html-visible-text-v2` extraction locators. The Web
contracts, limits, epochs, policy revisions, and policy inputs remain unchanged,
and dependency canaries recompose, freeze, and publish the affected HostTable
plan from those exact identities.
The immutable revision is recorded in the kernel spec and reachable from the
durable remote; Slice 0 must lock that exact commit rather than import a sibling
worktree.

The exact provider-runtime pin defines `AgentUsage` as a progressive
invocation-to-date snapshot and `AgentTerminal.usage` as invocation-local on
every status. It owns normalization of native cumulative state, including
resume baselines; the kernel adapter only selects the latest/terminal snapshot
and sums one invocation-local value per kernel turn.
It also defines `AgentTerminal.final_text` as the provider-selected
authoritative assistant response. `AgentText` is observational, the last
completed Codex `final_answer` wins, the last phase-unknown completion is the
fallback, and commentary is never executable. Provider-runtime owns that
selection; the kernel does not concatenate or select messages.
The qualified provider-runtime pin
`70e33e99a8c03f0304c9136203c38bade2c5e1cd` owns a WebSocket/Unix-socket
connection to the externally supervised Codex App Server behind the stable
`codex`/`sdk` route, strictly projects native authority including retained
custom-exec, validates protocol shape without native-version admission, and makes unknown protocol
a fatal `ProtocolDefect`. It owns no Codex process, account home, private SDK,
or bundled binary.

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
  envelope over the audited shared App Server protocol.
- Fully fingerprinted `AgentSessionRequest`, `PermissionPolicy`, native options,
  empty cwd lifecycle, and empty environment/MCP/network configuration. Default
  cwds remain private `0500`; explicit group sharing requires a setgid parent,
  inherited group ownership, and mode `0750`.
- One bounded kernel-owned structured-agent base instruction before application
  system material, with immutable revision/digest fingerprint coverage and
  automatic cold-bootstrap rotation.
- Complete stream consumption and event fail-stop for native tool-use or
  permission requests and provider `ProtocolDefect`, plus suppression of
  streaming text delivery.
- Terminal-only logical validation, with a consumer regression proving that
  commentary `AgentText` cannot become a model step or dispatch a tool.
- Latest-progressive-snapshot retention, terminal-usage precedence, exactly-once
  per-turn addition, resumed-history exclusion, and incomplete-usage handling
  without a second native cumulative-delta implementation.
- Live continuing-session leases, isolated lifecycle, shutdown close, and typed
  provider terminal mapping.
- Generation-CAS session-ref port, resume compatibility, speculative-ref
  discard, and session-acquisition fallback before a paid request is armed.
- Provider-neutral continuation and bootstrap sections using qualified
  `llm-tools` rendering and frozen `HostTable` publication.
- Definition-bound model-visible input projection with byte-compatible defaults,
  optional suppression of per-input timestamps, three-state batch `as_of`,
  pre-boundary request validation, and deterministic fingerprint rotation.
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
- Host-owned action/effect identity mapping for `Write` and original decision
  positions for recoverable `Pure`/`Read` behavior.
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
- Conservative retention of token reservations whenever safely attributable
  invocation usage is unavailable.
- Circuit-breaker/parking behavior for configuration defects.
- Multi-run, restart, race, and crash-order fixtures, including ordinary input
  arriving during finalization.

The package still supplies no database implementation. A conformance host must
prove canonical recovery scanning and the required durable semantics.

Exit: K037–K045 pass.

## Slice 4: one-shot, assurance, and release

Deliver:

- Isolated structured one-shot façade rejecting every `Write` plan.
- Optional single initial Read with exact plan/binding/input preflight, normal
  dispatcher execution before provider open, one shared plan-aware budget,
  deterministic disjoint isolated positions, and typed first-turn observation.
- Adversarial proof that the prelude is neither a model step nor executable
  commentary and adds no list, retry, hook, dependency graph, or workflow.
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

The accepted [paid-decision extension](../SPEC.md#17-durable-paid-decisions)
adds original request/terminal journaling, explicit isolated recovery policy,
and stable Read positions. Slice 6 owns K059–K064; application durable-store
qualification is required in addition to process-local kernel tests.
