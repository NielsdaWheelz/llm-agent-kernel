# native agent adversarial review

this is the historical design review. current implementation and installed
acceptance are recorded in [evidence](native-agent-evidence.md); its results below
do not claim the later implemented tree is still untested.

follow-up owner decisions supersede this initial review's optional budget and
shell-retention recommendations: no model usage limits; no native shell/files/
network in either app; automatic reasoning recovery with action barriers; no
arbitrary jarvis cutoff; continue independent work during pending approval.
see [SPEC section 18](../SPEC.md#18-native-agent-target-requirements).
the source findings below remain evidence about the inspected baseline.
the detailed follow-up [contract](native-agent-spec.md) and
[plan](native-agent-plan.md) select the implementation design. metadata retains
its explicit uncertain-step redispatch barrier; jarvis uses fenced reasoning
replacement. native transport reconnect/replay is not a target requirement.

reviewed 2026-10-02. recommendation: extract native supervision, preserve existing
owners, and repair submission/terminal evidence before migrating tool transport.
the current plan is NOT a perfect codapt copy and should not become one.
the [native spec](native-agent-spec.md) incorporates two review passes from
three independent agent reviewers: codapt supervision, consumer durability, and
provider/tool contracts. this is source review and limited deterministic evidence,
not human expert certification, production acceptance or proof of optimality.

## evidence baseline

| repository | inspected head | relevant pins |
| --- | --- | --- |
| kernel | `c5236809e3d8765b28e169792f50d24713c8a31a` | provider `69d41d38a3d290e7ae3bde9b57556dda41e1b2f1`; tools `9e6d155f3b64f03495911435b7cae8b8d131f9a2` |
| jarvis | `cc4873fabce7f0c3f0b024b3ab13242a4569b04f` | kernel `8f6f15e39a99ed25f1a9cf8a1a50f5c4a76b6342`; provider `69d41d38…`; tools `9e6d155…` |
| nexus | `a494f743eb402b0cbb6069066fca4143b24036f0` | kernel `937434b051d99c3dd10402db23e16d8baf129ebd`; provider `6a7093f799c88c205c8d797bbb8b14c2a9980db1`; tools `d305da8fb5f5eda89049779c4c4dfa4f1916618c` |
| codapt2 | `9a957c1ddd5b85cd7c4dcca72b730a9bdcccacb2` | source codex target `0.153.1`; not an installed-build observation |
| provider sibling | `4ddced3bb5487ce988858c4c6d45d2e5ee0acad9` | different from kernel's pin; pinned source inspected using `git show` |
| llm-tools | `9e6d155f3b64f03495911435b7cae8b8d131f9a2` | matches kernel pin |

kernel was clean at entry. jarvis had unrelated `.idea/`; codapt had unrelated
ide/configuration changes and a modified database helper. nexus had extensive
documentation edits/untracked tickets. those were read as local records where
relevant and were not changed. sibling links below assume this checkout layout;
provider links use the actual immutable kernel pin, not its stale sibling head.

## findings that change the design

### 1. non-submission is a missing provider fact, not an exception policy

high; current contract limitation. pinned provider `TurnNotStarted` means no
persistable native identity, and runtime timeout/cancel can raise it before the
first event although native submission has already been attempted. the kernel's
conservative post-entry uncertainty is correct. codapt's transient `requestSent`
flag also does not export a durable, typed guarantee through its helper boundary.

evidence: pinned [errors.py:80](https://github.com/NielsdaWheelz/llm-calling/blob/69d41d38a3d290e7ae3bde9b57556dda41e1b2f1/src/provider_runtime/agent_runtime/errors.py#L80),
`runtime.py:1135–1161`, `codex_sdk.py:690–698`;
[kernel decisions.py:187](../src/llm_agent_kernel/decisions.py#L187);
[codapt rpc.ts:100](../../codapt2/src/main/server/codex/internal/runtime/rpc.ts#L100).
resolution: provider-owned evidence for the exact attempt, including no delayed
send; pure incompatibilities rejected before arming. never infer it from names,
missing ids, missing usage or generic rpc rejection.

### 2. a typed terminal does not establish native finality

high; current representation gap. provider-runtime synthesizes timeout/cancel
terminals and converts general post-start transport errors into failed terminals.
the event has no origin field. nexus also manufactures its normal terminal
envelope from local failures; its `accepted_at` describes host admission. therefore
“preserve every terminal” is insufficient: preserve origin and native evidence,
and keep unresolved submission separate from local operation termination.

evidence: pinned [codex_sdk.py:746](https://github.com/NielsdaWheelz/llm-calling/blob/69d41d38a3d290e7ae3bde9b57556dda41e1b2f1/src/provider_runtime/agent_runtime/codex_sdk.py#L746),
`runtime.py:1231–1254`, `events.py:188–208`;
[nexus terminal contract:366](../../nexus-web/python/nexus/services/codex_generation_contract.py#L366),
`apps/codex_agent/host.py:1398–1421,1444–1462`.
this is not proof that every such local failure leaves native work running; it
proves the current type cannot establish which case occurred.

### 3. nexus couples provider evidence to product acceptance

high; current source defect. `complete_child` writes the child terminal, invokes
product resolution/encoding, then commits the same transaction. a product error
can roll back valid provider evidence. separately, `normalized_failure` raises
for `invalid_request`/`runtime_defect` before evidence acceptance. this explains a
real uncertainty path without proving the historical per-job exception cause.

evidence: [llm_execution.py:783](../../nexus-web/python/nexus/services/llm_execution.py#L783)
through commit at 829; `_child_terminal_documents:1029–1033`;
[codex_generation_contract.py:471](../../nexus-web/python/nexus/services/codex_generation_contract.py#L471).
reproduction to implement: force the product encoder/resolver to raise after a
valid child terminal, restart, and inspect the child journal. required result:
original native terminal survives and local processing resumes without inference.

### 4. cleanup and cancellation can erase terminal evidence earlier still

high; current source defect. nexus stores the received terminal locally, then
cleanup, credential sync or cancellation can replace it. the provider/kernel path
also has pre-journal cleanup failures. the provider must establish finality for
one finite turn stream, independently of its long-lived connection and cleanup.
preserving an observed frame must not authorize effects after a protocol defect.

evidence: [nexus host.py:1032](../../nexus-web/apps/codex_agent/host.py#L1032),
`:1149–1156,1172–1179,1194–1201,1221–1228,1237–1238`;
[kernel provider.py:243](../src/llm_agent_kernel/provider.py#L243);
pinned `codex_app_server.py:259–271`, `runtime.py:755–759`.
test simultaneous native terminal and timeout/stop, not only sequential cases.

### 5. codapt intentionally withholds normal terminal bookkeeping on some failures

high if copied; deliberate codapt policy. `Unrecoverable` native failure exits
before checkpointing, normal usage settlement, cleanup and terminal publication,
retaining ownership/native transcript for operator repair. it does not lose all
raw evidence, but it couples that repair policy to accepted terminal bookkeeping.
the shared library must preserve terminal truth first and report repair separately.

evidence: [service.ts:1101](../../codapt2/src/main/server/codex/service.ts#L1101),
bookkeeping begins at 1130;
[completion.test.ts:587](../../codapt2/src/main/server/codex/completion.test.ts#L587)
asserts this behavior. this is a counterexample to treating codapt as a correctness
oracle, not an allegation that its authors accidentally omitted the path.

### 6. jarvis needs a new durable unit: accepted invocation

high; planned migration gap, not a present v1 regression. current journal decisions
complete only with `AgentTerminal`; Read positions and paid write-gate operation
ids derive from that decision. multiple callbacks before one terminal cannot reuse
the old cardinality without aliasing separate work. persist each invocation before
dispatch and each result before reply; qualify stable ids, claims and recovery.

evidence: [decisions.py:304](../../jarvis/src/jarvis/decisions.py#L304),
`:346–362`; [read_positions.py:69](../../jarvis/src/jarvis/read_positions.py#L69);
[write_dispatch.py:202](../../jarvis/src/jarvis/write_dispatch.py#L202).
“reuse model_decision/read_position/action” identifies owners, not a completed
schema design. active session/turn fencing must also precede the first callback,
instead of waiting for the existing post-terminal reference CAS.

### 7. native turns invalidate old admission arithmetic

high; planned migration gap. one native turn can include many inference rounds.
the current kernel already lacks a hard per-turn token cap, but reserves excess
from qualified finite context/output bounds. those bounds cannot be assumed to
cover an opaque native loop. jarvis's paid write gate also opens a second native
turn while the parent awaits a callback, changing the serial child-slot premise.

evidence: [run admission](../SPEC.md#93-run-admission), historical v1 baseline lines 848–862 (superseded by native owner-only admission);
[jarvis admission.py:487](../../jarvis/src/jarvis/admission.py#L487);
`definitions.py:151–174`; `write_dispatch.py:202–210`.
resolution: qualify a finite exposure bound or explicitly amend native-lane
admission to a host-selected soft budget. separately account for nested gate
capacity and prove the shared transport cannot deadlock while it runs.

### 8. callback transport is proposed, while many reusable tool seams already exist

high activation gate; limited implementation need. pinned provider denies
`item/tool/call`, and the kernel rejects native tool events. existing provider
control can steer/interrupt externally owned threads, but that is not a declared
callback handler on `AgentRuntime`. meanwhile llm-tools already supplies native
exposure, public plan validation and async execution/recorders, and provider-runtime
already has tool publication/lowering. a new registry/executor would duplicate owners.

evidence: pinned [codex_app_server.py:44](https://github.com/NielsdaWheelz/llm-calling/blob/69d41d38a3d290e7ae3bde9b57556dda41e1b2f1/src/provider_runtime/agent_runtime/codex_app_server.py#L44),
`codex_control.py:26,307–335`, `tool_adapter.py:86–237`;
[llm-tools profiles.py:232](../../llm-tools/src/llm_tools/profiles.py#L232),
`:321–329`, `validation.py:9–15`, `execution.py:87–155,242–418`;
[kernel tools.py:51](../src/llm_agent_kernel/tools.py#L51) currently requires `HostTable`.
native exposure needs appropriate plan admission and projection, not a second budget.

## copy, adapt, reject

| codapt feature | disposition | reason |
| --- | --- | --- |
| native inner reasoning loop | adapt | useful autonomy; prove better task outcomes instead of assuming parity |
| correlated turn ids, expected-turn steering, reconnect observation | adapt | provider-owned mechanics; host owns durable input and uncertainty |
| interrupt acknowledgment separate from terminal | take | prevents false completion and premature resource release |
| canonical context separate from disposable session | retain kernel contract | native history alone cannot authorize effects or recover host truth |
| root workspace shell and full HTTP credential | reject as common default | product capability, incompatible with jarvis containment |
| silent model fallback on policy failure | reject | changes requested identity and cost/behavior without host selection |
| six-hour segment followed by continuation | reject as library policy | not a total execution bound; host chooses follow-through |
| app machine pools, account rotation, billing, scheduling | leave in codapt | different ownership and scale; unnecessary for this reusable boundary |
| native rollout-file parsing | avoid as public contract | recovery depends on native internals; prefer provider-owned typed evidence |
| failure classification before accepted terminal bookkeeping | reject | preserves uncertainty where terminal evidence should already be durable |

codapt references: [rpc.ts:100](../../codapt2/src/main/server/codex/internal/runtime/rpc.ts#L100),
[connector.ts:274](../../codapt2/src/main/server/codex/internal/runtime/connector.ts#L274),
`connector.ts:350–403`, `service.ts:2554–2603`;
[run-interruption.ts:7](../../codapt2/src/main/server/internal/agent/run-interruption.ts#L7),
`:58–65`, `service.ts:1204–1205`;
[turn-model.ts:5](../../codapt2/src/main/server/codex/internal/turn-model.ts#L5),
[pool authority](../../codapt2/docs/modules/main-codex-pool.md),
[workspace api](../../codapt2/docs/modules/main-workspace-api.md).
codapt's model-monitoring documentation itself describes best-effort identity
enforcement; do not turn its requested model into a guarantee about served work.

the recommended consolidation is one application-tool contract and, once qualified,
one native callback mechanism. shell authority is an independent product choice:
nexus might retain workspace execution while replacing its application HTTP bridge.
that mixed capability needs its own proof. jarvis must not gain shell merely to
share a tool transport, and nexus lifecycle repair must not wait for this migration.

## corrected attribution

- jarvis o3–o5 is planned; source/docs do not establish installed native callbacks.
- the historical nexus disabled-builtins/network/mcp mismatch is a credible
  source explanation, but its original per-job exception subtype was not retained.
  current nexus instead uses an explicitly approved broad remote execution route:
  [codex_generation_operations.py:31](../../nexus-web/python/nexus/services/codex_generation_operations.py#L31),
  configuration at 69–103. do not call that the same broken request.
- current nexus already logs bounded original failure class/code/stage/identities:
  [host.py:902](../../nexus-web/apps/codex_agent/host.py#L902). its older diagnostic-loss
  ticket is partly stale; terminal acceptance remains a separate problem.
- server topology also differs: jarvis requires its existing shared service;
  nexus's approved host starts/stops a per-generation server at `host.py:980–981`
  and `1180–1201`. host operations retain both policies; the kernel owns neither.
- the old cancellation/requeue ticket describes superseded code. current
  [tasks/chat_run.py:47](../../nexus-web/python/nexus/tasks/chat_run.py#L47) and
  `services/chat_runs.py:1033–1041` attempt local settlement, not automatic requeue.
- nexus's shell qualification report labels its cohort as pre-integration;
  [the report](../../nexus-web/docs/codex-shell-cutover-verification.md) is not
  current merged-tree or strict-json research acceptance.
- the last recorded stopped jarvis deployment and historical nexus incident
  records were not refreshed live. neither is asserted to describe today's service.
- provider sibling head and installed kernel environment differ from the declared
  pin. reviewing the checkout alone would falsely report existing APIs missing.

## what current practice supports

official app-server docs describe experimental dynamic tools, correlated callback
replies, per-turn output schema, expected-turn steering and interruption. they
do not establish crash-safe callback replay or contained-tool capability on the
installed route. source/interface existence and behavioral qualification remain
different evidence. [official protocol](https://learn.chatgpt.com/docs/app-server#dynamic-tool-calls-experimental).

anthropic's newer managed-agent architecture separates harness, execution and
durable session state, and treats context as a projection of retained history.
that supports the proposed ownership split as an architectural inference; it
does not require adopting its cloud service or persistence model.
[managed-agent architecture](https://www.anthropic.com/engineering/managed-agents).
its earlier recommendation to start with simple composable patterns remains a
useful design principle, not a current protocol reference.
[building effective agents](https://www.anthropic.com/engineering/building-effective-agents).

langgraph's checkpointers/stores are an alternative when graph-state persistence
is the problem. these applications already own canonical claims/actions and
durable records; adding graph persistence would introduce another owner without
solving native submission evidence. this is a fit judgment, not a claim that
langgraph cannot implement durable agents.
[persistence contracts](https://docs.langchain.com/oss/python/langgraph/persistence).

no architecture enforces “state of the art.” evaluate representative tasks and
adversarial failures, with human-defined success criteria and cost/latency/stop
measurements. a small fixed comparison set is sufficient to start; no evaluation
platform is required. correctness gates remain deterministic and cannot be voted
away by a model judge. [evaluation guidance](https://developers.openai.com/api/docs/guides/evaluation-best-practices).

## review disposition and validation

the reviewers agree on ownership and selective extraction. they do not approve
activation. second-pass objections changed the draft: explicit terminal provenance,
turn finality, stale callback fencing, transient-inference preservation, per-call
gate identities, nested admission and a bounded interruption grace are now stated.
the remaining engineering gates have individual [issue records](native-agent-spec.md#10-decisions-tradeoffs-and-implementation-gates).

executed:

- llm-tools public validation/tightening, frozen-plan integrity and async execution:
  35 passed. command: `.venv/bin/python -m pytest -q -p no:cacheprovider
  tests/kernel/test_public_validation_and_tightening.py
  tests/kernel/test_frozen_plan_integrity.py tests/kernel/test_async_execution.py`.
- kernel generation/provider tests against a temporary export of exact pinned
  provider source: 58 passed, sockets disabled. the installed kernel environment
  first failed collection because its stale provider lacked `CodexCatalogSessionRequest`.
  the successful run prepended the temporary pin's `src` to `PYTHONPATH`, retained
  installed other dependencies, and ran `tests/test_generation.py tests/test_provider.py`.
  this is source-level evidence, not clean-install qualification. temporary export
  removed; shared environment untouched.

not run: proposed N001–N020 behaviors, paid native calls, real-store crash tests,
production probes, model-quality comparisons, full cross-repository suites or
deployment. the existing tests prove the baseline, not the unimplemented design.
initial-review documentation validation passed: 17 markdown files, 94 local links/anchors,
20 uniquely defined criteria with one owning slice each, and `git diff --check`.
all workspace changes from this review are documentation only.

### detailed design follow-up

three independent reviewers challenged the provider API, consumer schema/control
and content contracts. corrections adopted: native queued input is not incorporated
input; pending approval never terminalizes its action position; claude raw structured
output survives validation; cleanup is scoped to one handle; public native ids do
not occupy discord delivery ids; jarvis's whole-drain mutex cannot block delivery
or approvals; stopped/resumed requests reject stale final settlement; host resolution
and scheduled-wake events retain separate consumption. hard cutover preserves effect
undo ownership before deleting shell credentials and resolves actual socket symlinks.

new design work ran source/protocol inspection and documentation checks only. no
new runtime tests, paid/live calls, deployment or metadata-worktree edits occurred.
earlier test counts above remain historical baseline proof, not target acceptance.

final design checks: 26 changed markdown files, 133 local links/anchors, 20 unique
acceptance criteria with one slice owner each, and documentation-only scope passed.
git diff --check passed. no preference questions remain; implementation and live
qualification gates remain open, including metadata's exact capability proof.
