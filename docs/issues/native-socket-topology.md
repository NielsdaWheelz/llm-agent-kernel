# nexus worker access to the native socket

status: target topology selected; container qualification pending, 2026-10-02.

problem: the present worker sees the HTTP socket; native sockets may be symlinks
into a private codex daemon directory. mounting only the requested path need not
make the native endpoint reachable from a worker.

impact: a nominal socket migration can fail startup or expose the wrong authority;
shared-service cancellation also needs isolation across jobs.

evidence: nexus apps/codex_agent/native_server.py:122–154,184–211; compose host/worker
uid 10001. [selected topology](../native-agent-spec.md#nexus-schema-and-composition).

resolved when: the actual target resolves inside the private shared socket volume
on both sides with matching uid/permissions and host-visible contained cwd. credentials
and account refresh remain host-owned. N020 proves actual attach, two jobs, correct
callback/result correlation and isolated cancellation without a callback relay.
