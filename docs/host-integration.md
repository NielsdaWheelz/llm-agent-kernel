# Host integration and release qualification

`llm-agent-kernel` deliberately stops at asynchronous ports. A production host
must implement persistence and product policy outside this package; replacing a
store with an in-memory adapter changes the recovery guarantee and is not a
deployment option for continuing effectful work.

The shared generation protocol is specified separately in
[SPEC section 16](../SPEC.md#16-shared-generation-protocol). Its host lifecycle
must arm native children, atomically commit terminal and exact successor
decision, and reopen the same canonical bytes under the current claim. Its
observer must acknowledge events before dependent tools run. Resume must use
the original durable decision and existing tool recorder positions. The host
must atomically retire pending continuation and persist a distinct stopped
parent outcome when the kernel returns `GenerationStopped`; it must preserve
the real child terminal evidence. No in-memory lifecycle fake proves these
obligations.

## Required durable facts

The checkpoint store is canonical for ordered input, exclusive claim ownership,
the oldest-input attempt number, checkpoint advancement, and atomic
conclusion/consumption. `release` is idempotent cleanup and never signals new
work. Startup scans the same unconsumed input used by `claim`.

The kernel calls `park` before returning `configuration_error`; the checkpoint
implementation must atomically release ownership into a durable operator-only
park and trip the applicable thread or deployment circuit breaker. Only
operator correction may clear it. `release` remains ordinary cleanup and is
deliberately not a hidden scheduling or parking operation.

The session-reference store is keyed by `(thread_id, definition_fingerprint)`
and implements generation CAS. A successful provider terminal is stored before
validation, display, dispatch, or settlement. Recovery discards a speculative
reference before cold-bootstrap replay.

Every `AgentDefinition` supplies a non-empty owner-controlled
`session_compatibility_revision`. The host rotates it whenever an application,
kernel, or provider-runtime semantic change makes saved sessions unsuitable for
reuse even though other definition fields remain unchanged. Because it is part
of the fingerprint and session-store key, rotation cold-bootstraps without
deleting the older reference namespace.

The Codex provider wire is not the public logical step shape. Provider terminals
contain a required/nullable envelope and must enter the kernel through
`validate_provider_step`; `validate_model_step` remains the validator for an
already-decoded logical `say`, `call_tool`, or `finish`. Wire
`call_tool.arguments` is a strict JSON object encoded as a string and is decoded
before the unchanged `llm-tools` input validator runs. `StructuredOutput.schema`
retains the logical Pydantic schema, while `StructuredOutput.wire_schema` exposes
the compiled provider result schema for diagnostics and fingerprinting. Hosts
should not render or parse either wire form themselves.

For this wire compatibility change, a consumer updates its immutable
`llm-agent-kernel` revision and lock, bumps its owner-controlled
`session_compatibility_revision`, and removes any prompt or fixture that demands
the former top-level logical JSON shape from Codex. Logical `SayStep`,
`CallToolStep`, `FinishStep`, tool definitions, dispatch, and result models do
not change. The definition fingerprint includes the new wire schema, so the
upgrade cold-bootstraps rather than resuming an old-schema native session.

For the historical provider-runtime usage propagation from kernel
`c9dac7a610636a668bbf932cc2f961c0904f9157`, a consumer pins the successor
kernel revision and regenerates its lock to exact provider-runtime revision
`f477dcdcad03c30019576203d4eb8a3581a6d32f`. It keeps `llm-tools` at
`9e6d155f3b64f03495911435b7cae8b8d131f9a2` and `openai-codex` at `0.144.4`.
No provider request, provider wire schema, public kernel API, persistence schema,
or session-reference format changes. Existing native sessions remain compatible,
so a host MUST NOT rotate `session_compatibility_revision` solely for this
correction.

The revised provider contract defines `AgentUsage` events as progressive,
non-additive snapshots for the current invocation and `AgentTerminal.usage` as
invocation-local on every status. Provider-runtime owns subtraction of restored
or prior-turn cumulative provider state. The kernel adapter keeps the latest
progressive snapshot, prefers terminal usage, adds usage once per provider turn,
and sums those invocation-local values across kernel turns. A host MUST NOT add
another cumulative-delta layer. `Absent` means usage is incomplete, not zero;
the admission implementation must retain the run's reserved token dimensions
when settling incomplete usage.

For the provider-runtime assistant-message propagation from kernel
`09f08df2970121ababe973b0e92d6901dd40da9e`, a consumer pins the successor
kernel revision and regenerates its lock to exact provider-runtime revision
`2cfed97ee5b9b8eb11103b0575eb7f29de00a0bd`. It keeps `llm-tools` at
`9e6d155f3b64f03495911435b7cae8b8d131f9a2` and `openai-codex` at `0.144.4`,
and records all three immutable revisions in its compatibility manifest. No
kernel API, provider request, provider wire schema, persistence schema, or
session-reference format changes. Existing native sessions remain compatible,
so a host MUST NOT rotate `session_compatibility_revision` solely for this
correction.

The revised provider contract makes `AgentTerminal.final_text` the
provider-selected authoritative assistant response. `AgentText` events are
observations and need not concatenate to that terminal value. For Codex, the
last completed `phase=final_answer` message wins; if none exists, the last
completed phase-unknown message is the compatibility fallback. Commentary is
never executable structured output. Provider-runtime owns selection and
concatenation rules; hosts and the kernel MUST NOT add another selection layer.
The kernel continues to validate only `AgentTerminal.structured_output`, so a
Jarvis consumer needs no application-code, plan, HostTable, persistence, or
session migration for this release.

For the input-projection release from kernel
`670da13ff0cfe766f36d8966e0575db0f7525143`, consumers pin the successor
kernel revision and regenerate their lock without changing the exact
`provider-runtime`, `llm-tools`, or `openai-codex` pins. The public additions
are `BatchAsOfMode`, `InputProjectionPolicy`, and `InputProjectionRequest`, the
`AgentDefinition.input_projection_policy` field, and the keyword-only
`input_projection` argument on `run_thread`, `run_one_shot`,
`bootstrap_context`, `run_context`, and `continuation_context`.

The default `InputProjectionPolicy()` renders input IDs, per-input
`source_timestamp`, and batch `as_of` byte-for-byte as before.
`render_source_timestamps=False` suppresses the timestamp attribute for every
invocation of that definition. `batch_as_of` is `always`, `never`, or
`on_request`; an `on_request` definition renders the batch clock only when the
invocation supplies `InputProjectionRequest(render_batch_as_of=True)`. A
request for a definition whose mode is `never` is rejected before claim,
context rendering, admission, provider I/O, or tool I/O. The host must continue
to supply aware `HostInput.source_timestamp`, `InputClaim.as_of`, appended
`new_as_of`, and one-shot `as_of` values because this is visibility policy, not
an operational-data deletion.

Every projection-policy value participates in the definition fingerprint, so
this kernel revision rotates definition identity even for the byte-compatible
default and non-default policies rotate again according to their exact value.
An invocation request is dynamic and does not participate. Old saved session
references remain in their former fingerprint namespace and are not resumed;
no session-reference format or persistence schema changes. A host MUST NOT also
bump `session_compatibility_revision` solely for this release because the new
covered policy field already provides the deliberate rotation.

For Jarvis Slice 5, define AutomaticWriteGate with:

```python
input_projection_policy = InputProjectionPolicy(
    render_source_timestamps=False,
    batch_as_of=BatchAsOfMode.on_request,
)
```

Keep its plan empty and its restricted effect descriptor in ordinary
definition-owned context. Invoke it without `input_projection` normally; pass
`InputProjectionRequest(render_batch_as_of=True)` only when that invocation's
relative-time validation requires the batch clock. Do not strip timestamps
from canonical inputs, alter rendered text afterward, or add application roles
inside the kernel. No plan/HostTable re-freeze, effect revision, persistence
migration, provider-wire change, or provider/dependency update is required.

For the deterministic isolated initial-Read release from kernel
`7f3a9b145e68ba23c8aafad08500e9c452a9faef`, consumers pin the successor
kernel revision and regenerate their lock without changing the exact
`provider-runtime` pin
`2cfed97ee5b9b8eb11103b0575eb7f29de00a0bd`, `llm-tools` pin
`9e6d155f3b64f03495911435b7cae8b8d131f9a2`, or `openai-codex==0.144.4`.
The public additions are
`InitialReadCall`, `InitialReadDispatchLineage`, deterministic `position` on
both isolated lineage variants, and the keyword-only `initial_read` argument on
`run_one_shot`. No `AgentDefinition` field, definition fingerprint input,
provider wire, session-reference format, persistence schema, thread behavior,
or dependency contract changes. Existing continuing sessions remain compatible,
and a host MUST NOT rotate `session_compatibility_revision` solely for this
release.

`initial_read=None` is the exact prior path. With a value, the kernel proves the
selected plan and exact catalog/profile relationship, resolves a granted
`ToolEffect.Read` binding, and performs pure schema validation before rendering,
admission, provider I/O, or tool I/O. It then completes normal isolated/child
admission and cancellation checks, creates one fresh exact plan-aware budget,
and dispatches the call through `ToolDispatchPort`. The dispatcher MUST use
`InitialReadDispatchLineage.position` as the `llm-tools`
`InvocationPosition`. It MUST likewise use `IsolatedDispatchLineage.position`
for later model-proposed isolated calls; the kernel derives the two position
domains deterministically so they cannot collide within the run. Thread
position/effect ownership is unchanged.

Only `DispatchCompleted` supplies initial context. Its exact typed `ToolResult`,
including declared or `BudgetExceeded` boundary failure, is rendered with
`origin="initial_read"` before the provider session opens. The same budget is
passed to every later model-proposed dispatch, so `llm-tools` accounts calls,
attempts, bytes, external attempts, and elapsed time once. Suspension,
recovery/configuration defects, cancellation, or an oversized required
observation stops before provider I/O. Initial arguments/results remain private
payload and are absent from default events.

Jarvis's recaller migration is:

```python
outcome = await run_one_shot(
    # existing arguments unchanged
    initial_read=InitialReadCall(
        ToolId("memory.search"),
        {"query": recall_query},
    ),
)
```

The selected frozen recaller plan must grant the exact revisioned
`memory.search` Read binding, and its dispatcher must forward the lineage's
provided isolated position unchanged. Remove any prompt instruction or host
fallback that asks commentary to cause the mandatory search; commentary remains
non-executable. Do not pre-execute the tool, add a second budget, synthesize a
`CallToolStep`, persist a generic observation, or add a workflow/retry layer.
The caller still commits the final one-shot result under its existing rules.

For the sealed structured-agent instruction release from kernel
`09a1af093479aa92f3e783f4b4a7cc38e301a4a7`, consumers pin the successor
kernel revision and regenerate their lock to exact provider-runtime revision
`8fde23ac56571a63c65cfcff55c73a0976f83eb4`. Keep `llm-tools` at
`9e6d155f3b64f03495911435b7cae8b8d131f9a2`, and keep both the
`openai-codex` Python package and bundled CLI at `0.144.4`. The provider route
remains `backend="codex", transport="sdk"`; the transport literal is the
compatibility name for provider-runtime's directly owned App Server stream.

The public kernel additions are `KERNEL_BASE_INSTRUCTION`,
`KERNEL_BASE_INSTRUCTION_REVISION`, `KERNEL_BASE_INSTRUCTION_SHA256`, and
`KERNEL_BASE_INSTRUCTION_IDENTITY`; no function or port signature changes. The
identity for this release is
`llm-agent-kernel-contained-structured-agent-v1:sha256:1817c90f24bf9149f20f94b69f825d9be0b78df8bb46b1d24ed2691cf71b80e7`.
It participates in every definition fingerprint independently of application
configuration. Old session references remain in their former fingerprint
namespace and are not resumed; the next run cold-bootstraps from canonical
host context. A host MUST NOT manually bump
`session_compatibility_revision` solely for this release because the new kernel
identity already provides the required rotation.

Jarvis migration is only: repin the released kernel, regenerate its lock,
record the kernel/provider/tool/Codex revisions and base-instruction identity in
the compatibility manifest, preserve its existing application
`session_compatibility_revision`, and allow affected sessions to cold-bootstrap.
Keep Jarvis role/stable context and any provider `system`/`developer` values as
application instructions; do not copy or parameterize the kernel text. Keep the
existing frozen plans, HostTables, dispatcher, budgets, session-ref schema,
persistence, and `(codex, sdk)` route. Continue rejecting every
`AgentToolUse`/`AgentPermissionRequest` and treating provider `ProtocolDefect` as
fatal with no accepted or replayed terminal. Do not add native method parsing,
commentary parsing, dynamic tools, MCP, or another execution path.

The base instruction replaces Codex's built-in coding-agent prompt for new,
resumed, reconstructed, continuing, isolated, and initial-Read-backed sessions.
It is bounded behavioral guidance, not authority. The corrected provider event
boundary still contains and detects native Code Mode rather than proving it
absent before the first event. Unknown protocol drift intentionally breaks
availability. Read-only provider containment is not by itself a
host-confidentiality boundary; use OS/container read isolation where required.

For the dependency propagation from kernel `b53e4329d6a8fc8af622747c9670cf586cf9e1ff`,
a consumer pins the successor kernel revision, regenerates its lock to exact
`llm-tools` revision `9e6d155f3b64f03495911435b7cae8b8d131f9a2`,
records both immutable revisions in its compatibility manifest, and bumps its
owner-controlled `session_compatibility_revision`. Every catalog containing
`web.read` must expect `llm-tools-web-read-v2`; rebuild and freeze its maximum
and selected profiles and plans, then republish their `HostTable` sections.
Evidence consumers must recognize `plain-text-v2` and
`html-visible-text-v2` for new reads while retaining any historical v1 receipt
as historical evidence rather than rewriting it. `json-canonical-v1` is
unchanged. The `WEB_READ_SPEC` contract and limits, `web-read-v1` policy epoch,
policy inputs, and policy revision remain unchanged.

No `web.search` migration is introduced by this release: implementation
`llm-tools-web-search-v2`, policy epoch `web-search-v2`, its contract, policy
revision, policy inputs, 12-second operation deadline, and provider callback
API remain exactly as qualified at the parent kernel revision. The release
requires no kernel API, provider-session schema, authority, effect-ID, durable
action schema, replay, recovery, or uncertainty change. The kernel owns no
persistent profile, plan, HostTable, or evidence store to migrate.

The host supplies `ToolBudgetFactoryPort`, not a budget created before claim.
After `claim` reveals the selected plan and the kernel proves the exact frozen
plan/catalog relationship, the factory creates that run's `BudgetState` from
the supplied plan. Its `limits` must exactly equal
`plan.profile.run_limits`. A mismatch parks thread input or rejects a one-shot
before rendering, admission, provider I/O, or tool I/O.

The admission journal reserves the run's configured maximum turns and token
allowances plus one live root slot before provider I/O. Clean settlement records
available actual usage and refunds unused capacity. Startup recovery releases
only an orphan's live slot; its rolling turn/token reservation remains charged.
A corrupt or missing journal fails closed.

`AgentRuntime` reports token usage after a turn and supplies no hard turn-level
token cap. The admission adapter must therefore add a finite, route-qualified
one-turn input/output overshoot allowance to the requested token reservation.
This only protects the rolling journal from a terminal report above the kernel
threshold; it does not increase `KernelLimits`. Jarvis must record and qualify
those route-specific values before release.

The dispatcher owns effect identity and execution. Before a `Write` enters
`llm-tools`, it durably creates or resolves the action record and supplies its
stable ID as both `InvocationPosition` and `EffectId`. It preserves the kernel's
immutable claim/checkpoint/input/model-step lineage. Suspension persistence
includes the opaque host reference, tool ID, original validated arguments,
resolution state, and safe evidence.

No database transaction or blocking row lock may span provider or external tool
I/O.

`KernelLimits.max_cooperative_seconds` is not an end-to-end request SLA. The
kernel checks elapsed time at safe boundaries and supplies the remaining value
as the provider-turn deadline. Checkpoint, context, session-reference,
admission, dispatch, settlement, release, park, and cleanup calls are
cooperative and may finish after it. Tool execution remains independently
bounded by the validated plan's `RunLimits.max_elapsed_seconds`; hosts must not
add a blunt outer timeout around a `Write` that bypasses durable recorder and
reconciliation handling.

`KernelLimits.max_new_context_bytes` counts only UTF-8 bytes the kernel newly
renders and submits during that invocation. The kernel base instruction,
provider application system/developer content, output-schema transport overhead,
history retained by the native session, and provider compaction are outside it.
Hosts must size provider-native context separately and continue supplying
bounded canonical context and tool results; the kernel will not silently
truncate required effect or reconciliation evidence.

## Qualification

Ordinary CI is deterministic and network-disabled. It proves exact request
shape, complete `stream_turn` inspection, disabled native authority, pure plan
and whole-step validation, serial dispatch, session CAS ordering, bounded
context, polling/finalization races, admission recovery, and isolated cleanup.

Before a release, the first real consumer must additionally qualify its durable
checkpoint, action/recorder, admission, and delivery implementations under
process termination at each boundary. It must also pin its compatibility-
revision policy and qualify plan-aware budget construction against every
selectable plan. Jarvis must run its paid Codex account qualification for the
exact provider-runtime and provider-certified Codex SDK pins on at least one
currently supported local-account route, including conversational, structured
nested/nullable result, commentary-plus-final-answer behavior when observed,
JSON-string arguments, continuation, close/reopen/resume, invocation-local
usage, and in-flight cancellation. The current qualified route is
`gpt-5.6-terra`; retired `gpt-5.4` MUST NOT be invoked through `local_account`.
Qualification records contain only sanitized route, revision, status, usage,
timing, and trace identifiers. Provider-native
transcripts remain unredacted third-party data at rest; deleting a local
reference does not promise provider deletion.

A dependency-only `llm-tools` propagation may carry that paid provider
qualification forward only when the exact `provider-runtime` and Codex SDK
pins, kernel provider adapter, containment request, and structured-output wire
are unchanged and the complete deterministic suite still passes. The
`web.read` extraction propagation meets those conditions. Any provider-facing
change requires the paid matrix to run again.

This provider-runtime propagation changes a provider-facing input and therefore
requires the paid matrix on the currently supported `gpt-5.6-terra`
local-account route. The continuation probe must prove same-lease per-turn
addition and close/reopen/resume without historical recharge; the structured
probe must exercise authoritative final-answer selection when commentary is
observed; and the separately gated in-flight cancellation probe must also run.
Quota exhaustion runs only against a qualification profile that is already
exhausted and MUST NOT be induced for release testing. The retired `gpt-5.4`
local-account route is neither a release gate nor a permitted probe.

The input-projection release changes model-visible context and definition
identity, so it also requires the current `gpt-5.6-terra` matrix rather than
carrying prior qualification forward. Its structured probe must submit the
restricted projection with explicitly requested batch `as_of`; the regular
continuation, JSON-string argument, and separately gated in-flight cancellation
probes remain required. Retired `gpt-5.4` and deliberately induced quota
exhaustion remain prohibited.

The isolated initial-Read release also changes model-visible first-turn context
and therefore runs the current `gpt-5.6-terra` matrix rather than carrying prior
qualification forward. In addition to continuation, structured
commentary/final-answer, JSON-string argument, and separately gated in-flight
cancellation probes, it runs the kernel one-shot entry point with a known typed
initial Read result and proves that value is usable by the first provider turn.
Retired `gpt-5.4` and deliberately induced quota exhaustion remain prohibited.

The sealed base-instruction release changes every Codex session's model-visible
system input and therefore runs the current `gpt-5.6-terra` matrix rather than
carrying prior qualification forward. It additionally uses one synthetic Read:
natural language must produce the structured `call_tool`, the typed observation
must be projected and used by the following turn, normal execution must emit no
native exec event, and an adversarial shell/exec request must either remain in
the structured protocol or fail containment with zero host effect. Fresh and
close/reopen/resumed sessions are required. The changed provider lane is Codex;
provider-runtime's Claude implementation is unchanged, so no fresh Claude
qualification is required. Retired `gpt-5.4` and deliberately induced quota
exhaustion remain prohibited.

The library release commands are:

```console
uv sync --frozen --all-groups
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest -q
uv build
uv run pip-audit
git diff --check
```

## Shared-kernel paid-decision cutover

The current contract is [SPEC section 17](../SPEC.md#17-durable-paid-decisions).
Thread calls supply the host-backed `decisions` journal. Isolated calls supply
`DurableIsolatedDecisions(IsolatedDecisionScope(stable_operation_id), journal)`
or explicitly `TransientModelDecisions()`. Historical migration examples above
predate these required arguments and are not the current invocation contract.

Persist original request and normalized terminal separately from native session
references and Write actions. Restore original claim inputs/checkpoint/as-of
before retries; consult armed uncertainty before no-progress limits. Preserve
action recovery priority. Store existing typed role evidence atomically with
the terminal and restore it for replay; do not parse prompt history as authority.

`DispatchLineage` now requires definition fingerprint and model decision ID.
Both model-derived lineages expose the exact accepted decision `position` for
Read recorders. Initial Reads require the stable isolated operation ID and use
a disjoint position. Recoverable BilledOnce reads need a durable llm-tools
recorder. Write positions remain the host action IDs, admitted after existing
policy/approval; the kernel model journal never replaces them.

An exception after provider entry retains paid uncertainty, including a stop
before the first provider event. Do not automatically release or redispatch it.
This explicit availability cost prevents duplicate billing. No table here is
an outbox, scheduler, approval system, or general-purpose workflow engine.
