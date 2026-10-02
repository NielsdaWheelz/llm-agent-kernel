# adr 0010: supervise native agents without importing application policy

- status: accepted target design; implementation and qualification pending
- date: 2026-10-02
- scope: provider submission/finality, native callbacks and consumer adoption
- amends for the native extension: adrs 0003, 0005, 0006, 0008 and 0009; preserves existing
  protocol guarantees except where an adopted extension explicitly changes them

settled owner requirements are recorded in [SPEC section 18](../../SPEC.md#18-native-agent-target-requirements):
no model usage budgets, no native shell/files/network, automatic reasoning recovery
after callback fencing with action recovery barriers, and no arbitrary cutoff for
jarvis main. pending approval blocks its action and dependent work while independent
work continues. jarvis provides brief public progress and useful partial answers;
new requests arrive promptly while unfinished work remains in context. owner stop
cancels pending approvals for that work, preserving already-dispatched effects.
metadata separately requires conservative uncertain-step recovery and the exact
contract in the [integration handoff](../integrations/nexus-metadata.md).

## problem

jarvis proposes a native inner loop; nexus needs accurate submission and terminal
settlement on its existing route. codapt demonstrates useful supervision but
bundles root execution, application stores, model fallback and continuation policy.
copying it wholesale would move responsibilities into the wrong library and
preserve failure paths that withhold terminal bookkeeping.

current exceptions cannot prove no native submission. current terminal types can
represent synthetic local failures. the current terminal-first journal cannot
identify several callbacks within a single native turn. the old admission excess
calculation is unnecessary for the selected target, while the serial paid-child
slot assumption needs replacement with correct nested-turn ownership.

## decision

adopt the boundaries in the [native agent spec](../native-agent-spec.md).
the accepted codapt-derived kernel contract is authoritative for shared agent
behavior. dependency and consumer contracts must change to satisfy it; current
APIs and pins are not target-design constraints. codapt2 is the reference subject
to the explicit owner decisions, not a competing normative specification.

provider-runtime owns native protocol evidence, control and publication lowering;
llm-tools owns portable declarations/plans, validation and execution; the kernel
owns ordered supervision; applications
own durable storage, authority and recovery. no new workflow service or executor.

deliver submission/finality repair and nexus adoption independently of native
callback qualification. durably retain valid provider evidence before product
acceptance. introduce a durable accepted invocation before each callback effect,
and record its result before reply. preserve current owner/generation fencing,
explicit transient inference, host effect ids and provider session disposability.

return durable pending-action status to the native callback while approval waits.
continue independent work; yield when genuinely blocked. later action resolution
is ordinary input about the original action, never a model reproposal or a changed
reply to an already-completed callback. approval policy remains application-owned.

public progress and partial answers use the existing observation/delivery path.
they never authorize effects or substitute for canonical action/task outcomes;
nexus structured-output publication keeps its own validation boundary.

share contained native callbacks for application tools in both consumers. nexus's
shell/http route is a migration source to retire, not an alternative target.
qualification proves the selected scope; it cannot authorize broader native tools.

## selected design and costs

this introduces a public provider evidence contract and host journal obligations,
so consumer schema/migration and installed-route qualification are required.
usage remains observational; no task-wide model/tool budget or arbitrary jarvis task
deadline is required. automatic recovery can repeat reasoning after old callbacks
are fenced, while unknown action outcomes still require reconciliation. pending
approval, callback reply recovery and nested gates must be proved on the shared
server. the spec now selects provider handles/evidence, kernel ports, host schemas,
control/input settlement, write envelopes and optional quota algebra. the
[delivery plan](../native-agent-plan.md) assigns files and non-overlapping slices.

fresh native threads after disconnect trade hidden reasoning for simpler recovery.
semantic duplicate uncertainty restricts new writes for affected old requests.
nexus's direct worker/socket integration removes a relay but shares server failure
impact. stopped hard cutover requires settling legacy dispatched actions and fresh
consent for migrated pending approvals. new feature tests are deleted after recorded
red/green/refactor proof by owner instruction, sacrificing their future regression
coverage; final runtime artifacts must still match the qualified artifacts.

failed callback qualification requires investigation and repair at the responsible
layer. a proven limitation that requires changing accepted behavior must return
to the owner as a concrete tradeoff; it does not authorize silently retaining v1
or the shell/http bridge as the target. existing disposable inference remains in
scope for its separate roles; it need not adopt a native main-agent loop.

## implementation gate

SPEC section 18 adopts this design following the owner interview. implementation
must deliver the specified contracts/schemas and assigned acceptance slices.
source review or historical native-shell success cannot qualify callbacks.
see the [review](../native-agent-review.md) for findings, sources and test limits.
