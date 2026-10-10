# native agent implementation plan

status: accepted scope implemented and qualified; exact artifacts and proof are in
[implementation evidence](native-agent-evidence.md). the [contract](native-agent-spec.md) owns behavior, types and schemas;
this document owns delivery, file boundaries and proof. all n1–n5 slices are
implemented on isolated feature branches; n6 is implemented with controlled proof
and awaits its first consumer. the [metadata handoff](integrations/nexus-metadata.md) records
the separately running consumer and exact capability requirement.

## working rules

- implement one slice at a time at each shared boundary. n2 and n3 may proceed
  independently after n1; n4 and n5 consume n3. no parallel edits to one contract.
- accepted kernel behavior governs dependency and consumer changes. reuse public
  declarations, execution, evidence and persistence primitives before adding code.
- each slice has one implementation owner and a separate adversarial reviewer.
  the content designer owns the affected prompt/result/status examples and their
  quality criteria in the contract; this is a review role, not another service.
- no flags, alternate executors, compatibility parsers or automatic route/model
  fallbacks. retain a component only for an identified current role.
- use the actual consumer store and installed provider for claims about them.
  a deterministic fake proves its narrow boundary only. no production mutation is
  needed for the qualification fixtures.

## n1 — truthful provider and terminal evidence

owns N001–N005. provider-runtime owns attempt identity, request validation,
non-submission proof, native finality and control results. kernel owns sequencing
and durable evidence before dependent work. this slice does not implement callbacks.

files: provider new `agent_runtime/turn.py`, existing
`agent_runtime/{types,events,runtime,codex_app_server,codex_sdk,claude_sdk,_structured_output}.py`
and public exports; kernel `provider.py`, `decisions.py`, `generation.py`,
their owned exports and specification sections 16–17. use the pinned provider
source as the starting point, not the stale installed/sibling source.

1. write boundary cases for rejected preflight, interrupted send, dropped response,
   native failure, terminal/cleanup race and invalid terminal identity/tail.
2. change provider evidence types; advance every affected caller together. preserve
   original error and submission facts independently of local cleanup status.
   prepare durable requests before journal arm. preserve native structured payloads
   separately from their later decoded projection, including existing claude results.
3. separate durable terminal commit from product resolution in the generation
   lifecycle. product failure can repeat local work, never the provider request.
4. migrate historical evidence conservatively. missing provenance remains unknown;
   old armed rows are not negative-submission proofs.
5. qualify installed immutable packages and publish the provider/kernel pins.

red must expose the wrong evidence/dispatch behavior, not a missing credential or
test import. green requires original terminal identity/usage to survive each
secondary failure and no post-fence exception to manufacture non-submission.
reviewer attacks send/cancel ordering, evidence mutation and cleanup precedence.
designer checks that diagnostics explain which stage failed without payload leaks.

## n2 — nexus lifecycle repair

owns N006–N008. depends on n1. repair the current route independently of n3–n5;
this is staged delivery of a repair, not a retained fallback in the final system.

files: nexus `apps/codex_agent/host.py`; services
`codex_generation_{contract,client,operations}.py`, `generation_backend.py`,
`llm_execution.py`; affected child/terminal storage and one migration. n2 changes
evidence and settlement only. metadata domain files belong to the metadata owner.

1. reproduce child-terminal rollback on forced decode/encode failure, and
   terminal replacement by late cancel/cleanup using the real store.
2. commit native terminal first; persist product resolution separately. reopen a
   committed terminal after process death with provider-call count unchanged.
3. map original provider rejection/failure into the exact shared evidence contract.
   preserve uncertain steps and existing effect recovery obligations.
4. run the exact metadata success journey and separate controlled failures from
   [the handoff](integrations/nexus-metadata.md). current-route proof does not
   qualify the callback target.

reviewer attacks generation ownership and transaction rollback. designer reviews
metadata precision and evidence through the metadata owner's existing schema.
exit report names the tested adapter branch, immutable pins and actual model/effort.

## n3 — one reusable native callback supervisor

owns N009–N015. depends on n1; can run alongside n2. this slice owns the public
native callback API, the optional cumulative-limit algebra and portable ordering.

files: provider `agent_runtime/{types,events,runtime,codex_app_server,codex_sdk}.py`
callback/control members and `tool_adapter.py`; tools
`profiles.py`, `execution.py`, new `budgets.py`, `testing.py`, public exports;
kernel new `native.py` and `native_contract.py`, `tools.py`, `definitions.py`,
`coordination.py`, `sessions.py`, `context.py`, public exports. reuse current
modules for their existing responsibilities; do not add an event framework.

1. qualify declarations + strict output + disabled native tools on the installed
   app-server. an unsupported combination blocks this slice; do not broaden authority.
2. implement provider turn/callback/control contracts and small bounded queues.
   the transport reader must remain live while a callback or nested gate waits.
   per-handle close/timeout must not invalidate another healthy session on the adapter.
3. extend existing tools limits with explicit absence of cumulative quotas.
   centralize reservation arithmetic; retain per-operation limits and recorders.
4. implement the journal/dispatch/result/reply order and stale-owner checks. one
   active tool dispatch; native overlap waits in arrival order within finite bounds.
5. implement input/progress observations, stop and fencing, plus fresh-session
   recovery. no cumulative transcript ceiling may masquerade as a usage limit.
6. replace capacity reservation with the selected owner-only admission contract
   for native main and its isolated gate. no fabricated reservation numbers.

reviewer attacks duplicate/changed callbacks, send-result loss, control starvation,
false terminal proof and hidden usage caps. designer reviews tool descriptions,
pending/rejection results, base instruction and the progress/final distinction.

## n4 — jarvis native main and durable request state

owns N016–N019. depends on n3. no memory/delegation/work-table overhaul is included.

files: jarvis `db.py`, one new alembic migration, new `native_journal.py` and
`native_runtime.py`, `kernel.py`, `definitions.py`, `messages.py`, `checkpoints.py`,
`read_positions.py`, `read_dispatch.py`, `write_dispatch.py`, `write_gate.py`,
`actions.py`, `approval_runtime.py`, `approval.py`, `terminal.py`, `admission.py`,
`ownership.py`, `state.py`, `service.py`, `settings.py`, `rebuild.py`, isolated-role
permit callsites and affected CLI/delivery wiring. delete `thread_runtime.py`.
kernel deletion of the replaced `run_thread`
path belongs exclusively to this slice after its last consumer moves.

1. implement the request/attempt/invocation/input-delivery schema in the contract.
   prove real-store crash recovery before switching the main entry point.
2. bind writes to the exact originating canonical request. use invocation identity
   for reads/gates and existing action identity for external effects.
3. make pending approval return a durable receipt while independent work continues.
   serialize stop, approval and dispatch; deliver later action resolution as new input.
   remove service.py's whole-drain mutex/outbox starvation. ingress, consent and
   delivery stay live; callbacks and approved actions share the one actual-dispatch
   lane. prove progress delivery and approval resolution before native terminal.
4. replace main prompt/final handling: progress is observational; per-request
   completion is explicit; unanswered earlier requests survive a new topic's answer.
   preserve host-event consumption and existing scheduled-wake action settlement.
   test terminal commit -> stop/resume -> stale product commit under actual locks.
5. use the existing owner lock and separately contained host endpoint under
   [adr 0011](decisions/0011-contained-native-host.md). process/connection loss fences
   the old attempt and recovers canonical inputs/results into a fresh native thread.
6. cut over the main entry point. delete its structured-step loop, prompt, capacity
   reservation arithmetic and duplicate budget implementation. retain isolated
   inference only for its actual gate/context/memory roles.

reviewer attacks stop/approval races, request attribution, semantically repeated
writes and owner loss during receipt persistence. designer checks real rendered
messages, including the entire discord message's limit, waiting and truthful stop.

## n5 — nexus callbacks and deletion of the shell route

owns N020. depends on n3 and the n2 evidence repair. keep metadata's generation
service/journal contract unchanged; no metadata-local agent adapter.

files: nexus `generation_backend.py`, `generation_service.py`, `generation_spec.py`,
`tool_authority.py`, `tool_runtime/{plans,snapshots}.py`, `llm_execution.py`,
affected models/migration, worker composition, codex host lifecycle/container wiring.
delete the replaced `codex_generation_client.py` and shell generation protocol,
`apps/codex_agent/exec_server.py`, `skills/nexus-api`, shell prompt/tool bridge and obsolete credentials
only after moving any still-required ownership/effect behavior to its proper owner.

1. execute the same native supervisor in the generation worker. callback handlers
   use existing tool authority/recorder transactions and domain tools locally.
2. attach through a private app-server socket provided by the existing codex host
   service. the host retains native credentials and process supervision. this is
   an explicit n5 topology change; n2 retains per-generation server lifecycle.
   verify the socket's actual resolved location in the shared volume, uid/gid
   permissions, host-visible private cwd and account-refresh ownership. test two
   simultaneous jobs: cancelling one cannot stop the other or cross-route replies.
3. freeze exact native plans; qualify research results, source receipts, strict
   output and actual model/effort together. preserve metadata's uncertain-step barrier.
4. migrate effect ownership out of shell credentials before deleting them. existing
   effect listing/undo continues to resolve historical effects through that owner.
5. hard-cut the replaced route, flags, credential glue, unused prompt and callback
   bridge. remove imports/dependencies only after all remaining users are identified.

reviewer attacks private socket permissions, shared-server session isolation,
historical undo and uncertainty during job cancellation. designer checks metadata
precision and citation fidelity; callback migration adds no domain schema fields.

## n6 — transient native attempts

owns N021 ([adr 0012](decisions/0012-transient-native-attempts.md)). depends on n3.
files: kernel `native_contract.py` (`TransientNative`), `native.py` (per-call
journal substitution; no mode branch in the loop), `_api.py` and the normative
docs. no provider-runtime, llm-tools or consumer change.

proof: controlled app-server peer through installed provider-runtime callback
transport, no journal: acceptance before dispatch, reply after result, repeated
call id without second dispatch, stop cancelling the entered dispatch before
interrupt with no reply (also when the dispatch settles after stop), fresh attempt
recovers nothing. `tests/test_native_transient.py` is RETAINED conformance, an
explicit exception to the deletion rule below: it is the only `run_native`
coverage. reviewer attacks effect identity across reruns and uncertainty wording.
nexus adoption is a separate consumer slice under the owner's generation rewrite.

## red, green, refactor, delete

create one temporary acceptance folder per owning repo. provider/tools/kernel use
their existing test runner; jarvis/nexus may use small stdlib async integration
drivers rather than rebuilding their retired test systems. each case names its
N-id, fixture, observed boundary and exact expected receipt/state.

| layer | fixture and assertion |
| --- | --- |
| provider transport | real loopback protocol peer drops/reorders selected messages; prove local send classification and typed event ordering, not remote model behavior |
| tools/kernel composition | actual public packages and executor, recorder-backed fault points; check validation -> acceptance -> effect -> result -> reply order and duplicate suppression |
| consumer persistence | disposable real postgres, actual adapters, killed/restarted owner process at each durable boundary; query receipts/effects and count real dispatches |
| installed native | actual configured app-server/account/model, real declared tools and strict output; adversarial native-tool requests, overlapping callbacks, silent reasoning, steer/stop and nested gate |
| product/content | small representative tasks: new topic during research, pending approval with independent work, missing source, original/edition date ambiguity, unknown citation, oversized composed answer |

required crash points: after attempt arm; after invocation acceptance; after effect
dispatch; after effect receipt but before callback reply; after terminal commit but
before product commit. test both orders of stop versus approval/dispatch. check a
new model call id cannot evade an unresolved-action barrier. use counters/receipts,
not fluent prose, as the execution oracle.

test malformed/undeclared input separately from transport defects. verify genuine
tool failures remain useful typed results while identity/containment failures stop
further dispatch. include a quota-free run beyond the old cumulative limit with
bounded individual operations, and repeated settlement/replay without double charge.

the temporary test command and fixture must be implemented with the first red and
recorded then; do not publish an invented currently runnable command. existing
required checks remain: kernel/tools/provider formatting, lint, types and applicable
conformance; jarvis `scripts/verify`; nexus `./scripts/test` is static only and
cannot replace the consumer/live cases above. install from frozen lockfiles in
isolated environments, never from an accidental sibling import.

after green, refactor within the same slice; repeat only affected acceptance and
required checks. rerun affected dependent consumer cases on the final integrated
tree once. record proof, then delete all newly created feature acceptance tests
(except n6's retained N021 conformance), fault proxies, fixtures and test-only
dependencies as requested. remove superseded existing cases only when their runtime
path is deleted. unrelated existing tests remain. no test deletion counts as a
passing test.

after deletion, run the final static/type/build checks and compare runtime artifact
bytes and resolved runtime dependencies with the qualified artifact. if they changed,
rerun affected acceptance against the final artifact using an external temporary
harness, then remove that harness. record both the tested and final source commits;
pre-deletion proof alone is not final-artifact proof.

retain a small evidence note: N-ids, exact commits/locks/native build, actual route/
model/effort, command, fixture description, timestamps, exit result and non-sensitive
receipt/count assertions. retain reproduction steps, not a permanent harness or raw
private transcript. distinguish `PASS`, `FAIL`, `BLOCKED`, `NOT_RUN` and historical
pre-cutover evidence. test deletion removes ongoing regression protection; later
changes need fresh focused verification rather than claiming this proof is current.

## cutover and rollback

each replaced native-agent lane has one active implementation. pause its admissions,
finish or fence active attempts,
back up local state, run its migration, install exact qualified pins, start the new
route and verify the representative task. no mixed-schema writers, dual writes or
runtime switch back to the old path. pinned libraries may be delivered before host
activation, but the host cutover deletes its replaced code in that same release.

activation is BLOCKED while any dispatched legacy action still needs a retired
decoder/handler for settlement or reconciliation. fencing alone is insufficient.
preserve original historical arguments/digests/revisions. never-entered old approvals
become newly validated ActionRequest successor records with fresh consent; ambiguous
origin blocks migration. old queued work re-enters its gate before any successor
execution. never backfill new acceptance evidence into an old immutable record.

rollback first fences every post-cutover attempt/callback owner, then replaces the
application artifact while preserving the effect/journal records accumulated since
cutover. never restore a pre-effect database snapshot to
make old code appear compatible. if the old artifact cannot read the migrated state,
stop admission and repair forward or ship an explicit offline reverse migration
that preserves new receipts and unresolved actions. never replay a paid step or
external action merely to restore a former schema.

finish by updating the owning specs/ADRs, deleting resolved issue records and
removing task-owned temporary resources. retain open issues only for evidence not
yet established. implementation and paid qualification calls were subsequently authorized.
no deployment or edit to the metadata worktree is included.
