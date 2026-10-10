# adr 0012: run disposable native attempts without a host journal

- status: accepted; implemented with controlled proof only
  (../native-agent-evidence.md, N021). no consumer has adopted it yet.
- date: 2026-10-09
- scope: `run_native` journal selection; amends adr 0010 for disposable native
  work and extends adr 0009's explicit transient choice to native attempts

## problem

the nexus owner dropped durable crash replay for generation (decision of
2026-10-09): a worker that dies mid-generation fails the run as interrupted, and
background jobs rerun from scratch. `run_native` still required a `NativeJournal`,
so that host had to keep recover/arm/bind/record/fence rows whose only purpose is
replay identity, or imitate a journal in its own memory and thereby copy the
kernel's acceptance, duplicate-callback and reply-before-send order. the first
keeps cost without a claim; the second duplicates kernel-owned ordering per host.

## decision

`run_native(journal=...)` accepts `NativeJournal | TransientNative`.
`TransientNative` is an empty frozen marker, like `TransientModelDecisions`: the
host selects it explicitly; there is no default. on entry the kernel replaces it
with a private per-call memory journal. the supervision loop is unchanged and has
no mode branch, so durable and transient attempts share one proven control path.

retained in process:

- exact unsupported requests and plans fail before arm/send; owner checks still
  gate entry, dispatch, steering and reply.
- each callback is accepted before dispatch with a fresh random uuid4 invocation
  id and a serial ordinal from 1; its immutable reply is recorded before the wire
  reply. one dispatch lane, arrival order and finite queue bounds are unchanged.
- a repeated native call id reopens its original acceptance and reply: no second
  dispatch. changed bytes or revisions fail as `NativeDefect`.
- stop revokes the handle, cancels the active callback before requesting interrupt
  and ends with the stop terminal. a callback that still settles after stop has its
  reply recorded and never sent; this holds with a journal too.
- on return, the original native terminal, seal and usage come back unchanged;
  positive non-submission is returned; unresolved submission raises
  `NativeUncertain`.

dropped:

- recovery. nothing is read before preparation; every call is fresh provider work
  and never produces `NativeRecovery`.
- durability. arm, binding, delivery, control, outcome and fence facts live only in
  memory and are discarded on return or process loss. an exception carries its
  message only: neither submission evidence nor a native seal and raw output the
  reader had already latched, which a journal records before re-raising. usage
  observed before the exception still accrues to the session lease.
- cross-process fencing. a dead process's callbacks lose authority only through
  connection loss and the host's own owner check.

the host still owns owner/claim checks, input polling, dispatch and any durable
tool/effect record, budgets, public-message commit, session acquisition and its
policy after loss. `attempt_id` must be fresh per call: provider attempt and
input delivery identities derive from it. `NativeRequest` is unchanged.

## uncertainty and effects

the kernel never redispatches. with a journal, `NativeUncertain` keeps the armed
unresolved attempt and grants no redispatch. under `TransientNative` it keeps
nothing, so failing or rerunning from scratch is the host's explicit policy, which
accepts possible duplicate paid work. `recovery_policy` is inert here: the kernel
never interprets it, and the request fingerprint it enters is retained nowhere.

the kernel holds no effect barrier across process loss in this mode. invocation
id and `NativeDispatchLineage.position` are unique per acceptance: positions never
collide across calls, but they name one callback, never an effect that a rerun
could recognize. a host granting Write tools must commit each effect atomically
with its own durable record, so no entered-but-unknown effect survives a crash,
or own that effect's reconciliation. idempotency across reruns, where wanted, must
come from host identity that outlives the attempt. a rerun is fresh model work and
may repeat an equivalent write. adr 0010's action barrier (unknown outcomes need
reconciliation) thus moves to the host, the only party here with a durable store;
llm-tools still refuses Write execution without a durable recorder and stable
effect id.

## alternatives

- public in-memory journal class: exposes seven port methods no host calls and can
  be reused across attempts, leaking acceptance into a later call.
- mode flag through the loop: branches every journal call site; two paths to prove.
- `journal=None`: transient by omission; adr 0009 forbids a default transient path.
- third `recovery_policy` value: changes request fingerprints without changing any
  kernel behavior.
- host-written memory journal: each host re-derives duplicate and reply ordering.
- read-only transient plans (`require_read_only_plan`, as isolated one-shot
  roles): would exclude the first consumer, whose chat plan grants additive
  writes, while the kernel still could not see whether a host commit is atomic.
- seal attached to the propagated exception: changes "port exceptions propagate
  unchanged" for a value the transient host discards, since it fails or reruns
  after any exception.

## costs

a crash loses in-flight inference and any tool result the host did not record
itself; after a crash or exception the host cannot distinguish never-sent from
charged work, nor recover a latched answer. `tests/test_native_transient.py` is
retained conformance (N021, delivery slice n6), not a deleted feature probe: it is
the suite's only `run_native` coverage. it uses a controlled app-server peer and
claims nothing about model behavior.
