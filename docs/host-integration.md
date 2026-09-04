# Host integration and release qualification

`llm-agent-kernel` deliberately stops at asynchronous ports. A production host
must implement persistence and product policy outside this package; replacing a
store with an in-memory adapter changes the recovery guarantee and is not a
deployment option for continuing effectful work.

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
renders and submits during that invocation. Provider system/developer content,
output-schema transport overhead, history retained by the native session, and
provider compaction are outside it. Hosts must size provider-native context
separately and continue supplying bounded canonical context and tool results;
the kernel will not silently truncate required effect or reconciliation
evidence.

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
exact provider-runtime and provider-certified Codex SDK pins, including
conversational, structured nested/nullable result, and JSON-string argument
probes on `gpt-5.6-terra` and `gpt-5.4`, and record only sanitized route,
revision, status, usage, timing, and trace identifiers. Provider-native
transcripts remain unredacted third-party data at rest; deleting a local
reference does not promise provider deletion.

A dependency-only `llm-tools` propagation may carry that paid provider
qualification forward only when the exact `provider-runtime` and Codex SDK
pins, kernel provider adapter, containment request, and structured-output wire
are unchanged and the complete deterministic suite still passes. The
`web.read` extraction propagation meets those conditions. Any provider-facing
change requires the paid matrix to run again.

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
