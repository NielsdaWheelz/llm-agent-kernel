# historical uncertainty blocks the nexus production release

status: OPEN production release gate; independent of nexus artifact readiness.
review: 2026-10-02, read-only source/document inspection. fresh production census,
disposition and release are NOT_RUN. no runtime changes or production writes.

## evidence and kernel disposition

the metadata [cutover plan, section 9](../../../nexus-web-metadata/docs/metadata-enrichment-plan.md#9-hard-cutover-and-verification)
requires uncertainty disposition before release. the historical receipts report:

| receipt | observed blocker |
| --- | --- |
| [2026-09-27 media census](../../../nexus-web-metadata/docs/tickets/model-cutover-dead-media-generations.md), source `7dc68929b4d5ddfd77eb1a50228d477fa0148b5d`, revision `0241` | 41 outcome-null media generations with dispatched, unsealed turns; 41 dead metadata jobs retaining admissions |
| [2026-09-27 chat census](../../../nexus-web-metadata/docs/tickets/model-history-cutover-blocked-by-uncertain-work.md), same source/revision | running chat `ac2b162e-0bb1-4b66-90f5-a9aaec0b3f22`, dead job; two dispatched, unsealed chat generations, including one under a terminal run |
| 2026-10-01 lewis inspection, retired smoke ticket at nexus revision `c2e0c154` | eight dead jobs: five uncertain dispatches and three catalog-refresh failures; no recorded publication/web call |

the resolved research ticket was removed after finite local qualification. its
original body remains in nexus git at
`c2e0c1546a4cb839da33bc2eb496afb0443cf796:docs/tickets/metadata-live-research-smoke-unverified.md`;
that local immutable object was verified, without assuming it is published remotely.
these are historical counts, not today's census; overlap is unknown. missing tool
rows, dead jobs, a parent outcome and stopped processes prove no native terminal
or non-submission. new provider seals cannot certify old unsealed attempts.
`generation_has_local_recovery` requires original native attempt identity and
original terminal/non-submission evidence. never manufacture these facts, clear
`Uncertain`, requeue an unknown dispatch, or stamp past a migration guard.

`0246` rejects these owners before deleting old chat/generation history. the
approved [model reset](../../../nexus-web-metadata/docs/latest-models-cutover-plan.md#hard-cut-and-data)
permits audited abandonment of old paid work while preserving uncertainty,
domain effects and undo. it supplies no executable abandonment transition.
the current release controller also supplies none. this is the missing seam.

## finite owner procedure and required proofs

1. **census, read-only.** the authorized nexus operator runs the installed
   candidate's `python -m nexus.model_cutover_preflight --snapshot` against the
   actual target; preserve its exact revision, identities and row hashes. its
   transaction is repeatable-read/read-only. supplement it with all retained
   job admissions and coordination steps, including succeeded jobs and inactive
   `Uncertain` steps with terminal parents; frozen request/intent, leases,
   publication/memo references, manual-author pins, accepted effects and undo
   records, including those under settled parents. reconcile every owner/job/
   generation/turn identity. malformed, missing or unowned records stop release.
2. **classify, without replay.** settle only from original authoritative evidence
   through the owning application's existing contract. catalog failures are
   separate: prove they preceded admission before considering any later retry.
   old unsealed submissions remain unknown. if settlement is impossible, the
   nexus reset/ledger and domain owners must define a reviewed, exact-id
   archival abandonment allowlist. preserve the original null terminal/outcome
   and uncertainty; an archival disposition is not provider completion. resolve
   effects through their actual owners or retain their reconciliation barriers;
   unknown ownership or effects without a safe owner disposition stop release.
3. **quiesce and preserve.** before any disposition write, freeze admission,
   stop/drain writers and owned native processes, revoke old grants and fence
   stale leases/commands. use the existing release/backup owners. preserve a
   verified consistent pre-disposition backup with source/database/revision,
   hash/byte-count and restore manifest; retain exact old jobs, ledgers,
   continuations, history, effects, authorship and undo. preserve required
   continuation-key references through existing secret custody, never logs.
   record process/grant receipts separately: remote computation may still bill.
4. **supply the missing executable seam.** the nexus reset/ledger owner must
   implement the narrow allowlisted transition and its explicit `0246` guard
   integration under the approved reset. compare original row identities/hashes;
   reject drift and every unreviewed owner. retire old replay authority without
   creating replacement attempts or erasing domain facts. record disposition,
   reviewer and original uncertainty beside the verified archive. integrate
   backup-before-disposition and the reviewed post-disposition census into the
   existing release sequence; today's controller has no such step. queue reset,
   deleted admissions or invented `Completed`/cancelled outcomes are not it.
5. **prove on a restored copy.** actually restore that backup, then run the
   exact disposition and canonical migration chain from the actual starting
   revision through the selected head. verify archived originals, domain facts,
   effect identity, authorship and undo through real owner operations; undo once
   and repeat safely. prove old jobs, memos, tokens, callbacks and browser
   commands cannot redispatch or republish after reopening admission. include an
   unallowlisted blocker that aborts without partial changes. make zero provider
   calls. archive traversal and row counts alone are insufficient; the existing
   `0252` → `0254` → `0255` fixture does not prove production `0241` → `0246`.
6. **release, separately authorized.** the release owner keeps writers stopped,
   repeats the reviewed census and effect/grant checks, executes only the proven
   disposition, verifies the preserved backup and runs the exact candidate to
   its canonical head with aligned api/worker/host/web artifacts. drift requires
   renewed review. post-`0246` accepted history forbids a second reset. rollback
   restores the verified backup under another drain; an old image is insufficient.

the existing mutating backend invocation is:

```sh
PYTHONPATH=python python3 deploy/hetzner/release.py <source-sha> \
  --model-cutover-snapshot <reviewed-json>
```

this is **not yet a runnable disposition procedure**. `deploy.sh:25,105` accepts
only the sha and does not forward this required option. the release owner must
close that integration gap within the existing aligned release workflow. direct
backend invocation alone does not qualify the full release.

## owners and closure

kernel integration owns this evidence verdict and handoff; it owns no application
archive/reset transaction. the model plan assigns nexus's consumer/backend reset
designer the ledger/history/migration work; the release owner owns quiescence,
backup and deployment. metadata/media owns retained metadata jobs, publication
and later retries. no current legacy reset/release owner contact or session is
identified in the inspected documents; obtain that handoff rather than guessing.

release may proceed only with a fresh target census, executed owner disposition,
verified pre-disposition restore, exact-chain/effect/undo/stale-replay proofs and
current quiescence/grant receipts. close this issue after exact release receipts.
until those prerequisites exist: **RELEASE BLOCKED**. qualified new runtime
artifacts and genuine new research receipts remain valid independent evidence.

source checks: nexus source `a3540e3dcbb79a0235ef21fba67fb5c6966bcfbd`;
`python/nexus/model_cutover_preflight.py:29–124`,
`services/llm_execution.py:824–856`, `services/durable_step_journal.py:45–103`,
`migrations/alembic/versions/0246_latest_model_history_cutover.py:73–97,121–171,264–279,385–401`,
`deploy/hetzner/release.py:381–442,610–692`, `deploy/hetzner/deploy.sh:25,105`,
`python/nexus/release_backup.py:215–251`. `0246` copies authorship then deletes
ledger positions; `python/nexus/services/generation_effects.py:20–61` still needs
live position/parent rows. copied authorship alone does not prove retained undo.
