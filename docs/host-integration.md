# host integration

compose exact provider configuration, role/output schema and maximum profile into
`NativeDefinition`; select a tightening frozen plan and canonical ordered inputs
for `NativeRequest`. supply current `OwnerPermit`, `OwnerPort`, a `NativeJournal`
or explicit `TransientNative`, `NativeInputPort`, `NativeMessagePort`, tool dispatch
and budget factory ports.
provider account/server lifecycle stays outside the kernel. the stock server loads
the provider-owned restricted model catalogue at startup; per-thread overrides
cannot establish this ceiling. jarvis uses its own contained endpoint; nexus uses
its dedicated host. see [adr 0011](decisions/0011-contained-native-host.md).

## transient native work

a host that claims no native recovery passes `journal=TransientNative()`
([adr 0012](decisions/0012-transient-native-attempts.md)). the kernel keeps
acceptance, duplicate-callback replay and reply-before-send order in per-call
memory; the durable facts below are not kept. the host still checks ownership,
polls input, dispatches tools and records whatever tool/effect rows it needs,
commits public messages and acquires the session. use a fresh `attempt_id` per
call. on return, persist what the product needs from the returned terminal or
`AgentNotSubmitted`; an exception or process loss leaves no kernel evidence (not
even a latched seal; observed usage stays on the lease), so the host settles the
work as failed or reruns it from scratch, accepting that the lost attempt may
have been charged. `recovery_policy` is inert in this mode.

the kernel keeps no effect barrier here. invocation ids and positions are unique
per acceptance, never an effect identity a rerun can recognize. for Write tools,
commit each effect atomically with its durable row, or own its reconciliation;
derive any cross-rerun idempotency from host identity, not from lineage. a rerun
is new model work and may repeat an equivalent write. a dispatch that settles
after stop may return its result; the kernel records and never sends it.

the owner selected this mode for nexus generation on 2026-10-09; until that
cutover lands, the nexus section below describes the deployed durable adapter.

## required durable facts

with a `NativeJournal`:

- arm original provider attempt/request digest and submitted bytes before send;
- bind the exact native turn; retain submission facts separately from terminal;
- freeze accepted callback arguments, input lineage and revisions before entry;
- retain stable read/gate/action identity, entered uncertainty and result receipt;
- commit immutable callback reply before wire send; duplicates replay that receipt;
- commit exact native terminal/usage/raw payload before product interpretation;
- retain local control/fence facts independently; none is a native seal;
- commit completed commentary plus outbox idempotently; record input delivery facts.

current owner authorizes provider/effect entry. stale owner cannot dispatch or
publish. revocation cannot erase an original entered operation's factual receipt.
unknown effects remain blocked for the host's real reconciliation procedure.

## jarvis

`native_runtime.py`/`native_journal.py` adapt the shared supervisor to canonical
requests, native attempts/invocations and the existing owner lock. approval returns
a pending receipt; ingress, approval resolution and outbox delivery run while
reasoning continues. action executor and callbacks share the actual-dispatch lane.
stop targets requests and cancels never-entered approvals. resume requires fresh
consent; entered unknown effects retain their original barriers. process/connection
loss fences the old attempt and cold-starts reasoning from canonical state.

stopped cutover refuses unresolved legacy entered actions and paid reads. old
unentered approvals/queued work re-enter current validation and consent. completed
historical observations stay facts; they are never invented native acceptance.

## nexus

`generation_service` freezes exact `GenerationSpec`/intent. `llm_execution`
retains journal `Prepared -> Uncertain -> Completed` and atomically commits parent
product terminal plus Completed memo. `native_generation.py` uses the shared
supervisor with existing `ToolAuthority`/recorder/domain handlers and persistent
host socket. raw API generation retains its genuine provider lane.

cold recovery first reads the original frozen admission. only own exact native
seal or authoritative original-attempt non-submission admits local settlement.
no provider/catalog call is needed; a parent outcome alone never authorizes it.
publication rechecks current source/credit/access/claim fences separately.

migration 0254 backfills generation principals from original shell credentials,
retains historical positions/continuations without invented seals, then deletes
the credential table. unresolved shell work or missing historical principal
blocks cutover. historical effect listing/undo uses the persisted principal.
metadata's separately owned 0255 follows 0254 in one canonical chain.

## qualification

install immutable libraries from frozen consumer locks. distinguish source-overlay,
controlled-peer, real-store, actual selected native model/research and final artifact
proof. exact pins, receipts, migration checks and outstanding gates belong in
[evidence](native-agent-evidence.md) and [metadata handoff](integrations/nexus-metadata.md).
