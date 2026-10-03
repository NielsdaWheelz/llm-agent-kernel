# llm-agent-kernel specification

this is the current reusable contract. [native supervision](docs/native-agent-spec.md)
is normative detail; [adr 0010](docs/decisions/0010-native-agent-supervision.md)
supersedes the former conversational step loop, session cache and capacity
admission. [evidence](docs/native-agent-evidence.md) distinguishes implemented
behavior, controlled proof and installed live qualification.

## 1. goals

one shared supervisor for jarvis and nexus; truthful provider evidence, durable
acceptance before actions, responsive control and useful work after cold restart.
keep application authority and canonical state in the application. codapt supplies
native supervision semantics; byte parity, workspace tools and its machine/billing
infrastructure are excluded.

## 2. dependencies and implementation gate

python 3.12+. `pyproject.toml` and `uv.lock` name exact immutable provider-runtime
and llm-tools revisions. install the frozen lock. no sibling-source import is an
installed qualification. the qualified native binary is stock codex 0.160.0;
consumer manifests pin that version.

| dependency | exact candidate revision |
| --- | --- |
| llm-tools | `2adb9790fc7a54de5342effaca9391c2f3d24ff9` |
| provider-runtime | `98913f35ab4c9bef2af85d90fd6e4bed747bd64c` |

any unsupported exact capability fails
before arm/submission; never substitute another model, effort, tool or route.

provider-runtime owns SDK integration, structured-output lowering, native callback
transport, native identities, authoritative submission/finality and per-turn
control. llm-tools owns prompt rendering, declarations, frozen profiles/plans,
pure validation, execution, budgets, durable position/replay contracts and results.
the kernel must use these public mechanisms rather than copy their internals.

## 3. ownership

| owner | responsibility |
| --- | --- |
| provider-runtime | prepare exact wire request; classify send facts; correlate native events/callbacks/control; preserve original terminal |
| llm-tools | schemas/plans and one executor/recorder/accounting contract |
| kernel | validate effective authority; supervise callback/input/control ordering; enforce host journal boundaries |
| application | requests/context, owner permits, transactions, action identity/consent/reconciliation, publication/outbox |
| native host | account state, persistent stock server, private socket and private read-only cwd |

the kernel owns no application table, migration, queue, scheduler, credential
store, memory service, delivery transport, approval policy or action ledger.

## 4. core values

`NativeDefinition` binds exact `ProviderConfiguration`, `AgentRole`, provider
output contract, maximum frozen profile, compatibility revision and finite
`NativeControl`. its fingerprint includes complete containment, exact schemas,
base instruction identity, tool authority and control bounds.

`NativeRequest` binds stable attempt, scope, operation, ordered canonical input
ids, canonical/submitted prompt sections, frozen plan, recovery policy, absolute
optional deadline and thread checkpoint. its fingerprint excludes renewable owner
token; ownership renewal cannot change immutable work identity. `OwnerPermit`
proves current application ownership and explicit parent invocation for an
isolated gate. native call ids identify proposals; they never authorize effects.

`NativeInvocationProposal` freezes original arguments, call/tool identity,
input/checkpoint lineage and all plan/binding revisions. `InvocationRecord`
identifies host acceptance and immutable `NativeReply`. `DispatchCompleted`
contains the original llm-tools result, required host-rendered `model_text` and
optional host receipt reference. the kernel submits that text unchanged;
`DispatchSuspended` is an existing durable host wait, not execution success.

## 5. exact provider surface and containment

`AgentRuntime.prepare_turn` prepares native work; `prepare_observed_turn`
prepares bounded isolated observation and rejects declared callbacks. both share
provider evidence and prepare before the journal arms them. immutable
`AgentAttempt` includes exact request digest. `AgentTurnRef` identifies the
accepted native session/turn. unsupported schema/model/callback composition is a
preflight refusal, not a route fallback.

native codex built-ins, web, MCP, inherited environment, network and unsolicited
permissions are disabled. cwd is private, empty and read-only. host callbacks
are the only application tools. a native tool/permission event is a containment
defect: fence callbacks and discard only that session. the account host retains
credentials; worker state is empty and accountless. native host network for model
authentication is distinct from model/tool network authority.

## 6. structured model protocol

native main uses the provider's native reasoning loop, declared callbacks and
exact text or strict JSON terminal contract. completed public commentary is plain
prose, observational and may precede terminal. the final output format belongs
only in the final response. commentary cannot settle a request or action.

isolated `run_one_shot` retains one closed `call_tool` or `finish` value and
serial read-only host tools for real gate/context/memory roles. `say`,
`run_thread`, conversational session/cache/CAS and capacity reservations are
removed. validate the complete step and pure arguments before dispatch.

## 7. tool boundary

prove exact plan/catalog consistency and tightening of definition maximum before
rendering or I/O. publish and execute the same declarations and frozen revisions.
one callback dispatch at a time; finite overlap buffers queue arrival order.
unknown tools never execute; known invalid arguments retain original evidence and
a bounded typed rejection, with zero handler entry.

the host journal accepts immutable invocation before dispatch. writes require
host-created effect identity; `InvocationPosition` equals `EffectId`. reads and
isolated gates retain their own original invocation identities. commit the
original executor result, then immutable callback reply, before sending that
reply. duplicate identical callbacks replay; changed bytes/revisions fail closed.
an entered unknown action never becomes fresh merely because a model changes
call id. domain reconciliation remains application-owned.

## 8. context and steering

canonical host context cold-bootstraps useful work; native history is disposable.
new input is polled while reasoning and callbacks wait. `NativeDelivery` retains
prepared/sent/queued/recorded/rejected facts. queued acknowledgment does not prove
recorded input or model attention. later steer cannot reattribute an accepted
invocation to newer inputs. ambiguous delivery never silently resends an action.

`NativeMessagePort` commits completed commentary and delivery outbox atomically
and idempotently. partial network deltas are not completed public messages. host
request settlement keeps earlier unfinished work when another topic arrives.

## 9. checkpoint, settlement, and recovery

native arm precedes provider submission. retained evidence has three distinct
forms: authoritative non-submission, exact sealed native terminal, and unresolved
submission. a timeout, `TurnNotStarted`, RPC error, missing id or absent usage is
not negative submission proof.

native terminal/usage/raw payload commit before cleanup or application decoding,
resolution and publication. local stop/fence/cancel acknowledgment is separate
from native finality. an original safe failure or valid terminal survives later
cleanup/product failure. native `turn/completed` evidence may preserve a failed
or interrupted turn with unfinished callbacks; successful completion requires a
valid resolved native lifecycle.

### 9.3 run admission

`OwnerPort.require_current` fences provider/effect entry and settlement authority.
there are no capacity reservations or fabricated token charges. an explicitly
serial isolated gate uses the current owner's permit and parent invocation; its
wait cannot block transport/control reading. no unused input is automatically
rearmed by cleanup.

## 10. limits and cancellation

no task-wide native usage/call/elapsed quota is required. jarvis main has no
arbitrary elapsed cutoff. nexus owns its job deadlines. tool deadlines, individual
input/output bounds, in-flight serialization and transport buffers remain finite.
`llm_tools.RunLimits` may omit each cumulative quota; use the shared budget algebra
and never double-account reservation, settlement or replay. provider context/output
policy is admission/reservation, not an invented native inner-loop token ceiling.

stop promptly revokes callback authority, records control independently and
interrupts only the affected turn. stopping cancels never-entered approval/action
work in the host. entered effects still settle truthfully or require reconciliation.
a stalled callback or withheld start acknowledgment cannot starve control.

## 11. run algorithms

`run_native`: validate -> require owner -> recover own sealed truth if present ->
prepare exact provider request -> durably arm -> submit -> supervise input,
commentary and serial callbacks -> commit original terminal -> cleanup. each
callback is validation -> host acceptance -> dispatch -> durable result -> durable
reply -> wire reply. the transport reader remains independent of effect execution.

`run_one_shot`: validate frozen read-only plan -> require owner -> recover or arm
exact model decision -> stream provider turn -> commit original evidence -> decode
whole step -> dispatch at accepted isolated position -> continue or finish.
recoverable paid inference explicitly selects `DurableIsolatedDecisions`;
disposable inference explicitly selects `TransientModelDecisions`.

## 12. outcomes

native execution returns provider `AgentTerminal` with mandatory
`NativeTerminalEvidence` or `LocalStopEvidence`. only exact own native seal can
produce `NativeRecovery`; local stop never supplies recovery authority.
`AgentNotSubmitted` is a separate authoritative provider submission fact.
`NativeUncertain` preserves the armed unresolved attempt. it is never automatic
redispatch permission. isolated outcomes remain `OneShotCompleted` or
`OneShotStopped`, with original accepted decision/usage retained.

## 13. observability and privacy

use existing redacted kernel events/diagnostics. do not persist private raw
transcripts or credentials for qualification. public fixtures may retain exact
receipts. raw provider evidence belongs to the host's durable journal; product
text is its separately derived projection. XML-like prompt structure establishes
provenance, not a security boundary.

## 14. required conformance

[native acceptance](docs/native-agent-spec.md#9-delivery-and-acceptance) assigns
N001–N020 exactly once. required verification includes controlled transport faults,
actual recorder/store transactions, owner/process loss, real selected model plus
research tools and strict JSON, containment and installed immutable artifacts.
[the delivery plan](docs/native-agent-plan.md) specifies red/green/refactor and
owner-requested deletion of new temporary feature tests after final proof.
existing applicable conformance stays. static checks do not prove live behavior.

## 15. explicitly deferred

program execution, parallel tools, delegation graph, application workflow engines,
memory redesign, native shell/files/web/network, compatibility lanes and new
multi-user infrastructure. do not add abstractions for hypothetical consumers.

## 16. shared generation protocol

`llm_agent_kernel.generation.run_generation` serves the retained raw API generation
lane. `GenerationTurn` carries exact generation/model-turn identity;
`GenerationProposal` may contain ordered API-native multi-call proposals whose
results execute serially through the application's canonical tools.

### 16.2 durable decisions and acknowledgment

`GenerationLifecyclePort` arms each child and commits its original terminal before
`resolve_terminal` performs product validation. the lifecycle owns authoritative
continuation evidence; a product rejection cannot erase a successful provider
terminal or authorize another paid call. API continuation may reopen only its
exact sealed original successor identity and persisted continuation.

### 16.3 cancellation and limits

`GenerationControlPort` polls at safe boundaries; no generic timeout destroys
host cleanup/settlement. `max_turns` is optional, with configured per-turn and
host/tool bounds preserved. native callback execution calls `run_native` directly;
do not nest journals or a second generation loop around its native inner loop.

## 17. durable paid decisions

host-backed `ModelDecisionJournal` stores exact request, arm, authoritative
non-submission or original terminal before interpreting a model choice. recover
paid decisions from their original record, never by regenerating a similar choice.

### 17.1 explicit recovery contract

`DurableIsolatedDecisions` supplies journal and `IsolatedDecisionScope`;
`TransientModelDecisions` marks disposable work explicitly. supplied resume state
must match exact definition, run/step, plan and request identity. accepted action
records, original arguments/revisions and effect identity remain host authority.

### 17.2 recovery and uncertainty

own native seal permits local product replay with zero provider/catalog calls.
exact original-attempt non-submission proof permits local failure settlement.
missing proof, local stop, parent outcome or exception naming stays uncertain.
jarvis may restart reasoning in a fresh thread only after fencing the old attempt;
original action barriers survive. nexus never redispatches an uncertain generation.

## 18. native agent target requirements

[the accepted detailed contract](docs/native-agent-spec.md) governs jarvis/nexus
composition, schemas, content requirements and N001–N020. implementation status and
exact qualified artifacts live in [evidence](docs/native-agent-evidence.md), with
[metadata handoff](docs/integrations/nexus-metadata.md). historical ADRs describe
former decisions; they cannot reactivate deleted runtime paths.
