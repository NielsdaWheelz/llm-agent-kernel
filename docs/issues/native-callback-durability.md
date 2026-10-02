# durable invocations before native terminal

status: open; planned native-main migration gap, 2026-10-02.

problem: current journals complete model decisions at terminal. jarvis derives
Read and isolated write-gate identities from those decisions. several callbacks
inside one native turn require distinct accepted-invocation identities and a
result-before-reply boundary.

impact: naive reuse aliases work, rebills reads/gates, or repeats effects after
reply loss. post-terminal session-reference CAS is too late for callback effects.

evidence: [review finding 6](../native-agent-review.md#6-jarvis-needs-a-new-durable-unit-accepted-invocation),
jarvis `decisions.py:304–362`, `read_positions.py:69–71`,
`write_dispatch.py:202–210`; kernel `ModelDecisionJournal.complete`.

resolved when: accepted invocation is durably fenced before dispatch; original
result precedes reply; action ids remain both Write position and effect id;
distinct callbacks have distinct Read/gate identities. duplicate/changed callbacks,
stale owner, crash after effect and lost reply cannot repeat effects. pending
approval must return a durable pending status, allow independent work and block
dependent effects. later resolution uses the original action and a new host event,
without rewriting the callback reply or repeating execution. stop cancels pending
approvals atomically against approval/dispatch; fresh approval on resume cannot
repeat an already-dispatched action. prove waiting/resume
and cold bootstrap against jarvis's real store. N011, N016–N018.
selected design: [native journal and host schemas](../native-agent-spec.md#6-callbacks-before-terminal).
implementation/qualification remain open. pending receipts must not terminalize an
unexecuted action's recorder position; malformed rejected writes require no valid
owner-input foreign key or execution link. legacy dispatched effects must settle
before deleting their execution decoder; pending approvals migrate with fresh consent.
