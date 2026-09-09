# ADR 0009: retain paid decisions independently of native sessions

- Status: Accepted
- Date: 2026-09-09
- Scope: shared-kernel hard cutover; amends ADRs 0002, 0005, and 0006

A crash between paid model completion and host action admission loses accepted
reasoning. A crash after request dispatch but before its first event can cause a
second charge. A native session reference and an action ledger prove different
facts; neither is the missing model-decision record.

Require a host-owned `ModelDecisionJournal` for thread runs. Require every
isolated caller to select `DurableIsolatedDecisions` with a stable operation ID,
or explicitly declare disposable inference using `TransientModelDecisions`.
There is no default transient path. Jarvis's recoverable roles use the durable
choice; process-local fakes and deliberately transient callers claim no replay.

Before paid provider invocation, commit a request containing stable scope and
ordinal, authority fingerprints, original input/checkpoint/as-of lineage,
logical counters, exact submitted text, and a bounded canonical bootstrap
snapshot. Before dependent effects, commit the original complete normalized
provider terminal. Scope plus ordinal identifies the decision; request content
has a separate fingerprint. Fresh claim/run UUIDs cannot create new work over
an unresolved operation.

Replay the latest completed decision without opening a provider or rewriting
its obsolete session reference. Subsequent paid work uses a fresh native session
and the stored canonical context, accepted historical model evidence, and new
tool observations. The host stores and restores any typed role evidence needed
to validate a replayed result atomically beside the terminal. Prompt text is
never parsed to recover host authority.

An armed record without an accepted terminal parks unconsumed work. Consult it
before retry limits or poison settlement. Every exception after provider entry
retains uncertainty, including `TurnNotStarted`: the pinned provider can raise
that after awaiting a backend without receiving its first event. Release an
armed record only when the kernel itself has not invoked the provider. Existing
session-acquisition fallback before arming remains available.

Stable accepted decision IDs also supply Read positions. The host's existing
llm-tools recorder durably retains BilledOnce results and uncertainty. Initial
Reads derive a disjoint position from the same stable isolated operation. Write
positions remain existing action IDs, admitted only after current host policy
and approval; this journal grants no permission and performs no reconciliation.

Trade-offs: another bounded application-owned store, canonical text storage,
and explicit operator recovery for ambiguous paid calls. We reject automatic
redispatch for availability, request hashes that include fresh attempt IDs,
reconstructing model results from actions, native-history replay as canonical
truth, and a second workflow server. These would respectively duplicate paid
work, evade uncertainty, conflate distinct facts, trust disposable state, or add
an owner the two consumers do not require.
