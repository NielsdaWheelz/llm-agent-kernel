# historical uncertainty blocks the nexus production release

status: OPEN production release gate; independent of nexus artifact readiness.
initial review: 2026-10-02, read-only source/document inspection. production
disposition and release remain NOT_RUN; preliminary owner census/restore and
application preparation are now qualified separately below. no production writes.

ownership update, 2026-10-03: metadata root, `t-81545cb9ac775ed8` on macbook,
has accepted nexus application reset/release preparation in
`feature/metadata-enrichment`. at current composed `bcb86e020`, the executable
archival transition, complete controlled owner-populated0241→0257 proof and eight
whole-transaction refusals are GREEN. eleven forwarding and ten controller cases
are GREEN with controlled remote leaves. final255-pass/256-refusal rollback proof
and metadata's owned cleanup/post-deletion static closure are GREEN. the owner's
[final verification](https://github.com/NielsdaWheelz/nexus-web/blob/16514144780bbddef4691ddb5c5e6114e932c21c/docs/metadata-enrichment-verification.md)
is published in draft pr482 at docs-only165, with qualified bcb86e runtime unchanged.
metadata pr merge remains separately owned and unexecuted. production disposition, drain and
deployment require separate final authorization; current quiescence and a fresh
verified R2 backup/restore are still required.

the fresh read-only owner census reports 52 uncertain media generations, two chat
generations and 56 retained dead metadata jobs. these are distinct sets, not a sum.
the preliminary exported-snapshot production archive/actual restore preserves
exact rows; it is not a drained release backup. source7dc689/revision0241 archive
sha256 `74eb092890dcfa6c809bea4e4ff187eb0a34381eb0681345d377aa9b594f149b`,
1,459,971,923 bytes. private owner receipts under
`/private/tmp/nexus-metadata-release-uy48cjy2/`:
`preliminary-live-0241-dump.receipt.json`, sha256
`3b74a7df0a6af2d83ed1be9947a60e0fca632740a289dbc512af133841e672ec`;
`preliminary-live-0241-restored.receipt.json`, sha256
`c45cd9319630f2dfa930dcf5558eefe6d7fa3c2c3d61b07730a321da06488d0e`.

the separate bcb86e qualification uses a controlled owner-populated0241 archive,
sha256 `4f139a1ac6398b809566ef800da11cc088dafc0df994cd3546dff1fa088426d2`,
1,464,333,814 bytes. it makes no production/R2 restore claim. owner proof:
`/private/tmp/nexus-metadata-release-uy48cjy2/0257-metadata-restored-cutover.receipt.json`,
sha256 `b0b50e9f192fe785b4290f030204d01b7d6134e8a4b6627b67cc3c7c1aa07f48`.
controlled fixture adds one owner; its 55 null parents/70 retired jobs differ from
original production54/69. original effects, undo, remaining atlas/resource rows and
excluded succeeded job survive; no native seal or provider completion is invented.
atlas timestamp loss is existing main's recorded migration loss. current owner
verification is `bcb86e020:docs/metadata-enrichment-verification.md`. immutable
private copies of the owner documents below, with full commits and hashes, are in
`/private/tmp/native-metadata-cutover-gu65429d/metadata-document-snapshots/manifest.json`.
these are retained local git objects, not remotely published links or new proof.

## evidence and kernel disposition

the metadata cutover plan, section 9 (`docs/metadata-enrichment-plan.md` at bcb86e),
requires uncertainty disposition before release. the historical receipts report:

| receipt | observed blocker |
| --- | --- |
| 2026-09-27 media census, `docs/tickets/model-cutover-dead-media-generations.md`; source `7dc68929b4d5ddfd77eb1a50228d477fa0148b5d`, revision `0241` | 41 outcome-null media generations with dispatched, unsealed turns; 41 dead metadata jobs retaining admissions |
| 2026-09-27 chat census, `docs/tickets/model-history-cutover-blocked-by-uncertain-work.md`; same source/revision | running chat `ac2b162e-0bb1-4b66-90f5-a9aaec0b3f22`, dead job; two dispatched, unsealed chat generations, including one under a terminal run |
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
approved model reset (`docs/latest-models-cutover-plan.md`, “hard cut and data”, at bcb86e)
permits audited abandonment of old paid work while preserving uncertainty,
domain effects and undo. the originally reviewed source lacked an executable
transition. metadata root now implements that seam in `model_cutover_archive`
and the existing aligned release controller; release authority remains gated.

## finite owner procedure and required proofs

preparation uses read-only target evidence and isolated restored copies. production
quiescence and disposition require the separate authorization in step 6.

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
4. **select and validate the qualified owner seam.** the nexus reset/ledger owner's
   `model_cutover_archive` supplies the narrow allowlisted transition and explicit
   `0246` guard integration under the approved reset. compare original row identities/hashes;
   reject drift and every unreviewed owner. retire old replay authority without
   creating replacement attempts or erasing domain facts. record disposition,
   reviewer and original uncertainty beside the verified archive. integrate
   backup-before-disposition and the reviewed post-disposition census into the
   existing aligned release sequence. queue reset,
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

the current application owner forwards that option through
`deploy/hetzner/deploy.sh <source-sha> --model-cutover-snapshot <reviewed-json>`.
the release controller invokes `python -m nexus.model_cutover_archive` with the
validated reviewed JSON and installed runtime identity, and the archive runs in
the actual migration transaction. preparation tests prove controlled forwarding
and refusal behavior; they are not production execution or R2 qualification.

## owners and closure

kernel integration owns this evidence verdict and handoff; it owns no application
archive/reset transaction. metadata root now owns nexus's application reset/ledger
and release preparation, including the snapshot forwarding repair, finite
archival transition and census/backup/restore/effect/undo/stale-replay proofs.
metadata/media retains ownership of metadata jobs, publication and later retries.
the kernel/native team has no active overlapping application work; its adapter,
provider/kernel/tools artifacts and immutable pins remain unchanged. the retired
original qualification host remains retired. archival preparation needs no fresh model calls and
must preserve the original stopped uncertain-job databases and evidence.

release may proceed only with a fresh target census, executed owner disposition,
verified pre-disposition restore, exact-chain/effect/undo/stale-replay proofs and
current quiescence/grant receipts. close this issue after exact release receipts.
until those release prerequisites exist: **RELEASE BLOCKED**. qualified new runtime
artifacts and genuine new research receipts remain valid independent evidence.

historical source checks: nexus source `a3540e3dcbb79a0235ef21fba67fb5c6966bcfbd`;
`python/nexus/model_cutover_preflight.py:29–124`,
`services/llm_execution.py:824–856`, `services/durable_step_journal.py:45–103`,
`migrations/alembic/versions/0246_latest_model_history_cutover.py:73–97,121–171,264–279,385–401`,
`deploy/hetzner/release.py:381–442,610–692`, `deploy/hetzner/deploy.sh:25,105`,
`python/nexus/release_backup.py:215–251`. `0246` copies authorship then deletes
ledger positions; `python/nexus/services/generation_effects.py:20–61` still needs
live position/parent rows. copied authorship alone does not prove retained undo.
