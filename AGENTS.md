# Repository instructions

This repository specifies and, after an explicit implementation request, will
contain `llm-agent-kernel`, imported as `llm_agent_kernel`.

## Current phase

- Runtime implementation has been explicitly authorized. Follow the slices and
  acceptance gates; do not skip a boundary because a later slice needs it.
- `SPEC.md` is normative. Architecture, acceptance, slices, and ADRs must agree
  with it.
- The public `llm-tools` seams in SPEC section 2 are qualified at a durable
  remote revision. Lock that exact pin; never substitute a mutable sibling
  worktree.

## Permanent boundaries

- Target Python 3.12 or newer.
- Use only `provider_runtime.agent_runtime.AgentRuntime` for v1 provider work.
- Use `llm-tools` for prompt sections, tool declarations, frozen profiles and
  plans, pure schema validation, execution, tool budgets, positions, replay,
  recorders, and results.
- Own provider-neutral orchestration: definitions, containment fingerprints,
  context projections, strict steps, serial loops, polling, admission,
  cancellation, ports, outcomes, and conformance tests.
- Own no application table, migration, workflow engine, queue, scheduler,
  connector, credential store, memory system, approval policy, delivery path,
  action ledger, effect identity, or reconciliation procedure.
- Do not duplicate provider SDK integration or any `llm-tools` registry,
  executor, budget, recorder, discovery implementation, or renderer.
- V1 has no program runtime, parallel/multi-call step, model-authored progress
  channel, provider-native application tool, MCP application tool, or delegation
  graph.

## Invariants

- Exact model grammar: one closed `say`, `call_tool`, or `finish` value.
- Validate the whole step and pure tool input before output or dispatch.
- Exactly one serial tool call per model step; model supplies no call/effect ID.
- Thread dispatch carries immutable claim, checkpoint, ordered input, and
  model-step lineage; isolated dispatch carries run and step identity. The
  kernel neither interprets nor persists either form.
- Native Codex built-ins and Web are disabled; cwd is private, empty, and
  read-only; network, copied environment, MCP, and approvals are disabled.
- Consume `AgentRuntime.stream_turn` directly; never use the event-discarding
  `run_turn` projection. Fail-stop and discard the session on any
  provider-native tool or permission event.
- The complete native session policy is part of the definition fingerprint.
- Effective authority is the intersection of provider containment and the
  host-selected frozen plan. Before rendering or I/O, prove the exact
  plan/catalog view is internally consistent and tightens the definition
  maximum; comparing profiles alone is insufficient.
- Every tool binding has a non-empty owner-controlled implementation revision
  covering its handler and transitive execution behavior. Bump it when that
  behavior changes unless revisioned policy inputs already capture the change.
- `KernelLimits` and `llm_tools.RunLimits` are distinct. Never double-account a
  tool call, attempt, byte, deadline, or replay.
- `Write` requires a host-created durable action/effect record whose stable ID
  is both `InvocationPosition` and `EffectId`.
- Suspension is a durable host boundary. The later resolution supplies original
  validated arguments and evidence; provider history is not canonical.
- Poll compatible input before provider turns, dispatch, after completion, and
  before settlement. Incompatible input remains unclaimed.
- No claim may be empty. No cleanup path automatically rearms unconsumed input.
- Deterministic no-progress stops consume poison input. Crashes are bounded by
  durable attempt counting and host-issued rolling admission before provider
  I/O.
- Admission reserves maximum turn/token capacity and one live slot per root work
  epoch before provider I/O. A strictly serial child one-shot may share that
  slot only when the parent reservation includes its capacity. Clean exits
  refund unused capacity; crash recovery releases only the orphaned slot and
  retains its rolling capacity charge.
- Store a successful returned session reference by generation CAS before acting
  on the model step. A stale CAS permits no dispatch or settlement.
- Provider sessions are disposable; canonical host context must cold-bootstrap
  useful work.
- XML-like formatting is provenance and structure, never a security boundary.

## Change rules

- Prefer the smallest reusable contract proven by a real consumer.
- New persistent-state requirements, provider/tool ownership, workflow
  semantics, program execution, or delegation require an ADR.
- Do not hide operational stores behind “no schema” or “adapter” language.
- A second consumer is required before generalizing a Jarvis-only concern.
- Keep acceptance IDs unique and assigned to exactly one slice.
- Verify relative links, anchors, dependency claims, and terminology after every
  material documentation edit.
