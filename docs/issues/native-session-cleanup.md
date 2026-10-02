# keep cleanup scoped to its session

status: design selected; implementation and qualification pending, 2026-10-02.

problem: pinned provider runtime.py:639–652 escalates turn cleanup timeout to
adapter.close(), invalidating every session on that adapter.

impact: a failed nested gate or another job can terminate healthy native work even
though the shared app-server process remains alive.

evidence: provider 69d41d38, agent_runtime/runtime.py; selected
[controlled-turn contract](../native-agent-spec.md#4-submission-evidence-and-paid-recovery).

resolved when: close/timeout affects only its handle/session, preserves its original
evidence and leaves healthy parent/gate/other-job sessions usable. no process fallback
or whole-adapter shutdown for one turn's timeout. portable n3/N012/N015 proof is
followed by actual jarvis/nexus shared-server proof in N019/N020.
