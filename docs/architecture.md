# Architecture

## System boundary

`llm-agent-kernel` coordinates four independently owned systems:

```text
┌──────────────────────────── host application ────────────────────────────┐
│ canonical input/history  admission  policy  action/effect state  delivery│
│       │                    │         │                │                   │
│       └──── context/checkpoint/admission/dispatch/session-ref ports ─────┤
└──────────────────────────────────────┬────────────────────────────────────┘
                                       v
                         ┌────────────────────────┐
                         │   llm-agent-kernel     │
                         │ containment + context  │
                         │ strict serial loop     │
                         │ polling + settlement   │
                         └──────────┬─────────────┘
                                    │
                    ┌───────────────┴────────────────┐
                    v                                v
       ┌────────────────────────┐       ┌────────────────────────┐
       │ provider-runtime       │       │ llm-tools              │
       │ AgentRuntime sessions  │       │ plan + execute + record│
       └────────────────────────┘       └────────────┬───────────┘
                                                     v
                                             host tool bindings
```

The kernel owns control flow, not application authority or data. Native
provider containment and the host-selected frozen tool plan form the effective
authority together. Neither prompt text nor the model's requested operation can
widen them.

The ownership split is fixed by [ADR 0001](decisions/0001-library-boundary.md),
[ADR 0003](decisions/0003-provider-and-tool-ownership.md), and
[ADR 0005](decisions/0005-codex-agent-lane-and-serial-steps.md).

## Runtime modules

The runtime is organized into the source modules below.

### `definitions.py`

Defines immutable provider-neutral values:

- `AgentDefinition`, `SessionMode`, `OutputContract`, and `KernelLimits`.
- `StructuredOutput` retains the logical Pydantic schema and freezes its
  preflighted Codex `wire_schema`; unsupported result contracts fail during
  construction.
- Exact session-scoped provider configuration and deterministic fingerprint.
- Required owner-controlled session-compatibility revision for deliberate
  saved-session rotation across application/kernel/runtime semantic changes.
- Frozen maximum profile and host-selected frozen run plan, with the exact
  catalog view covered by the plan's consistency/tightening proof.
- `InputClaim`, host inputs, checkpoints, `DispatchLineage`, conclusions, and
  run outcomes.
- Closed `SayStep`, `CallToolStep`, and `FinishStep` models.
- Completed and suspended dispatch results.

The fingerprint includes every native option that changes session meaning or
containment: backend, transport, credential-profile identity, model, reasoning,
instructions, output schema, policy, cwd, directories, MCP configuration,
native options, and the owner-controlled session-compatibility revision. Secret
bytes and dynamic input are excluded.

### `provider.py`

Adapts the actual `provider_runtime.agent_runtime.AgentRuntime` resource
lifecycle:

```text
open_session(AgentSessionRequest)
stream_turn(AgentSession, TurnRequest, cancel=...)
close_session(AgentSession)
```

The adapter owns live-session leases, consumes and inspects every streamed
event, and maps typed runtime terminals. It uses the exact provider-certified
`openai-codex==0.144.4` SDK/runtime pair and never uses the convenience
`AgentRuntime.run_turn` projection because that method discards the event
history required for containment. It publishes the kernel's Codex-compatible
closed-object wire envelope through `JsonSchemaAgentOutput` and constructs the
exact containment request:

- subscription-backed Codex route;
- private empty absolute cwd with read-only filesystem policy;
- no additional directories, copied environment, network, MCP, or approval;
- native built-ins and Web disabled;
- the Codex `allowed_tools=("*",)` SDK sentinel only where required by the
  pinned runtime.

The sentinel is not application authority. Any native `AgentToolUse` or
`AgentPermissionRequest` event taints and discards the session and fails the run
without returning its terminal to the loop, before a host tool or model-authored
conclusion can cross the boundary. Streaming text is not delivered; only
terminal structured output from a fully inspected clean stream enters the
kernel protocol.

### `sessions.py`

Coordinates disposable continuing sessions through two separate resources:

- A live-session lease owned by the provider adapter and optionally cached by
  the host for latency.
- A serialized `AgentSessionRef` stored behind a generation-CAS host port.

Every successful provider turn advances the session reference before the
kernel acts on the step. A stale CAS proves another owner or broken adapter and
therefore permits no dispatch or settlement. If later canonical settlement is
interrupted, the input remains unconsumed; recovery discards the speculative
reference before replay.

A missing, invalid, incompatible, or unresumable reference permits one cold
bootstrap before any successful terminal from the current attempt. Provider
session state is never evidence that host input was consumed.

### `context.py`

Builds `llm-tools` prompt sections from host-selected material:

- stable role and application context;
- bounded canonical completed history;
- current claimed or newly polled host input;
- host-selected retrieval;
- the exact frozen `HostTable` plan;
- relevant locale/timezone and one `as_of` per admitted input batch;
- bounded tool observations and explicit omission markers.

Continuation sends only material not already accepted by that live session.
Cold bootstrap rebuilds useful context from canonical state and may repeat safe
reads. It obtains durable effect arguments and outcomes from host action state,
never solely from provider history.

XML-like rendering preserves structure and provenance but does not neutralize
prompt injection. Untrusted human, connector, memory, and Web content remains
untrusted data.

The context counter is intentionally narrower than total provider context. It
counts UTF-8 bytes of kernel-rendered material newly submitted during this
invocation: initial bootstrap/run material, appended inputs, observations,
corrections, and any cold-bootstrap replay. Provider system/developer material,
output-schema transport overhead, retained native-session history, and provider
compaction are outside the counter.

### `_schema.py`

Compiles a logical structured result schema into the Codex strict subset before
an `AgentDefinition` can be built. It closes and requires every object property,
preserves supported definitions and constraints, removes non-validating schema
generator annotations, and lowers nested `oneOf` to `anyOf` for later exact host
revalidation. Map-shaped objects, unsupported semantic keywords, malformed
schemas, and provider size/depth violations fail deterministically. This is
model-output schema compilation owned by the kernel, not provider SDK
integration or `llm-tools` input-schema compilation.

### `protocol.py`

Separates the provider wire from the closed logical model grammar:

```text
say(text)
call_tool(tool_id, arguments)
finish(optional reason, output-contract result)
```

The wire is one root object with required `type`, `say`, `call_tool`, and
`finish` properties. Inactive branch payloads and optional reason values are
explicit nulls. Tool arguments cross the wire as a string containing one strict
JSON object, avoiding schema-valued `additionalProperties`; duplicate keys,
non-finite constants, trailing data, and non-object values fail during decode.
For structured definitions, Pydantic's result schema is compiled before an
agent definition exists: all objects remain closed, every property is required,
definitions are preserved, non-validating defaults are removed, and unsupported
or map-shaped contracts are rejected.

It revalidates and decodes the complete runtime-parsed envelope, revalidates the
resulting logical step, applies the output contract, resolves the exact
frozen-plan binding, and invokes the qualified pure `llm-tools` argument
validator. Before any plan is rendered, the dependency's public proof must bind
every published tool specification and revision to its frozen grant and prove
that the complete plan tightens the maximum profile; a profile-only comparison
is not sufficient. Every binding carries an owner-controlled implementation
revision covering its handler and transitive execution behavior. Validation
does not occupy a position, reserve tool budget, touch a recorder, or dispatch.

There is no model-authored preview, call ID, effect ID, authority label,
approval instruction, or delivery instruction. One malformed value produces no
partial text or call. A bounded correction can consume another provider turn.

### `kernel.py`

Runs one claimed batch under `KernelLimits`. It:

1. Validates the claimed plan, constructs its tool budget, and proves exact
   `RunLimits` equality before rendering or I/O.
2. Polls for compatible input or preemption.
3. Builds one bootstrap or the unsent continuation delta.
4. Executes one structured provider turn.
5. Stores the returned session ref by generation CAS.
6. Decodes exactly one complete wire envelope and validates its logical step.
7. Settles `say`/`finish`, or dispatches one `call_tool` serially.
8. Feeds a bounded completed observation into the next provider turn, or
   settles a durable suspension and returns.

The kernel polls before provider turns, before dispatch, after tool completion,
and before settlement. Compatible input is appended exactly once under the
already-frozen plan. Incompatible input remains unclaimed. A stop or
higher-priority host control may preempt; ordinary follow-up input does not
discard a paid valid answer that has already reached finalization.

V1 has no parallel calls and no nonterminal model-authored narration. The host
may expose typing/activity state.

### `coordination.py`

Defines the host coordination protocols.

`InputCheckpointPort` claims a non-empty bounded batch, polls it, atomically
settles its conclusion plus consumed checkpoint, releases interrupted work, and
durably parks configuration defects. The host owns selection, priority,
compatibility, and plan choice. The kernel has no `run_class`.

`AdmissionPort` durably reserves one live slot per exclusive root work epoch plus
maximum turn and available token allowance before provider I/O. A strictly
serial child one-shot may share the root slot only when its allowance was
included in the parent reservation and the parent cannot perform provider or
tool I/O. Clean exits settle actual usage and refund unused capacity. After
process death, startup under the exclusive host lock releases the orphaned slot
but preserves the conservative rolling turn/token charge until window expiry.
Missing or corrupt admission state fails closed. Subscription AgentRuntime is
not assigned fictional per-token dollar cost; a future priceable lane may add a
cost dimension.

`EventSink` receives bounded metadata. It is observability, not canonical input,
delivery, or an effect recorder, and its failure is nonfatal.

`ToolBudgetFactoryPort` receives the already validated frozen plan and returns a
fresh `llm_tools.BudgetState`. The kernel requires exact equality between its
`limits` and `plan.profile.run_limits` before context rendering, admission,
provider I/O, or tool I/O. The factory removes any need for a caller to know a
claimed plan out of band and does not make the kernel a tool-budget owner.

### `tools.py`

Bridges a validated proposal to the host dispatcher and `llm-tools`. It never
implements a second executor or tool budget.

Every thread dispatch carries immutable claim ID, current checkpoint, ordered
admitted input IDs, and model-step ordinal. An isolated dispatch carries only
its run ID and ordinal. The host may persist lineage with an effect; the kernel
treats it as opaque coordination metadata.

`llm_tools.RunLimits` alone owns tool-call, attempt, byte, concurrency, and tool
elapsed limits. The frozen plan sets `max_in_flight = 1`. `KernelLimits` owns
provider turns, protocol repairs, reported provider usage, the cooperative
elapsed limit, and newly rendered model-visible context bytes.

The exact `llm-tools` pin also revision-controls `web.search`'s inner
whole-operation deadline. The Brave binding's default 12-second deadline covers
all request attempts and retry delays inside the declared 15-second executor
deadline, records the deadline in policy identity, and counts attempts through
the provider callback immediately before dispatch. This remains dependency-owned
tool execution behavior; the kernel does not add another timer or attempt
counter.

The cooperative limit is observed at safe boundaries and becomes the remaining
hard deadline for each provider turn. It is not an outer timeout over host
ports, settlement, cleanup, or tool dispatch. Tool execution keeps its frozen
`llm-tools` elapsed deadline; especially for a `Write`, the kernel does not
interrupt outside recorder/reconciliation semantics.

For `Write`, the host creates or resolves a durable action/effect row before
executor entry. Its stable ID is both the `InvocationPosition` and `EffectId`.
For `Pure` and `Read`, the host may use an attempt-scoped position and
non-durable recorder. A `Read + BilledOnce` operation can therefore rebill after
a crash; v1 accepts that cost instead of adding a generic durable read cache.

Dispatch returns:

```text
completed(llm_tools ToolResult)
suspended(host_ref, waiting_for=user|system)
```

A suspension means host state is durable and the run can release all live
resources. A later host input supplies the reference, tool ID, original
validated arguments, resolution, and safe evidence. The kernel owns no approval
or action vocabulary. Terminal uncertainty is a host resolution, not a generic
tool-loop retry signal.

## State transitions

```text
START
  |
  +-- no work / busy / denied admission ----------------------> RETURN
  |
  v
CLAIM --> PROVE PLAN --> BUILD EXACT BUDGET --> ADMIT --> OPEN/RESUME
                                                        |
                                                        v
                                                     POLL --> MODEL TURN
                                                        typed failure |
                                              bounded fallback or STOP
                                                               |
                                         CAS SESSION REF --> VALIDATE
                                                           invalid |
                                               bounded correction
                                                           |
                                                           +--> POLL

VALIDATE -- call_tool --> POLL --> SERIAL DISPATCH
                                      /       \
                               completed    suspended
                                   |            |
                              observation     SETTLE --> RETURN
                                   |
                                   +------------------> POLL

VALIDATE -- say/finish --> POLL FOR PREEMPTION --> SETTLE --> RETURN

deterministic exhaustion/quota/stop --> host-authored stopped conclusion
process interruption/invariant defect --> release or park; never auto-rearm
```

No database transaction remains open across provider or connector I/O.

## Work bounded across runs

A per-run ceiling is insufficient if cleanup can create an unlimited sequence
of fresh runs. [ADR 0006](decisions/0006-bound-work-across-runs.md) therefore
requires:

- no unconditional successor arming from `release`;
- deterministic poison stops to settle and consume the claimed input;
- durable no-progress attempt counting on crash recovery;
- rolling admission before provider I/O;
- explicit startup/recovery scanning of canonical unconsumed input.

When `settle` reports later input, the host signals a new run after commit.
Correctness rests on canonical state and recovery scanning, not a fictitious
transaction spanning a database and a process trigger.

## Durable-state truth

The kernel owns no database schema, but its contracts do require real durable
facts in a continuing effectful host:

| Fact | Owner | Why |
| --- | --- | --- |
| Input, conclusion, consumed checkpoint, delivery | Host canonical store | Conversation correctness and restart delivery |
| Provider session ref + generation | Host session-ref store | Safe continuation optimization and CAS ownership |
| Action/effect position, input, recorder result | Host + `llm-tools` recorder | Write replay and reconciliation |
| No-progress attempts and rolling usage | Host admission state | Cross-run boundedness |

A host may map several facts into existing tables or one atomic document. The
library does not dictate layout, but conformance must prove the semantics. An
in-memory recorder is a test double, never a crash-safety claim.

## Observation size and recovery

Bindings return bounded previews, pagination/source references, and typed
boundary guidance. The kernel additionally caps cumulative kernel-rendered
model-visible bytes newly submitted in the current invocation. Provider
configuration/schema overhead, native retained history, and provider compaction
are outside that counter. It may replace older recomputable reads with explicit
omission markers and stable source references. It may not silently truncate
effect results, approval material, or reconciliation evidence.

V1 intentionally has no generic observed-value table. A host can add one after
real workloads prove that source reread and bounded results are inadequate.

## Deferred designs

Program agents and general delegation remain deferred under
[ADR 0004](decisions/0004-defer-program-agents-and-delegation.md). Also deferred:
parallel steps, semantic discovery in the kernel, provider-native application
tools, MCP application tools, model-authored progress, generic durable read
observations, stateless provider generation, and kernel-owned workflow/schema
infrastructure.
