# Acceptance criteria

These criteria are the implementation's release contract. Every ID is
assigned to exactly one implementation slice.

## Dependency and package boundary

- **K001** — The package supports Python 3.12 or newer, imports as
  `llm_agent_kernel`, and performs no I/O or authority grant on import.
- **K002** — Runtime locks qualified immutable git revisions of
  `provider-runtime` and `llm-tools`; ordinary CI never imports mutable sibling
  worktrees.
- **K003** — Before kernel implementation, public `llm-tools` APIs provide pure
  strict input validation, frozen-plan/catalog consistency and tightening
  proof, exact `HostTable` publication/rendering, and async durable
  execution/recording. Every binding has a non-empty owner-controlled
  implementation revision. Freezing and publication reject a view whose
  contract, implementation, or policy revision differs from its frozen grant.
- **K004** — Pure validation performs no position occupation, budget
  reservation, recorder access, or dispatch.
- **K005** — The kernel imports no private dependency module and contains no
  provider SDK adapter, second tool catalog/profile/executor/budget/recorder,
  discovery engine, or prompt renderer.
- **K006** — The package contains no application schema, migration, workflow,
  queue, scheduler, connector, credential resolver, memory store, approval
  policy, delivery implementation, effect ledger, or reconciliation policy.
- **K007** — Public types and fakes do not claim crash durability; documentation
  identifies the canonical host, session-ref, effect-recorder, and admission
  facts a continuing effectful consumer must store.

## Exact provider surface

- **K008** — V1 uses only public
  `provider_runtime.agent_runtime.AgentRuntime` open/stream/close APIs; it does
  not use stateless root generation or the event-discarding `run_turn`
  convenience projection.
- **K009** — The adapter passes the closed kernel step schema through
  `JsonSchemaAgentOutput` and independently revalidates the parsed terminal
  value inside the kernel.
- **K010** — A session request uses subscription Codex with the qualified
  transport, local-account credential reference, private empty absolute cwd,
  read-only filesystem, no additional directories, disabled network, denied
  approvals, empty copied environment, no MCP, disabled native Web, and
  `builtin_tools="disabled"`.
- **K011** — The Codex `allowed_tools=("*",)` sentinel appears only where the
  pinned runtime requires it and is never interpreted as application authority.
- **K012** — The adapter consumes and inspects every `stream_turn` event. Any
  native tool-use or permission-request event fails the turn, discards the
  session, returns no terminal to the loop, dispatches no host tool, and settles
  no model-authored conclusion.
- **K013** — Streaming model text is never delivered; only a successful terminal
  structured step can cross the host output boundary.
- **K014** — Live continuing sessions are acquired/released and may be cached;
  isolated sessions and retired/discarded sessions are always closed, including
  cancellation and failure paths.
- **K015** — Quota exhaustion, expected provider failure, cancellation, resume
  incompatibility, and runtime invariant failure remain distinct. There is at
  most one safe cold-bootstrap fallback before a successful terminal and no
  fallback after host tool dispatch.

## Definitions, plans, sessions, and context

- **K016** — Public values distinguish agent definition, application thread,
  input claim, run, provider turn, model step, provider session, and role.
- **K017** — A definition freezes role/stable context, session mode, output
  contract, maximum frozen capability profile, exact provider configuration,
  and finite `KernelLimits`.
- **K018** — The deterministic fingerprint covers every session-scoped semantic
  and containment value, including `PermissionPolicy` and native options;
  changing any covered value rotates the session. Secret bytes and dynamic
  input are excluded.
- **K019** — Before rendering or provider/tool I/O, a qualified public predicate
  proves that the host-selected frozen plan is internally consistent with its
  exact catalog view, tightens the definition maximum in full, and sets
  `llm_tools.RunLimits.max_in_flight = 1`. Tests reject cross-catalog effect,
  schema, handler-implementation, replay-policy, and revision substitution.
- **K020** — The kernel has no run-class abstraction. The host claim returns one
  non-empty bounded input batch and its already-selected plan; the host owns
  priority, batching, and compatibility.
- **K021** — Session refs are keyed by thread and definition fingerprint and
  stored by generation CAS. The first expected generation is absent; every
  successful store returns the next generation; stale CAS permits neither
  dispatch nor settlement.
- **K022** — Every successful provider terminal's session ref is stored before
  semantic step action. Recovery discards a speculative ref before replaying
  host input left canonically unconsumed.
- **K023** — Context uses provider-neutral `llm-tools` sections. Continuation
  sends each admitted host input once; cold bootstrap reconstructs useful work
  from bounded canonical history, current input, retrieval, plan, and durable
  action state after all provider-session state is deleted.
- **K024** — Each newly admitted input batch carries source timestamps and one
  host `as_of`; timezone/locale is included only when relevant. Ordinary tool
  continuations do not receive a changing ambient clock.

## Protocol and tool boundary

- **K025** — The only model variants are closed `say`, `call_tool`, and `finish`.
  A `call_tool` contains exactly one canonical tool ID and arguments and no
  model-authored call/effect ID, preview, authority, approval, credential, or
  delivery field.
- **K026** — Conversational definitions allow `say` and resultless `finish`;
  structured definitions forbid `say` and require a closed schema-valid
  `finish.result`.
- **K027** — Whole-step, output-contract, frozen-plan, and pure argument
  validation complete before visible output, position occupation, budget
  reservation, recorder mutation, or dispatch.
- **K028** — Invalid output produces no partial effect and at most the configured
  number of bounded protocol corrections; exhaustion settles a host-authored
  stopped conclusion and cannot obtain fresh repair budget automatically.
- **K029** — Exactly one tool executes serially per model step. There is no
  parallel executor, multi-call outcome vector, not-initiated suffix, or second
  kernel tool budget.
- **K030** — `KernelLimits` own provider turns, repairs, wall time, reported
  provider usage, and cumulative model-visible context. The frozen
  `llm_tools.RunLimits` alone own tool calls, attempts, bytes, concurrency, and
  tool elapsed/deadline limits.
- **K031** — Before `Write` executor entry, the host durably creates or resolves
  an action/effect record and uses its stable ID for both `InvocationPosition`
  and `EffectId`. The dispatch exposes immutable claim ID, through-checkpoint,
  ordered admitted-input IDs, and model-step ordinal; conflict or uncertain
  recorder state never blind-redispatches.
- **K032** — `Pure`/`Read` may use attempt-scoped positions and a non-durable
  recorder. Tests and docs expose that `Read + BilledOnce` can be billed again
  after crash or discarded one-shot.
- **K033** — Dispatch returns only completed `llm_tools.ToolResult` or durable
  suspended `(host_ref, waiting_for)`; configuration, recorder, executor, and
  position defects are typed exceptions rather than fabricated tool failures.
- **K034** — Suspension settles the proposing input and releases all live
  resources. A later host input supplies the opaque ref, tool ID, original
  validated arguments, resolution state, and safe evidence without relying on
  provider history or a kernel approval vocabulary.
- **K035** — Bindings return bounded results or typed boundary guidance. The
  kernel caps cumulative visible context, emits explicit omission markers for
  recomputable reads, and never silently truncates effect, approval, or
  reconciliation evidence.
- **K036** — V1 emits no model-authored nonterminal progress prose; the host may
  expose activity/typing state.

## Polling, settlement, and cross-run bounds

- **K037** — At most one claim owns a thread. An empty claim is invalid, and
  `no_work`, `busy`, `deferred`, or denied admission performs no provider I/O.
- **K038** — The kernel polls before provider turns, before dispatch, after tool
  completion, and before settlement. Compatible appended inputs are ordered,
  use the frozen plan, and appear exactly once; incompatible input remains
  unclaimed.
- **K039** — Immediate stop/pause or host preemption prevents later provider/tool
  boundaries where possible and propagates cancellation in flight. Cancellation
  never claims to undo an already committed effect.
- **K040** — `settle` idempotently and atomically persists the host conclusion
  and consumes through the checkpoint. A valid answer is retained when an
  ordinary follow-up races with finalization; that follow-up is signalled and
  handled by a later run.
- **K041** — `release` is idempotent cleanup and never arms a successor.
  Correctness after interruption comes from canonical unconsumed input plus
  explicit startup/recovery scanning.
- **K042** — Protocol exhaustion, kernel-budget exhaustion, quota exhaustion,
  declared stop, and repeated provider failure settle and consume a
  host-authored stopped conclusion. None automatically starts a fresh-budget
  run for the same logical input.
- **K043** — Before provider I/O, every thread run and isolated one-shot is
  covered by durable maximum-turn and configured token reservations. Each root
  work epoch reserves one live cognitive slot; a strictly serial child one-shot
  may share it only when its allowance was included in the parent reservation.
  A clean exit refunds unused capacity; process death retains the full rolling
  turn/token charge.
- **K044** — Crash recovery increments the durable attempt number on the oldest
  logical input. Exceeding its ceiling stops or parks the input before provider
  I/O. Configuration defects park and trip a host circuit breaker rather than
  entering an automatic retry loop.
- **K045** — No database transaction or blocking row lock is held over provider
  or connector I/O; a host signal after `settle(more_input)` is backed by
  canonical recovery scanning rather than treated as an atomic database/worker
  transaction.

## One-shot, privacy, and assurance

- **K046** — An isolated one-shot requires isolated mode, a structured output
  contract, and a plan containing no `ToolEffect.Write`; it uses a fresh native
  session, a host-issued admission reservation, no
  claim/checkpoint/admission-retry/session-ref port, and returns only a valid
  result or typed stop. Admission denial calls no provider and returns to its
  caller without retry.
- **K047** — One-shot sessions always close. Their results remain non-canonical
  until the caller commits them, and provider-internal continuation is never
  saved.
- **K048** — Default traces contain IDs, revisions, timings, counts, usage, and
  outcomes—not prompts, user text, memory, arguments/results, session refs,
  credentials, or provider payloads. Sink failure is nonfatal.
- **K049** — Documentation states that provider-native transcripts are
  unredacted third-party data at rest and discarding a local ref does not promise
  provider deletion.
- **K050** — Deterministic tests inject failures at claim, admission reservation,
  provider terminal, session CAS, validation, recorder/effect commit,
  suspension, settlement, release, and usage settlement/refund boundaries.
- **K051** — Multi-run race tests cover poison input, no automatic rearm,
  attempt-ceiling recovery, rolling admission, mid-loop steering, stop
  preemption, ordinary follow-up finalization, suspension/resolution, and
  startup scanning that releases orphaned concurrency without refunding its
  conservative rolling charge.
- **K052** — Opt-in live qualification exercises the exact pinned AgentRuntime
  request, streamed event, resume, cancellation, quota, and containment
  behavior without running in ordinary CI or recording private payloads. A
  contract test proves that production calls `stream_turn`, never `run_turn`.

## Slice assignment

| Slice | Acceptance IDs |
| --- | --- |
| 0 — dependency truth and package contract | K001–K007 |
| 1 — Codex agent sessions and context | K008–K024 |
| 2 — strict serial protocol and tool boundary | K025–K036 |
| 3 — polling, settlement, and admission | K037–K045 |
| 4 — one-shot, assurance, and release | K046–K052 |
