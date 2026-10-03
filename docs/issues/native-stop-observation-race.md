# jarvis stop races late provider facts

status: attributable RED; consumer journal repair and installed repeat pending.

problem: canonical stop fences the attempt before a queued AgentInputRecorded
is persisted. jarvis's delivery journal incorrectly requires live authority for
that original provider observation. NativeDefect bypasses the explicit kernel
interrupt/control/grace path. changing event priority cannot close the database race.

impact: host dispatch/publication fences hold, and missing native completion stays
unknown; ordinary stop can nevertheless lose its durable control evidence. provider
cleanup may still interrupt. absent receipts prove neither no interrupt nor termination.

evidence: installed jarvis5d84d03/providerE149/kernel9d57/tools2adb.
actual observation delayed at the journal port until ordinary stop committed:
kernel native.py:438 → jarvis native_journal.py:627,860 raises
`NativeDefect('native attempt authority is stale')`, attempt470a3403.
controlled-scheduling genuine receipt sha256
`727f14def747324893d018124cc08a38b3b781ff03aeeb00da7256b45e674cde`.
an unmodified second run recorded native cancellation; the failure is a race.

repair owner: jarvis journal. retain immutable original bind and existing delivery
observations after fencing; new prepared input still requires live authority.
late progress publishes nothing. invocation/effect/product authority stays strict.
nexus already records these observations without execution authority; no shared
kernel change or nexus adoption dependency is required.

resolved when: real-store delayed bind/delivery/progress races retain exact original
facts, reject changed/unknown identities and new input, never publish after stop;
final frozen installed genuine stop executes the explicit control path and retains
observed native terminal or truthful local-stop uncertainty. an interrupt ack is
never a native terminal. preserve original entered effects and prevent stopped work
from restarting.
