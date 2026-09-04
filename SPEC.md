# llm-agent-kernel v1 specification

Normative terms **MUST**, **MUST NOT**, **SHOULD**, and **MAY** have their usual
RFC 2119 meanings.

## 1. Goals

V1 provides a reusable Python 3.12 kernel that:

1. Runs a bounded model/tool loop over host-owned durable input.
2. Uses the real subscription-backed Codex session API shipped by
   `provider-runtime`.
3. Validates one complete structured model step before displaying text or
   dispatching a tool.
4. Allows exactly one serial host tool call per model step.
5. Lets newly arrived compatible human input steer a running loop.
6. Makes provider sessions disposable and cold-bootstrapable from canonical
   host context.
7. Preserves host ownership of authority, persistence, approval, delivery,
   scheduling, effect identity, and reconciliation.
8. Bounds repeated work across runs as well as work inside one run.
9. Owns no application database schema or workflow engine.

V1 is a small control plane for trustworthy personal agents, not a general
workflow system, tool platform, or persistent multi-agent graph.

## 2. Dependencies and implementation gate

The distribution is `llm-agent-kernel`; applications import
`llm_agent_kernel`. It supports Python 3.12 and newer.

The reviewed dependency baseline is:

- `provider-runtime` from the `llm-calling` repository:
  `a5d9c8e0c1c851daee0731554e0a4a326d3c2819`
- `llm-tools`: `05f89e238f52fbc69e83d9aacea1bcf2d8e6de88`
- The provider-certified Codex SDK/runtime pair: `openai-codex==0.144.4`

The provider baseline is usable without modification. V1 selects only
`provider_runtime.agent_runtime.AgentRuntime`; it does not use the stateless
root `ProviderRuntime.generate` lane. The kernel distribution directly pins the
Codex SDK version certified by that immutable provider revision so a later
transitive release cannot silently invalidate the native-tool containment
qualification.

The reviewed `llm-tools` revision exposes and qualifies the public seams this
kernel needs:

1. Pure strict input validation that performs no position occupation, budget
   reservation, recorder write, or dispatch.
2. A public proof that one frozen tool plan is internally consistent with its
   catalog view and tightens a maximum frozen capability profile, including
   exposed bindings, grants, limits, contract revisions, implementation
   revisions, and policy revisions. Freezing and publication MUST reject a
   catalog view whose tool, implementation, or policy revision does not exactly
   match the corresponding frozen grant.
3. A public `HostTable` publication/rendering contract for the tools represented
   to a model through structured host prompts rather than provider-native tools.
4. An asynchronous durable execution/recorder path suitable for an async host,
   without blocking the event loop on persistent recorder operations.

The qualified revision preserves `ToolEffect`, `ReplayPolicy`,
`FrozenToolPlan`, `InvocationPosition`, `EffectId`, recorder uncertainty,
position conflict, and tool-budget behavior. Its conformance suite includes
adversarial cross-catalog substitution and direct inconsistent-plan tests at
construction, proof, publication, and execution. The immutable revision is
fetchable from the configured remote; the package resolver MUST lock that exact
commit rather than import from a sibling worktree.

That revision also owns the corrected `web.search` whole-operation deadline.
`bind_brave_web_search` accepts a positive finite
`operation_deadline_seconds`, defaulting to and capped at 12 seconds inside the
declared 15-second executor deadline. The inner deadline covers every provider
attempt and retry delay and is frozen into binding policy identity. A custom
`WebSearchProvider.search` implementation MUST accept the optional keyword-only
`attempt_started` callback, invoke it synchronously once immediately before
each external attempt, and propagate task cancellation unchanged. Expected
inner expiry becomes the declared `UpstreamUnavailable` result with the actual
started-attempt count; unexpected outer timeout and cancellation retain the
existing executor replay and uncertainty semantics. The kernel neither starts
nor separately accounts this tool deadline.

The kernel MUST NOT import a private dependency module to bypass a missing
public seam. It MUST NOT duplicate provider SDK integration, tool execution,
schema compilation, prompt-section rendering, or recorder semantics.

## 3. Ownership

### 3.1 Provider-runtime owns

- Codex local-account authentication.
- Native session creation, resume, turns, interruption, references, and close.
- Session-scoped `PermissionPolicy`, native options, model, reasoning, cwd, and
  structured-output lowering.
- Strict parsing of the provider's declared JSON-schema output.
- Normalized events, usage when available, quota exhaustion, and typed provider
  failures.
- Child process, private state-root, environment, and sandbox lifecycle.

### 3.2 llm-tools owns

- Tool declarations, bindings, catalogs, frozen profiles and plans, including
  plan/catalog consistency and tightening proofs.
- `ToolEffect` (`Pure`, `Read`, `Write`) and orthogonal `ReplayPolicy`
  (`BilledOnce`, `ReDispatchable`).
- Tool schemas and pure strict argument validation.
- Tool-call, attempt, input/output-byte, concurrency, and elapsed execution
  budgets through `llm_tools.RunLimits`.
- Invocation-position occupation, recorder protocol, replay memoization,
  uncertainty poisoning, execution, result envelopes, and prompt sections.

`llm-tools` requires a stable effect ID and durable recorder for `Write`; it does
not mint application effect IDs, reconcile an external effect, resolve an
uncertain position, or decide product authority.

### 3.3 The kernel owns

- Immutable agent definitions and deterministic fingerprints.
- Plan-aware construction and exact-limit verification of the dependency-owned
  tool budget.
- Provider containment requirements and the proof that a run plan tightens the
  definition's maximum profile.
- The closed logical model-step grammar, its Codex-compatible provider-wire
  envelope, structured-result schema compilation, and semantic output-contract
  validation.
- Provider-neutral bootstrap and continuation context choreography.
- The bounded serial model/tool loop, polling choreography, cancellation, and
  kernel-level limits.
- Provider-session and host input/checkpoint ports.
- Run outcomes, accumulated provider usage, and conformance tests.

### 3.4 The host application owns

- Canonical input, conversation history, conclusions, and delivery.
- Input selection, prioritization, compatibility, and the frozen plan chosen for
  each claimed batch.
- Run admission and durable no-progress attempt accounting.
- Product context and retrieval.
- Tool composition, credentials, policy, approval, action state, effect-ID
  minting, durable recorder implementation, and reconciliation.
- Schedules, background work, privacy, retention, and user experience.

The kernel owns no table, migration, queue, outbox, connector, memory store,
approval matrix, or effect ledger. This is not a claim that a consumer needs no
durable state. A continuing consumer with writes normally needs at least:

1. Canonical input/conclusion/checkpoint and delivery state.
2. Disposable provider-session reference state.
3. A durable `llm-tools` recorder/effect record for writes.

## 4. Core values

### 4.1 AgentDefinition

An `AgentDefinition` is immutable configuration containing:

- Stable definition ID and role instructions.
- Stable provider-neutral prompt sections.
- `SessionMode`: `continuing` or `isolated`.
- `OutputContract`: `conversational` or one closed, provider-representable
  structured result type.
- A maximum frozen `llm-tools` capability profile.
- Exact session-scoped provider configuration.
- A required, non-empty, owner-controlled `session_compatibility_revision`.
- `KernelLimits`.

The provider configuration for the v1 Codex route includes backend, transport,
credential profile identity, model, reasoning, system/developer material,
output schema, cwd scope, additional directories, MCP configuration,
`PermissionPolicy`, and `CodexNativeOptions`.

The deterministic definition fingerprint covers every value that can change a
native session's meaning or containment, including the exact
`session_compatibility_revision`. The owner MUST rotate that revision when an
application, kernel, or provider-runtime semantic change makes saved sessions
incompatible even if no other serialized definition field changed. It excludes
credential secret bytes, current input, dynamic context, the per-run plan, and
host time. Any change to a covered value rotates the session and forces
bootstrap.

### 4.2 RunPlan

Each invocation receives one frozen `llm-tools` plan with `HostTable` exposure.
Before provider or tool I/O, the kernel uses the qualified public dependency
predicate to prove both that the plan is internally consistent with the exact
catalog view it will publish and that the entire plan tightens the definition's
maximum profile. Comparing the embedded profiles alone is insufficient. The
published effect, schemas, replay policy, implementation revision, contract
revision, and policy revision MUST be the values covered by that proof. Any
mismatch fails before rendering or provider/tool I/O. The plan MUST set
`max_in_flight = 1`.

Every binding MUST declare a non-empty owner-controlled
`implementation_revision` covering its handler and transitive execution
behavior. A handler or behavior-affecting dependency change requires a revision
bump unless that change is already represented by revisioned `policy_inputs`.
The revision is identity and recovery evidence, not a claim that code was
automatically hashed or independently attested.

The plan is fixed for the invocation. A model cannot discover, add, widen, or
reclassify tools. Tool descriptions in model context describe the plan; they do
not grant authority. A proposed tool absent from the plan is protocol-invalid
and dispatches nothing.

The caller supplies a `ToolBudgetFactoryPort`, not a `BudgetState` constructed
from out-of-band plan knowledge. After `claim` returns and the kernel validates
the exact selected plan, the kernel calls `create(plan)` once for a run that can
proceed. The returned `BudgetState.limits` MUST equal the claimed plan's
`profile.run_limits`; a mismatch parks thread input or rejects an isolated run
before context rendering, admission, provider I/O, or tool I/O. The factory
does not transfer ownership of tool accounting to the kernel: the returned
state and `llm-tools` executor retain that responsibility.

### 4.3 ApplicationThread and InputClaim

An application thread is a host-owned durable workstream identified by an
opaque `thread_id`. It is not a provider session.

The host claims one non-empty, bounded batch and returns an `InputClaim` with:

- An opaque stable `claim_id`.
- One or more ordered host inputs, each with an opaque stable `input_id`.
- An opaque consumed checkpoint.
- Source timestamps and one host `as_of` value.
- The frozen run plan selected by host policy.
- A durable no-progress attempt number for the oldest logical input.

The host chooses batching, priority, and compatibility. The kernel neither
defines a `run_class` nor infers authority from input text. The plan is still
independently proven inside the definition maximum before I/O.

### 4.4 Run and model turn

A run is one bounded invocation over one claim. It may perform several provider
turns and serial tool calls but does not silently start a fresh-budget successor
over the same failed input.

A provider turn is one complete consumption of an `AgentRuntime.stream_turn`
event stream. A model step is the one validated structured value returned by
its successful terminal event. The convenience `AgentRuntime.run_turn` method
MUST NOT be used: it consumes and discards the intermediate events that the
kernel must inspect to enforce containment.

An isolated one-shot has explicit host input, no application claim/checkpoint or
saved session reference, a fresh native session, a structured output contract,
and no `Write` tool. Its result is not durable until its caller commits it.

## 5. Exact provider surface and containment

### 5.1 Selected lane

V1 uses only:

```text
provider_runtime.agent_runtime.AgentRuntime
  open_session(AgentSessionRequest)
  stream_turn(AgentSession, TurnRequest)
  close_session(AgentSession)
```

These are public dependency APIs. The adapter MUST consume every event yielded
by `stream_turn`; it MUST NOT call the convenience `run_turn` projection in
production or infer event history from its terminal. The adapter returns a
terminal to the kernel only after observing a well-formed stream through that
terminal.

The adapter MUST represent the kernel provider-wire envelope through
`JsonSchemaAgentOutput`. The root is one closed object, not a discriminated
union. Every property of every object is required, and inactive/optional values
are explicit nulls. Jarvis tools are not provider-native tools and are not MCP
tools. `mcp_servers` MUST be empty.

The Codex request MUST use:

- `backend = "codex"` and the qualified SDK transport.
- Local-account credential reference.
- A private empty absolute cwd with read-only filesystem policy.
- No additional directories.
- Network disabled.
- Approval mode `deny`.
- Empty copied environment.
- The exact Codex `allowed_tools` sentinel required by the pinned runtime, while
  separately setting `CodexNativeOptions(builtin_tools="disabled")`.
- Native Web search disabled.

The sentinel reflects a limitation in Codex's public SDK; it is not authority.
Safety is the conjunction of native-feature disablement, empty read-only cwd,
disabled network/environment, denial of provider approval, and host refusal to
accept native tool activity.

Any `AgentToolUse` or `AgentPermissionRequest` event fails the provider turn,
discards its session, dispatches no host tool, and commits no model-authored
conclusion. `AgentText` chunks are never delivered as conversational output;
only a validated terminal structured step may be displayed.

### 5.2 ProviderSessionPort

The provider adapter exposes the native resource lifecycle rather than
pretending it is a stateless call:

```text
acquire_continuing(definition, saved_ref | none) -> live session lease
open_isolated(definition) -> live isolated session lease
run_observed_turn(lease, typed content, cancellation) -> AgentTerminal
release(lease) -> return continuing session to host cache
discard(lease) -> close and invalidate session
close(lease) -> close isolated or retired session
```

`run_observed_turn` is a kernel port operation, not a wrapper around
`AgentRuntime.run_turn`: its implementation drives `AgentRuntime.stream_turn`,
suppresses text chunks, accumulates usage, and inspects every event. On a native
tool-use or permission-request event it taints and discards the session and
returns no terminal or model-authored output to the loop.

The host MAY retain a continuing live session between runs for latency and
provider caching. A lease permits one active turn. Shutdown closes every live
session. Isolated sessions are always closed in a `finally` path.

`AgentQuotaExhausted` maps to the distinct `quota_exhausted` run outcome and is
never retried or replaced with another provider. Expected provider failures are
mapped explicitly; runtime invariant violations remain defects.

### 5.3 SessionRefPort

Continuing session references are disposable but generation-checked:

```text
load(thread_id, definition_fingerprint)
  -> none | stored(ref, generation)
compare_and_set(thread_id, definition_fingerprint,
                expected_generation | none, new_ref)
  -> stored(new_generation) | stale
discard(thread_id, definition_fingerprint, expected_generation | none)
  -> discarded | stale
```

The first store uses `expected_generation = none`. Every successful store
returns the generation required for the next store. A stale result is a
`configuration_error`/ownership defect: no tool dispatch or conclusion from
that terminal may proceed.

After every successful provider turn, the kernel stores the returned
`AgentSessionRef` before acting on its model step. If the later tool or canonical
settlement boundary is interrupted, host input remains unconsumed and recovery
discards the speculative reference before replay. This ordering prevents a
committed conclusion from being absent from the next resumed session.

A missing, invalid, incompatible, or unresumable reference causes one cold
bootstrap, never canonical data loss. The adapter owns live open/resume/close;
the session-reference store owns only serialized refs and generations.

## 6. Structured model protocol

### 6.1 Grammar

The complete model response is exactly one closed variant:

```text
say
  text

call_tool
  canonical tool_id
  arguments

finish
  optional internal reason
  result only as required by the definition output contract
```

Unknown fields, mixed variants, trailing prose, empty `say`, and model-authored
call IDs, authority labels, previews, credentials, effect IDs, approval
instructions, or delivery instructions are forbidden.

Conversational definitions allow `say` and `finish` without a result.
Structured definitions forbid `say` and require `finish.result` to validate
against their closed result type.

The logical variants above are distinct from the provider wire. Codex receives
one closed envelope object with four required properties: `type`, `say`,
`call_tool`, and `finish`. Exactly one payload selected by `type` is non-null;
the other payloads are null. A conversational `finish.reason` is a required
nullable value. A structured `finish` additionally carries the compiled result
object, and the `say` payload is constrained to null.

The provider-wire `call_tool.arguments` value is a string containing one strict
JSON object. This avoids an arbitrary map schema, because Codex Structured
Outputs does not permit schema-valued `additionalProperties`. Before logical
tool validation, the kernel rejects duplicate keys, non-finite constants,
trailing data, and non-object argument values, then supplies the decoded object
to the unchanged pure `llm-tools` validator. The model still supplies no call
or effect identity.

At `StructuredOutput` construction, the kernel compiles Pydantic's result
schema into the supported strict subset: every object stays closed, every
property becomes required, optional values remain explicit (normally nullable),
definitions are preserved, and non-validating defaults/generator annotations
are removed. Map-shaped objects, unsupported semantic keywords, invalid local
definitions, and supported-subset size/depth violations fail deterministically
before an `AgentDefinition` can open or run a provider session. The original
result type remains the authority for independent semantic revalidation.

### 6.2 Whole-step validation

Before display or dispatch, the kernel MUST:

1. Require `AgentTerminal(status="succeeded")` with structured output.
2. Revalidate and decode the complete closed provider-wire envelope, including
   its exactly one selected payload.
3. Revalidate the decoded value through the kernel-owned closed logical step
   model, even though `provider-runtime` already enforced the wire schema.
4. Apply the frozen output contract.
5. For `call_tool`, resolve the exact binding from the frozen HostTable plan.
6. Validate its decoded arguments through the qualified pure public `llm-tools`
   validation seam.
7. Confirm remaining kernel budget. The `llm-tools` executor independently owns
   and enforces the frozen plan's remaining tool budget at dispatch.

Failure of any check produces no visible model text, no position occupation,
and no tool call. A bounded protocol correction may be supplied to the next
provider turn. Exceeding the repair allowance ends the run; it is not rearmed
with fresh repair budget.

Whole-step atomicity covers validation. It does not pretend external effects
form a transaction.

### 6.3 Step behavior

- `say` proposes conversational text for host settlement and delivery.
- `finish` proposes a silent conversational conclusion or a structured one-shot
  result.
- `call_tool` proposes exactly one serial host call. Its observation becomes
  input to a later provider turn; the model may then produce a truthful `say`.

V1 deliberately has no nonterminal narration step. Long tool loops expose
host-owned typing/activity state but no model-authored progress prose. Adding a
durable progress channel is a later product decision.

## 7. Tool boundary

### 7.1 Serial execution and positions

Parallel and multi-call dispatch do not exist in v1. This removes partial
outcome vectors, not-initiated suffixes, and multiple unresolved effects.

`ToolDispatchPort` receives the validated binding, validated input, the budget
constructed from the exact validated plan, cancellation token, and immutable
dispatch lineage. A thread
`DispatchLineage` contains:

- The stable `claim_id`.
- The current opaque `through_checkpoint`.
- The ordered `input_id` values admitted through that checkpoint.
- The model-step ordinal within the claim.

An isolated one-shot instead carries its run ID and model-step ordinal; it has
no application claim, checkpoint, or input identities. The kernel does not
interpret or persist lineage. It supplies the lineage that was true immediately
before dispatch so the host can bind a durable effect to every thread input
that preceded it, including input appended mid-loop. The host supplies
`llm-tools` with an `InvocationPosition`:

- For a `Write`, host code first creates or resolves its durable effect/action
  record and uses that stable record ID for both `InvocationPosition` and
  `EffectId`.
- For `Pure` or `Read`, the host may use an attempt-scoped position and a
  non-durable recorder. A `BilledOnce` read may therefore be billed again after
  a crash or discarded one-shot; this is an accepted v1 cost, not an
  exactly-once claim.

Invocation positions MUST be unique for distinct calls and stable whenever a
call may be resumed or replayed. A same-position/different-input conflict is a
host defect and never a reason to dispatch.

### 7.2 Dispatch result

The dispatcher returns one of:

```text
completed(llm_tools ToolResult)
suspended(host_ref, waiting_for = user | system)
```

Expected tool successes and declared/boundary failures use the closed
`llm-tools` result envelope. Executor configuration, position conflict, broken
binding, recorder, or adapter failures raise a typed defect; they are never
misrepresented to the model as an ordinary tool failure.

`suspended(..., user)` means the host durably accepted work that requires a
human decision. `suspended(..., system)` means the host durably accepted work
whose reconciliation or completion continues without human action. Neither is
called `uncertain`. Terminal uncertainty is a later host-owned resolution after
the binding's reconciliation procedure is exhausted.

A suspension settles the current input, releases every live resource, and
returns. A later host input contains the opaque reference, tool ID, original
validated arguments, resolution state, and safe result/evidence. The kernel
does not define an approval-specific input type or action status vocabulary.

### 7.3 Observation bounds

Tool bindings MUST produce bounded results under their declared
`llm_tools.RunLimits`. Connector families SHOULD return bounded previews,
pagination or stable source references, and typed `TooLarge`/boundary guidance
rather than oversized payloads.

The kernel maintains one cumulative bound over the UTF-8 bytes of model-visible
material it newly renders and submits during the current invocation. This
includes its bootstrap or run delta, appended-input deltas, tool observations,
protocol corrections, and any cold-bootstrap replay rendered in that run.
Provider system/developer material, JSON-schema transport overhead, history
already retained by a native session, and provider compaction are outside this
counter and MUST NOT be described as covered by it. When older recomputable read
observations must be omitted, the kernel inserts an explicit omission marker and
preserves stable source references supplied by the host. It MUST NOT silently
truncate an action outcome, approval payload, or uncertainty evidence.

A generic durable observed-value store is not a v1 kernel requirement. It may be
added by a host when source-specific reread/pagination is insufficient.

## 8. Context and steering

### 8.1 Provider-neutral context

`ContextSourcePort` supplies typed sections for:

- Stable role instructions and application context.
- Bounded canonical completed history.
- Current claimed host inputs with identities and source timestamps.
- Retrieved context selected by the host.
- The exact frozen HostTable plan and tool documentation.
- Host timezone or other stable locale context when relevant.
- One `as_of` value for each newly admitted host-input batch.

`llm-tools` renders typed prompt sections. XML-like presentation is structure and
provenance, never a security boundary. Human input, retrieved memory, tool
observations, connector content, and public Web content remain untrusted data.
In-plan automatic tools can still be induced by malicious data; approval and
containment limit authority, not prompt interpretation.

### 8.2 Continuation and bootstrap

A healthy continuing session receives only material not already sent to it:
newly claimed or polled host input, tool observations, protocol corrections, and
refreshed dynamic context. Each host input appears once in that session.

A cold bootstrap includes stable instructions, bounded canonical completed
history, retrieved context, current unresolved host input, the current plan, and
explicit omission markers. It need not reconstruct provider reasoning or
turn-local read observations byte-for-byte. Reads may be repeated. Durable
effect arguments and outcomes must come from host action state, never solely
from the discarded provider transcript.

### 8.3 Mid-loop polling

Before every provider turn, before tool dispatch, after tool completion, and
immediately before settlement, the kernel calls:

```text
poll(claim, through_checkpoint)
  -> none
   | append(compatible_inputs, new_checkpoint, new_as_of)
   | preempt(reason)
```

`append` inputs MUST be non-empty, ordered, and compatible with the already
frozen plan according to host policy. They extend the claim/checkpoint and are
sent to the provider exactly once. A new `as_of` accompanies the appended batch;
ordinary tool continuations do not receive a repeated clock.

`preempt` stops before another provider turn or tool dispatch. The host decides
which input types preempt and how the interrupted input is concluded. The
cancellation token may be triggered immediately by ingress while an external
call is in flight; cancellation cannot undo an effect already committed.

Inputs incompatible with the current plan remain unclaimed for a later run.
The host may prioritize interactive input over scheduled/background work.

## 9. Checkpoint, settlement, and recovery

### 9.1 InputCheckpointPort

```text
claim(thread_id, owner_token)
  -> no_work | busy | deferred(until) | claim(InputClaim)
poll(claim, through_checkpoint) -> poll result
settle(claim, through_checkpoint, host_conclusion)
  -> idle | more_input
release(claim, reason) -> released | already_released
park(claim, reason) -> parked | already_parked
```

`claim` MUST never return an empty batch. `no_work` calls no provider. The host
MUST persist input before signalling work and MUST make startup/recovery scan the
same canonical unconsumed input.

`settle` atomically and idempotently persists the host-owned conclusion,
advances consumption through the checkpoint, and determines whether other input
remains. It releases the claim. If it returns `more_input`, the host signals the
next run after commit; correctness rests on canonical unconsumed input plus
startup/recovery scanning, not an impossible atomic transaction spanning a
database and an out-of-process trigger.

V1 commits a valid conversational conclusion for its claimed input even if an
ordinary follow-up arrived during finalization, then processes that follow-up in
the next run. It does not discard a paid answer and ask the model to rewrite it.
Exact host stop/pause controls may preempt before settlement. This UX trade-off
is deliberate.

`release` is cleanup for shutdown, invariant defects, or an interrupted host
boundary. It never arms a successor by itself. The input remains visibly
unconsumed for explicit recovery.

`park` atomically releases claim ownership into a durable operator-only state
and trips the applicable circuit breaker. It is the configuration-defect exit;
normal startup scanning cannot reclaim parked input until operator correction.

### 9.2 No-progress stops

The following deterministic stops MUST settle a host-authored stopped
conclusion and consume the current claimed input:

- Exhausted protocol-repair allowance.
- Kernel model-step or cooperative elapsed-limit exhaustion.
- Provider quota exhaustion.
- Explicit owner cancellation/stop when host policy says the input is complete.
- A repeated provider failure after the one permitted safe bootstrap fallback.

They MUST NOT automatically rearm the same logical input. Configuration defects
park the input, trip the host circuit breaker, and require operator correction;
they do not become model-visible tool failures.

A process interruption may leave the claim unconsumed. The host supplies a
durable attempt number on the next claim. Once the configured no-progress
attempt ceiling is exceeded, admission persists a stopped/parked conclusion
without calling the provider.

### 9.3 Run admission

Per-run limits do not bound a system that can start unlimited runs. Every thread
run therefore requires a host-issued `AdmissionToken` proving that a rolling
admission policy was checked before provider I/O. An isolated one-shot MUST also
be covered by host admission: it either receives its own token or a child token
whose turn/token allowance was already reserved by a serial parent invocation.
It has no admission retry state; denial returns to its caller without provider
I/O.

The host policy MUST bound, per deployment or thread and rolling window:

- Started provider turns.
- Available input/output token usage.
- Consecutive no-progress attempts for one logical input.
- Concurrent cognitive work.

It MAY additionally bound estimated monetary cost when the provider surface
exposes a priceable call. The subscription-backed AgentRuntime lane does not
produce root-lane `CallMeta` and is not treated as per-token billable; it uses
turn/token ceilings and `AgentQuotaExhausted` instead.

Before provider I/O, the host MUST durably reserve against the rolling policy:

- One live cognitive-work slot for the exclusive root work epoch. A serial child
  one-shot MAY share that slot only while its parent cannot perform provider or
  tool I/O and only when its capacity was included in the root reservation.
- The run's maximum remaining provider turns.
- The route's configured input/output-token allowance when that usage dimension
  is available.

Because `AgentRuntime` reports tokens only after a turn and exposes no hard
per-turn token cap, the host MAY issue a token reserving more than the requested
allowance. A production host MUST configure that conservative excess from the
route's qualified finite context/output bounds so one terminal report cannot
exceed its reservation. The kernel still stops when reported cumulative usage
crosses `KernelLimits`; the excess is admission capacity, not extra run budget.

The resulting `AdmissionToken` identifies the run, rolling window, reserved
capacity, and reservation state. A clean exit settles actual available usage
and refunds unused capacity in `finally`, including ordinary failure and
cancellation. Process death is charged conservatively: the full turn/token
reservation remains consumed until its rolling window expires. During startup
under the host's exclusive deployment/ownership lock, an orphaned in-flight
reservation is marked interrupted and its live concurrency slot is released;
its turn/token charge is not refunded. A missing or corrupt admission journal
fails closed until explicit host repair.

A denied admission calls no provider. Host policy either returns
`deferred(until)` while leaving canonical input unconsumed, or persists a
visible stopped conclusion. The host, not the kernel, owns deferred-work
signalling, notification, and recovery scanning.

## 10. Kernel limits and cancellation

`KernelLimits` is distinct from `llm_tools.RunLimits`. It contains finite
defaults for:

- Provider turns per run.
- Protocol-repair turns per run.
- Cooperative elapsed duration at safe boundaries and the hard deadline passed
  to each provider turn.
- Provider input/output usage when the selected route reports it.
- Cumulative bytes of kernel-rendered model-visible material newly submitted in
  the current invocation.

Tool calls, attempts, tool input/output bytes, tool concurrency, and tool
deadlines remain exclusively in the frozen plan's `llm_tools.RunLimits`. The
kernel MUST NOT maintain a second tool budget or charge a replay twice.

`KernelLimits.max_cooperative_seconds` is not a hard total wall-clock guarantee.
The clock starts at invocation entry; the kernel observes it at safe boundaries
and passes the remaining duration to the provider turn. A host claim, context
source, poll, session-reference operation, admission operation, dispatch,
settlement, release, park, usage settlement, or cleanup may return after that
duration. At the next safe boundary the kernel prevents further provider/tool
work when possible, but it does not interrupt a host operation or pretend that
cleanup completed on time. Tool execution is independently governed by the
validated plan's `RunLimits.max_elapsed_seconds`. The kernel MUST NOT place a
blunt outer timeout around a `Write`, because abandoning it outside the
dependency recorder boundary would undermine uncertainty and reconciliation
safety.

Cancellation is cooperative and checked at every provider, polling, dispatch,
and settlement boundary. It is passed into provider and tool adapters. A
cancellation result does not erase a committed external effect and never causes
an unconditional retry.

## 11. Run algorithms

### 11.1 Thread run

The public behavior is equivalent to:

```text
claim one bounded non-empty host batch or return no_work/busy/deferred
verify frozen plan/catalog tightening
construct a fresh tool budget from that plan and verify exact RunLimits
durably reserve admission and verify its token before provider I/O
load/acquire compatible continuing provider session, or cold bootstrap

loop within KernelLimits:
  poll and append compatible host input, or handle preemption
  build only new continuation material, or one cold bootstrap
  consume one complete AgentRuntime streamed turn while inspecting every event
  reject native tool/permission events without projecting a terminal
  map typed terminal failure, or persist returned AgentSessionRef by generation CAS
  validate one complete structured step

  if call_tool:
    poll/preempt before dispatch
    dispatch exactly one validated call serially through host + llm-tools
    if completed:
      retain the bounded observation and continue
    if suspended:
      settle the host-referenced suspension and return suspended

  if say or finish:
    poll once more for stop/preemption
    settle the host-owned conclusion and return completed

on deterministic no-progress stop:
  settle a host-authored stopped conclusion; do not rearm this input

on shutdown/invariant interruption:
  release without arming; canonical unconsumed input drives explicit recovery

always settle/refund admission on clean exit; release the live provider lease
on startup, release only orphaned concurrency slots;
  retain their rolling capacity charge
```

No database transaction remains open across provider or external tool I/O.

### 11.2 One-shot run

An isolated one-shot:

- Requires `SessionMode.isolated` and a structured output contract.
- Requires a HostTable plan containing no `ToolEffect.Write` binding.
- Validates that plan, constructs a fresh budget through
  `ToolBudgetFactoryPort`, and requires exact plan `RunLimits` before rendering,
  admission, provider I/O, or tool I/O.
- Requires a host-issued admission reservation; denial returns to the caller
  without retry or provider I/O.
- Uses a fresh native session and no `InputCheckpointPort`, admission retry
  state, or `SessionRefPort`.
- Uses the same structured step validation, serial tool loop, budgets, and
  cancellation.
- Closes the native session in `finally`.
- Returns only a schema-valid `finish.result` or a typed stop outcome.

`Read + BilledOnce` may be billed again if the caller fails before committing
the result. Provider-internal session state may exist during the invocation but
the kernel never saves its reference or treats it as canonical.

## 12. Outcomes

Thread outcomes are:

- `completed`: current input was durably concluded and consumed.
- `suspended(host_ref, waiting_for)`: host work is durable and a later host
  input will resume product work.
- `no_work`, `busy`, or `deferred(until)`: no provider call began.
- `preempted`: host policy stopped the run for higher-priority input.
- `cancelled`: cancellation stopped the run under its declared settlement rule.
- `budget_exhausted`: a kernel limit stopped and concluded the input.
- `quota_exhausted`: subscription quota stopped and concluded the input.
- `protocol_error`: repair allowance stopped and concluded the input.
- `provider_error`: the selected provider failed after its one safe fallback.
- `configuration_error`: a dependency/port/containment invariant failed and the
  input was parked for operator correction.

Every result includes run ID, provider turns, available normalized token usage,
duration, and whether canonical input was consumed. No outcome implicitly means
"retry me".

One-shot outcomes replace thread states with `completed(structured_result)` or
the applicable typed stop.

## 13. Observability and privacy

Every run has a stable run ID. An optional event sink receives bounded metadata
for claim, admission, provider turn, validation, tool dispatch, suspension,
settlement, usage, cancellation, and terminal outcome. Sink failure is nonfatal
and never acknowledges canonical work.

Default events and logs contain stable IDs, kinds, timings, counts, revisions,
and usage—not prompts, human text, retrieved memory, tool arguments/results,
session refs, credentials, or provider-native payloads. An application may opt
into a separately configured redacted diagnostic transcript; the kernel defines
the configuration and sink boundary but does not require persistence.

Provider-side native session transcripts are unredacted third-party data at
rest under the provider/runtime retention model. Discarding a local session ref
does not promise provider deletion. Consumers MUST state that privacy trade-off.

## 14. Required conformance

The release suite covers both single-run interior behavior and composed seams:

1. Exact `AgentRuntime` request mapping and open/stream/close lifecycle against
   the pinned route; production never calls the event-discarding `run_turn`
   convenience projection.
2. Native built-ins disabled, empty read-only cwd, disabled network/environment,
   approval deny, no MCP, and fail-stop on any native tool/permission event.
3. Codex-compatible provider-wire JSON-schema enforcement plus independent
   envelope decoding, logical-step validation, and output-contract validation.
   Tests audit conversational and structured schemas for an object root, closed
   objects, all-properties-required, explicit nullability, JSON-string tool
   arguments, nested/optional/empty results, unsupported-contract preflight,
   malformed branch combinations, and deterministic fingerprints.
4. Pure argument validation performs no recorder/budget/dispatch operation.
5. Frozen plan/catalog consistency, full-plan tightening, and exact `HostTable`
   exposure are proven before rendering or I/O, including adversarial
   cross-catalog handler-implementation substitution tests.
6. Exactly one serial tool call per model step; no parallel or multi-call path.
7. `Write` execution has stable action-owned position/effect ID, immutable
   claim/checkpoint/input/step lineage, and a durable recorder; conflicts and
   uncertain positions never redispatch blindly.
8. `Pure`/`Read` one-shot behavior and the accepted BilledOnce recomputation
   cost are explicit and tested.
9. Mid-loop human input is polled and appears once before the next model turn;
   stop/preemption prevents later dispatch.
10. Empty claims call no provider; oversized batches are bounded by the host.
11. Valid final text is persisted before delivery; restart delivery is tested by
    the consumer's outbox contract.
12. Session-reference CAS precedes dispatch/settlement; every crash boundary
    either resumes an aligned session or discards it before replay.
13. Suspension preserves the host ref, original tool/arguments, waiting actor,
    and later safe resolution without relying on provider history.
14. Protocol, budget, quota, and explicit-stop outcomes consume the poison input
    and cause zero automatic successor runs for it.
15. Crash recovery cannot exceed the durable no-progress attempt ceiling.
16. Thread runs and isolated one-shots are covered by durable maximum turn/token
    reservations before provider I/O. Each exclusive root work epoch reserves
    one concurrency slot; a strictly serial child may share it only when its
    capacity was reserved by the parent. Clean exits refund unused capacity;
    crash recovery releases only the orphaned live slot and conservatively
    retains the rolling capacity charge.
17. Provider quota, expected failure, invariant defect, executor result, and
    recorder recovery remain distinct.
18. Observation and cumulative-context bounds yield typed failures or explicit
    omission markers, never silent truncation or a successful false result. The
    counter covers exactly the kernel-rendered material newly submitted in that
    invocation and excludes provider configuration/schema overhead, retained
    native history, and provider compaction.
19. A cold bootstrap works after deleting all provider-session state; durable
    effect context comes from the host, while safe reads may repeat.
20. One-shot sessions always close and never touch checkpoint or saved-ref ports.
21. Multi-run integration fixtures cover poison input, cancellation, mid-loop
    steering, suspension/resolution, startup recovery, and rolling admission.
22. Ordinary tests use deterministic fakes; paid live qualification is opt-in
    and records no private payloads.
23. A plan-aware factory runs only after exact plan validation; its returned
    `BudgetState` must carry exactly the plan's `RunLimits` before rendering,
    admission, provider I/O, or tool I/O, for both thread and one-shot runs.
24. The cooperative elapsed limit deadlines provider turns and prevents new
    work at safe boundaries without wrapping host cleanup or a `Write`; tool
    execution remains under its independently frozen `llm-tools` deadline.
25. A non-empty owner-controlled session-compatibility revision participates in
    the definition fingerprint, and mutating it rotates saved-session identity.

## 15. Explicitly deferred

- Stateless root `ProviderRuntime.generate` support.
- Provider-native or MCP application tools.
- Parallel or multi-call model steps.
- Nonterminal model-authored progress delivery.
- Generic durable observed-value storage.
- Tool discovery in the kernel.
- Lua, QuickJS, WASM, CodeAct, or other model-authored program execution.
- General delegation, persistent peer agents, task trees, join, and cancellation
  propagation.
- Kernel-owned SQL, workflow, queue, scheduler, lease, connector, memory, or UI.

Deferred features require measured need, an ADR, and preservation of the
provider containment, plan-tightening, admission, and effect boundaries above.
