# repository instructions

this repository contains `llm-agent-kernel`, imported as `llm_agent_kernel`.

- python 3.12+. `SPEC.md` and `docs/native-agent-spec.md` are normative; adr 0010
  supersedes the deleted conversational loop, session cache and capacity admission.
- provider-runtime owns SDK/native transport, exact request/capability validation,
  authoritative send/finality evidence and per-handle control. do not duplicate it.
- llm-tools owns rendering, declarations/plans, pure validation, executor, budget
  algebra, durable recorder/positions/replay and results. use its public contracts.
- kernel owns portable native ordering and genuine isolated/raw-generation roles.
  no application store, migration, workflow/queue, credential, memory, consent,
  effect ledger, publication, delivery or reconciliation procedure belongs here.
- exact unsupported requests fail before arm/send; no fallback or compatibility.
- effective authority is provider containment intersected with the host frozen
  plan; prove plan/catalog consistency and tightening before rendering or I/O.
- native shell/files/web/network/MCP/unsolicited permissions and inherited
  authority are disabled. cwd is private, empty and read-only.
- accept immutable invocation before effect; commit result and immutable reply
  before wire send. one dispatch lane, independent live transport/control.
- preserve original native seal/raw/usage before product validation or cleanup.
  exception names, timeout, local stop and parent outcome never prove submission.
- owner permits authorize entry; recorded action/result facts survive revocation.
  restart reasoning only after fencing old callbacks; retain effect barriers.
- no task-wide quota or arbitrary main cutoff. finite operation/buffer bounds
  remain. share llm-tools arithmetic; never double-charge settlement or replay.
- fingerprints cover full containment, base instruction and frozen binding/plan
  revisions. implementation revisions cover transitive execution behavior.
- prefer the smallest complete reusable contract proven by actual consumers.
  new persistent requirements or ownership changes need an ADR. no future framework.
- keep acceptance ids unique; verify documentation links/pins/terminology after
  material changes. record unresolved issues in `docs/issues/<short-name>.md`.
- use concise explicit control flow and meaningful proportionate verification.
  delete new temporary feature tests only after required final proof, as accepted
  in `docs/native-agent-plan.md`; retain applicable existing conformance.
