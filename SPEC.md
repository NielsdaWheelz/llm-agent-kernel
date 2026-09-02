# llm-agent-kernel v1 specification

Normative terms **MUST**, **MUST NOT**, **SHOULD**, and **MAY** have their usual
RFC 2119 meanings.

## 1. Goals

V1 MUST provide a reusable Python 3.12 kernel that:

1. Processes durable application input with one bounded, inspectable loop.
2. Validates an entire model step before displaying text or dispatching tools.
3. Keeps canonical context independent of a provider session.
4. Uses native provider continuation when healthy and reconstructs useful
   context when it is absent.
5. Makes drain ownership, input consumption, and idle transitions race-safe.
6. Preserves application authority over tools, approvals, persistence, and UX.
7. Adds no mandatory persistent schema.

V1 optimizes for a small trustworthy control plane, not a general autonomous
agent platform.

## 2. Scope and ownership

The distribution name is `llm-agent-kernel`; its import package is
`llm_agent_kernel`. It supports Python 3.12.

The kernel depends on:

- `llm-calling` / `provider-runtime` for model calls, provider events, and
  resumable provider sessions.
- `llm-tools` for frozen capability plans, typed prompt sections, schema
  validation, tool execution, durable-effect requirements, and result
  envelopes.

The initial qualification baseline is:

- `llm-calling` / `provider-runtime`:
  `a5d9c8e0c1c851daee0731554e0a4a326d3c2819`
- `llm-tools`: `8df458a199703120005296ae12f997b39d208fed`

Implementation MUST lock qualified git revisions rather than depend on mutable
sibling worktrees. A later upgrade is ordinary dependency work only after the
conformance suite passes against the new pair.

The kernel MUST NOT implement or duplicate either dependency's responsibilities.
In particular, it owns no tool registry, effect recorder, provider
implementation or provider-specific SDK adapter, or XML renderer. Its narrow
provider port is only the orchestration-facing façade over `provider-runtime`.

Applications own all domain policy and state: durable messages and terminal
conclusions, effect/action records, memory, connectors, credentials, approvals,
delivery, schedules, and data retention. The kernel defines ports over that
state, not tables or migrations.
It MUST work with in-memory, file, SQL, or workflow-backed port implementations
without detecting which one is in use.

The v1 package contains no generated-code runtime, Lua interpreter, operating
system sandbox, generic command tool, or subagent/delegation graph. See
[ADR 0004](docs/decisions/0004-defer-program-agents-and-delegation.md).

## 3. Terms and value model

### 3.1 Agent definition

An `AgentDefinition` is immutable configuration with:

- A stable definition ID and deterministic configuration fingerprint.
- A `Role`.
- Stable typed prompt sections.
- An immutable maximum `llm-tools` capability envelope.
- A provider profile reference understood by `provider-runtime`.
- A session mode: `continuing` or `isolated`.
- A context policy.
- An `OutputContract`.
- Explicit `RunLimits`.

Changing session-scoped configuration MUST change the fingerprint. An agent
definition is not an identity-bearing database record, process, thread, or
provider session.

V1 has two output contracts:

- `conversational`: permits `say` and permits `finish` without a result.
- `structured`: forbids user-facing text and requires `finish.result` to match
  one closed host-supplied schema.

The output contract is frozen in the definition and participates in its
fingerprint. It is not selected by the model.

Each run also receives one frozen `llm-tools` capability plan selected by the
application. Before I/O, the kernel MUST prove that every declaration in the
plan is inside the definition's envelope. A run may narrow the envelope but
never expand it. The envelope participates in the definition fingerprint; the
effective plan is current-run context.

### 3.2 Role

A `Role` names a behavioral purpose and its instructions, expected output
behavior, and optional context selectors. A role grants no authority by itself;
effective authority comes only from the frozen per-run plan supplied by the
host within the definition's envelope.

### 3.3 Application thread

An application thread is a host-owned durable workstream with an opaque
`thread_id`, ordered waking inputs, canonical completed history, and a consumed
input checkpoint. It may represent a chat, background cognitive job, or another
serial workstream. It is not a provider chat/session.

Waking input is a typed host value, not necessarily human text. V1 includes a
standard `ActionResolutionInput` carrying an opaque host reference, original
tool ID, resolved state (`executed`, `denied`, `failed`, `uncertain`, or
`cancelled`), and a host-validated observation or receipt. It lets an
application reintroduce an asynchronously resolved dispatch without replaying
the original call or turning its turn-local `call_id` into durable identity. The
application owns its storage and decides whether receipt bodies are safe for
model context.

### 3.4 Run, drain, and one-shot invocation

A run is one host invocation of the kernel. A thread run processes an
application thread. After obtaining an exclusive claim, it enters a drain. The
drain repeatedly consumes eligible waking input and performs model steps until:

- It commits a race-safe idle transition.
- A host dispatch reports pending approval or uncertainty and no newer waking
  input is ready to continue.
- Cancellation is observed.
- A budget is exhausted.
- A non-recoverable provider, protocol, or adapter error occurs.

Only one drain may own a given application thread at a time. A run that cannot
claim it returns `busy` without calling the provider.

Every thread run also has one opaque host-defined `run_class` bound to its
frozen capability plan. The checkpoint adapter MUST expose only the maximal
ordered prefix of waking inputs that the host declares eligible for that class.
A drain MUST NOT cross into a newer input that requires another class or plan:
the adapter arms a run for the next class and the current drain returns
`pending_input`. This preserves input order without allowing a read-only run to
inherit broader work or a broad run to consume narrowly authorized work.

An isolated one-shot run processes explicit host-supplied input without an
application-thread claim, input checkpoint, or saved session reference. It
always opens a fresh provider session and returns one validated terminal
structured conclusion to its caller. V1 one-shot definitions MUST use
`SessionMode.isolated` and a structured output contract. They exist for bounded,
recomputable helper work such as retrieval and summarization; the host decides
whether and how to commit the result. This is not a durable workflow or a second
coordination mechanism.

### 3.5 Model step

A model step is one complete provider response parsed and validated as exactly
one `Step` variant. Streaming deltas and provider reasoning events are not model
steps and MUST NOT be displayed as assistant output.

### 3.6 Provider session

A provider session is an opaque continuation reference owned by
`provider-runtime`. It is a rebuildable optimization for continuity, compaction,
and caching. It MUST NOT be the sole record of waking input, terminal output, or
effect completion. Intermediate read observations may remain turn-local.

## 4. Model-step protocol

### 4.1 Closed grammar

The semantic grammar is this strict discriminated union:

```text
say
  kind: "say"
  text: non-empty string

call_tools
  kind: "call_tools"
  calls: non-empty ordered list
    call_id: non-empty string, unique within the step
    tool: canonical granted tool ID
    arguments: object

finish
  kind: "finish"
  reason: optional string
  result: present only as required by the frozen output contract
```

The transport representation MAY be provider-native structured output or strict
JSON, but it MUST preserve these semantics. Unknown variants, unknown fields,
missing fields, duplicate `call_id` values, ungranted tools, invalid arguments,
output-contract violations, and limit violations are invalid. A
`conversational` definition rejects `finish.result`; a `structured` definition
rejects `say` and requires `finish.result` to match its closed result schema.

The model cannot attach approval classifications, user-facing approval
previews, execution policy, effect IDs, provider credentials, or delivery
instructions to a step.

### 4.2 Whole-step validation

Before any part of a step is acted on, the kernel MUST:

1. Receive the complete provider response.
2. Parse exactly one variant and reject trailing or competing content.
3. Apply structural and size limits and reject unknown fields.
4. For `call_tools`, resolve every tool against the frozen plan and validate
   every argument object through `llm-tools`.
5. Validate user-facing text and any terminal result against the definition's
   frozen output contract.
6. Confirm that the complete step fits remaining call and run budgets.

If any check fails, the whole step fails. The kernel MUST emit no `say` text and
dispatch none of its calls. Whole-step atomicity applies to validation; it does
not pretend that independently committed external effects form a transaction.

### 4.3 Step semantics

- `say` concludes conversational input with user-visible text. Delivery and
  durability are application concerns and occur only after validation.
- `finish` concludes without user-visible text. For a structured definition,
  its validated `result` is the terminal value returned to or settled by the
  host. `reason`, if present, is internal trace data.
- `call_tools` passes the validated ordered call set to the dispatch port. Its
  normalized observations become turn-local context for a later model step.
  Effectful durability is a dispatcher/`llm-tools` obligation, not an event-sink
  obligation. `call_tools` has no user-facing text; after seeing the correlated
  observations, the model may produce a separate truthful terminal `say`.

The default adapter dispatches calls in listed order. An application MAY provide
a parallel dispatcher only for calls that `llm-tools` declares non-effectful and
host policy has already classified as automatic/non-stopping. It MUST preserve
stable result ordering, honor the same budgets and cancellation contract, and
return every initiated outcome. Every potentially effectful or stopping call is
dispatched serially, so one step cannot create multiple unresolved host
references concurrently.

### 4.4 Protocol feedback

An invalid response produces a bounded `protocol_rejected` diagnostic suitable
for repair, not provider-specific raw prose alone. The next model call receives
it as a turn-local typed correction section with the same unresolved input. The
kernel offers the rejection to the event sink, but sink failure is nonfatal and
no persistence is required. No invalid response can cause a tool effect or
user-visible `say`.

Protocol retries consume model-step, time, and usage budgets. When no retry
budget remains, the run returns `protocol_error`. Raw provider traces MAY be
kept by the host for audit but are not a substitute for normalized corrective
feedback inside the live drain.

## 5. Tool dispatch boundary

The kernel receives one already-frozen `llm-tools` plan from the application,
proves that it is a subset of the definition's immutable envelope, and then MUST
NOT discover, expand, or mutate tools during the run.

`ToolDispatchPort` accepts validated calls plus a stable application invocation
key, cancellation token, and remaining budget. It returns one outcome per
initiated call in canonical call order:

- `executed`: a validated observation that can be shown to the model.
- `pending_approval`: the host durably accepted an approval proposal but did
  not execute it; it includes an opaque host reference.
- `denied`: host policy denied the call during this dispatch.
- `failed`: a declared failure observation that can be shown to the model.
- `uncertain`: the host cannot safely determine an effect's outcome; it includes
  an opaque reconciliation reference.

The application and its tool bindings decide whether approval is required,
render any preview, persist the proposal, and execute or deny it later. The
kernel merely recognizes the host-authored outcome. It MUST NOT classify calls
as automatic or approval-bearing and MUST NOT turn a pending proposal into an
effect.

`executed`, `denied`, and `failed` outcomes become turn-local tool observations
and the loop may continue. An effectful `executed` outcome is returned only after
the dispatcher and `llm-tools` have met their effect-recording contract. On
`pending_approval` or `uncertain`, that host state is already durable. In a
thread run, the kernel settles the current input with a host-referenced waiting
conclusion. It does not ask the model to retry. A later host-authored
`ActionResolutionInput` carries the opaque host reference, original tool ID,
resolved state, and validated observation or receipt into a new input batch. It
does not reuse the turn-local `call_id`. A one-shot run treats either stopping
outcome as an adapter error under its non-effectful-plan rule. Dispatch
cancellation follows section 9. Calls after a serially encountered stopping
outcome are not initiated.

The kernel provides no exactly-once claim. Effect identity, recording,
reconciliation, and replay safety remain in the application bindings and
`llm-tools`. A dispatcher MUST preserve the invocation and call identities
across its own safe retries.

## 6. Context construction

### 6.1 Canonical material

`ContextSourcePort` supplies semantic, provider-neutral application material:

- Stable agent and role instructions.
- Bounded canonical completed history with source IDs and timestamps.
- The current ordered waking inputs and source timestamps.
- Host-selected retrieved context.
- The current frozen capability descriptions.
- Exactly one host-supplied authoritative `as_of` instant captured for the
  current input batch and reused unchanged across its tool loop, plus optional
  stable facts such as an IANA timezone.

The kernel augments that material with tool and protocol observations produced
during the current run. Those observations are not canonical context-source
state and may remain turn-local.

Each waking input MUST appear exactly once in one provider session's input
history. It is included on the first call for its batch, then omitted from later
continuation calls in the same tool/protocol loop; those calls carry only new
observations, corrections, and refreshed dynamic material. A cold bootstrap
into a replacement session includes unresolved input once in that replacement.
Context selection MUST retain source identity and chronology. Summaries,
indexes, provider transcripts, and provider compaction are projections; they
MUST NOT silently replace canonical source events. If content is omitted for a
bound, the context SHOULD say what range or source references were omitted.

The kernel composes this material with `llm-tools` typed prompt sections.
Escaping and rendering belong to `llm-tools`. XML-like presentation is not a
trust boundary.

### 6.2 Continuation mode

When a compatible provider session reference is healthy and the definition uses
`continuing` mode, the continuation
projection sends only material not already carried by that session: as-yet
unseen waking input, fresh retrieved context, current capability information
when needed, and new current-run observations. Once the provider accepts a
response for an input batch, later continuation calls MUST NOT repeat that batch.

Stable instructions and completed history SHOULD NOT be repeated merely to
simulate a stateless call. The context policy MUST nevertheless be able to mark
critical current facts as authoritative over stale session history.

### 6.3 Cold-bootstrap mode

When no compatible session exists, the definition uses `isolated` mode, or
resume fails safely, the bootstrap projection includes stable sections and
bounded canonical completed history before the same current-turn material. An
isolated run opens a fresh provider session and never loads or saves a session
reference. A bootstrap restores useful semantic continuity; it need not recreate
provider reasoning or compaction byte-for-byte.

A provider-session failure before a valid response MAY fall back once to a cold
bootstrap if the host permits it and `provider-runtime` reports that no response
was accepted. A failure after a validated step or initiated tool call MUST NOT
replay the model step blindly.

The bootstrap contract MUST remain usable by a future stateless API-backed
provider without changing application persistence or context selection.

## 7. Ports

Ports use opaque application identifiers. Their reference implementation MUST
be asynchronous and typed; sync applications may wrap it at their boundary.

### 7.1 Provider port

`ProviderPort` adapts `provider-runtime`. It opens or resumes a session, submits
typed context, returns a complete response plus usage and a new opaque session
reference, and accepts cancellation. Provider-native events MAY be forwarded to
tracing but cannot bypass the step parser or tool boundary.

### 7.2 Session-reference port

`SessionRefPort` provides:

```text
load(thread_id, definition_fingerprint) -> ref with generation | none
compare_and_set(thread_id, expected_generation, new_ref)
  -> stored(new_generation) | stale
discard(thread_id, expected_generation) -> discarded | stale
```

References MUST be scoped to the application thread and definition fingerprint.
They contain no canonical message bodies or credentials. Losing all references
must cause bootstrap, not data loss. A stale compare-and-set result MUST NOT
overwrite the winner. After crash recovery, a host MUST discard a reference
before replaying unresolved input unless it can prove the session is aligned;
cold bootstrap is always the valid fallback.

`stored` returns the new generation, which becomes the expected generation for
the next model step. A `stale` result before dispatch or canonical settlement is
an `adapter_error`: the kernel performs no effect and commits no conclusion from
that response. It MUST NOT continue with unsaved provider state. The host
resolves the conflicting reference and unconsumed input through recovery.

After a crash, recovery distinguishes two cases. If the host's durable state
proves that no effectful dispatch began, it discards any speculative reference
and may replay the unconsumed input from cold bootstrap. If an effectful dispatch
began or may have begun, the host first uses its effect/action record to
reconcile or resume it and MUST NOT ask the kernel to replay the original model
turn blindly.

### 7.3 Input-checkpoint port

`InputCheckpointPort` provides the concurrency boundary:

```text
claim(thread_id, owner_token, run_class) -> claim | busy | class_mismatch
read(claim) -> ordered waking inputs plus opaque through_checkpoint
settle(claim, through_checkpoint, terminal_conclusion, on_new_input)
  -> continue | idle | deferred
release(claim) -> released(armed_unconsumed: boolean) | already_released
```

This port is required only for a thread run. `run_class` is an opaque stable
application value whose host-owned policy binds it to the supplied frozen plan
and determines input eligibility. `claim` grants exclusive drain ownership. If
the first unconsumed waking input is not eligible for the requested class, the
adapter MUST arm the correct class before returning `class_mismatch`; the kernel
returns `pending_input` without calling the provider. `read` MUST return only
the maximal contiguous ordered prefix eligible for the claimed class.

`settle` MUST atomically:

1. Commit the supplied host-owned terminal conclusion idempotently.
2. Mark all inputs through `through_checkpoint` consumed by that conclusion.
3. Test for newer waking input.
4. Determine whether the next waking input is eligible for the claimed class.
5. Apply the requested newer-input behavior: `continue` under the same claim
   only when budget remains and that input is eligible, or `defer` when another
   run or class is required.

If newer waking input exists and `continue` was requested, `settle` returns
`continue` and preserves the claim only when the next input is eligible for the
same class. An incompatible next input forces `deferred` even if budget remains.
When deferring, the adapter atomically arms the host's run trigger for the next
input's class, releases the claim, and returns `deferred`; the unconsumed input
remains the durable recovery watermark. With no newer input, it atomically
commits `idle`, releases the claim, and returns `idle`. Pending approval and
uncertainty are terminal-conclusion kinds, not a thread lock: compatible newer
input can be processed normally, while incompatible input is handed off. The
eventual public result is `waiting` only when such a conclusion settles with no
newer input.

`release` is idempotent and exists for cancellation/error cleanup. If the claim
still owns any unconsumed waking input, it MUST arm the host's recovery run
before releasing and report `armed_unconsumed = true`; calling it after `settle`
released ownership returns `already_released`. This
compare-and-set rule closes both the arrival-during-finalization race and the
budget-exhaustion handoff gap. A defer implementation MUST register the next run
before making the claim available; after a process crash, startup MUST scan the
same unconsumed canonical inputs before declaring the service idle. A host may
implement a claim with an in-process mutex, advisory lock, row lock, lease, or
workflow; the kernel requires the semantics, not a mechanism.

Terminal conclusion and input consumption MUST share one durable transaction or
an equivalent idempotent commit protocol. Restart recovery MUST recognize an
already committed conclusion without generating a second one. This is the only
application persistence guarantee imposed by the checkpoint port; turn-local
protocol and read/tool-loop observations need not be stored.

### 7.4 Event sink

`EventSinkPort` receives normalized semantic events for observability. A host MAY
persist them, but kernel correctness and recovery MUST NOT depend on that
persistence. V1 event kinds include at least:

- `model_said`
- `model_finished`
- `tool_executed`
- `tool_failed`
- `tool_denied`
- `tool_pending_approval`
- `tool_uncertain`
- `protocol_rejected`
- `budget_exhausted`
- `run_cancelled`
- `run_failed`

Event payloads are semantic library values and exclude sensitive bodies by
default. Emission does not make an event canonical, acknowledge input, or
replace the dispatcher's effect record. The kernel attempts emission before
reusing a protocol correction or tool observation. Event-sink failure MUST NOT
fail a run or block that reuse; the adapter reports it out of band.

### 7.5 Supporting ports

- `ContextSourcePort` selects canonical and retrieved context.
- `ToolDispatchPort` bridges the frozen plan to the application/`llm-tools`
  executor boundary.
- `ClockPort` supplies monotonic deadlines and optional host wall time.
- `CancellationToken` allows cooperative cancellation at model, dispatch, and
  between-step boundaries.

Adapters MUST NOT gain more credentials or authority than their underlying
operation requires.

## 8. Drain algorithm

The public thread entry point is semantically:

```text
await run_thread(
  definition: AgentDefinition with SessionMode.continuing,
  plan: frozen llm-tools plan within the definition envelope,
  run_class: opaque host value bound to that plan and input eligibility,
  thread_id: opaque application ID,
  ports: KernelPorts,
  cancellation: CancellationToken,
) -> RunResult
```

`KernelPorts` groups the provider, session-reference, input-checkpoint, context
source, tool dispatcher, and clock ports plus the optional event sink.
Construction performs no I/O and grants no capability beyond the current frozen
plan, which has already been checked against the definition envelope.

V1 rejects `run_thread` with `SessionMode.isolated`. A future stateless provider
can still consume the existing bootstrap/context contract; adding a thread mode
that holds an unsaved session only for one drain requires an explicit later
contract rather than an ambiguous branch in this algorithm.

For one run, the kernel MUST behave equivalently to:

```text
claim application thread for run_class or return busy/pending_input
load the maximal run-class-compatible input prefix and its through_checkpoint
load compatible provider session reference

while not stopped:
  check cancellation and budgets
  build continuation context, or bootstrap context if no healthy session
  call provider once
  validate the complete model step

  if invalid:
    attempt protocol_rejected emission and add turn-local corrective feedback
    compare-and-set the returned session reference or return adapter_error
    update the expected session generation
    continue with corrective feedback

  if call_tools:
    compare-and-set the returned session reference or return adapter_error
    update the expected session generation
    dispatch only after every call validates
    attempt emission of all initiated outcomes and retain observations turn-locally
    if any outcome is pending_approval or uncertain:
      settle host-referenced waiting conclusion and consumed input,
        requesting continue or defer according to remaining budget
      if settle says continue: read newer same-class waking input and continue under claim
      if settle says deferred: return pending_input
      return waiting
    add completed observations to current-drain context
    continue

  if say or finish:
    compare-and-set the returned session reference or return adapter_error
    update the expected session generation
    settle host terminal conclusion and consumed through_checkpoint,
      requesting continue or defer according to remaining budget
    if settle says continue:
      read newer same-class waking input and continue under the claim
    if settle says deferred: return pending_input
    return idle

idempotently release in a finally path, arming recovery if input remains unconsumed
```

The implementation MAY organize code differently but MUST preserve the ordering
constraints. It MUST NOT hold a database transaction open across a provider or
external tool call. Advancing the disposable session reference before canonical
settlement is deliberate: if the process stops between those boundaries, the
input remains unconsumed and recovery discards the speculative reference. An
effect-free interrupted turn may then replay; one with a recorded or possible
effect follows host reconciliation and is not blindly replayed. Reversing the
order could commit the conclusion while leaving a stale session reference that
silently omits it on the next continuation.

The public isolated entry point is semantically:

```text
await run_once(
  definition: AgentDefinition with SessionMode.isolated and structured output,
  plan: frozen non-effectful llm-tools plan within the definition envelope,
  input: provider-neutral host material,
  ports: OncePorts,
  cancellation: CancellationToken,
) -> OnceResult
```

It uses the same context, provider, whole-step validation, dispatch, correction,
budget, and cancellation machinery, but it neither claims a thread nor loads or
saves a session reference. V1 rejects a one-shot definition whose frozen
`llm-tools` plan contains any effectful binding or whose output contract is not
structured. It terminates only with a validated `finish.result`. The caller
receives that result and performs any application transaction. If the caller
stops before committing it, the read-only one-shot work may be recomputed; no
kernel checkpoint falsely records it as durable. Opaque provider continuation
state may exist between model steps within that invocation, including inside
`provider-runtime`, but the kernel never loads or saves its reference through
`SessionRefPort` and never treats it as canonical application state.

## 9. Budgets and cancellation

Every `AgentDefinition` MUST specify finite bounds for:

- Model steps per run.
- Protocol-repair steps per run.
- Tool calls per step and per run.
- Concurrent tool calls.
- Provider input and output size/usage, using the best counters the provider
  exposes.
- Tool-observation size.
- Wall-clock duration.
- Individual provider and dispatch timeouts.
- Context and observation sizes.

The kernel checks the relevant bound before starting work and accounts for
actual usage afterward. Exhaustion attempts a `budget_exhausted` event and returns
`budget_exhausted`; it is never represented to the model as a successful tool
result.

Cancellation is cooperative. It is checked before and after provider and tool
boundaries and passed into adapters. Cancellation cannot erase an effect that
already committed; the dispatcher must report the best durable outcome it can.
The kernel attempts a cancellation event and does not blindly retry unknown work.

No unbounded internal retry loop is permitted. Provider transport retries belong
to `provider-runtime`; tool replay policy belongs to `llm-tools` and the host.

## 10. Run outcomes

The public run result is one of:

- `idle`: all observed waking input concluded and the idle transition committed.
- `busy`: another drain owns the application thread.
- `pending_input`: the requested class did not match the first input, or
  finalization observed newer waking input that could not continue in this run;
  the checkpoint adapter atomically armed the correct later run and released or
  declined the claim.
- `waiting`: a pending or uncertain host operation requires later input or
  reconciliation and no newer waking input was ready to drain.
- `cancelled`: cancellation stopped the drain.
- `budget_exhausted`: a configured finite limit stopped it.
- `protocol_error`: bounded correction could not produce a valid step.
- `provider_error`: the provider failed without a safe fallback.
- `adapter_error`: a required host port violated or could not complete its
  contract.

Outcomes describe the run, not application action status. The host decides how
to react to each outcome; `pending_input` already means the checkpoint adapter
armed another run. `OnceResult` uses the same failure, cancellation, and budget
taxonomy but replaces thread states (`idle`, `busy`, `pending_input`, and
`waiting`) with `completed(structured_result)` or the applicable stop outcome.
A one-shot dispatcher that reports pending approval or uncertainty is an adapter
error in v1; durable suspension belongs to a thread run.

## 11. Observability and privacy

The kernel emits structured trace hooks for drain start/stop, context mode,
provider call, validation result, tool dispatch, budget usage, cancellation, and
idle contention. Trace payloads MUST use stable IDs and timings and MUST NOT log
prompt bodies, tool arguments, observations, session references, or credentials
by default. Applications explicitly opt into redacted content capture.

Provider sessions, raw provider events, and traces are diagnostic projections.
Canonical host input, terminal conclusions, effect state, and retrieved context
remain sufficient for a cold bootstrap.

## 12. Conformance requirements

The package is v1-ready when automated conformance tests prove:

1. Each valid step variant round-trips; conversational and structured output
   contracts enforce their respective text/result rules; all unknown or mixed
   shapes fail.
2. One invalid call makes a whole `call_tools` step effect-free.
3. Invalid `say` plus tool content displays nothing.
4. Protocol feedback is turn-local, bounded, charged to budgets, and offered to
   observability before reuse; sink failure is nonfatal.
5. Continuation uses a compatible session; missing, stale, and failed sessions
   cold-bootstrap from canonical context.
6. Losing every provider session reference loses no canonical content.
7. Two simultaneous runs yield one drain owner and one `busy` result.
8. Waking input arriving during finalization prevents idle and is either
   processed by the owning drain or atomically deferred to an armed later run.
9. A crash between conclusion work and restart cannot create a second canonical
   conclusion for the same input checkpoint.
10. Tool observations reach the next provider call within a live drain without
    requiring application persistence; effectful outcomes satisfy the separate
    dispatcher/`llm-tools` durability contract.
11. `pending_approval` outcomes consume the proposing input without executing,
    approving, or rendering policy inside the kernel; a later host-authored
    action-resolution input correlates by opaque host reference and resumes work.
12. Cancellation and each budget stop at every defined boundary.
13. Session-reference compare-and-set cannot overwrite a newer generation.
14. An isolated one-shot run accepts only a non-effectful frozen plan, uses a
    fresh session and no checkpoint/session-ref port, and returns only a
    schema-valid structured result.
15. A crash on either side of session-reference advancement and terminal
    settlement cannot resume a provider session that is semantically behind or
    ahead of canonical input consumption.
16. No conformance fixture requires a kernel-owned database table, workflow,
    connector, memory store, XML renderer, sandbox, or subagent.

The architectural rationale is recorded in [ADR 0001](docs/decisions/0001-library-boundary.md),
[ADR 0002](docs/decisions/0002-event-drain-kernel.md), and
[ADR 0003](docs/decisions/0003-provider-and-tool-ownership.md).
