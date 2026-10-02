# authoritative native non-submission

status: open; provider/kernel contract gap, 2026-10-02.

problem: `TurnNotStarted` and missing native identity do not prove absence of
submission. current conservative uncertainty is correct; consumers cannot safely
clear it merely by recognizing an exception class.

impact: deterministic request errors can strand admitted work; an overbroad fix
can invent certainty and repeat effects. repeated model computation itself is
acceptable under the owner's selected recovery policy.

evidence: [review finding 1](../native-agent-review.md#1-non-submission-is-a-missing-provider-fact-not-an-exception-policy),
pinned provider `runtime.py:1135–1161` and `codex_sdk.py:690–698`;
current [recovery rule](../../SPEC.md#172-recovery-and-uncertainty).

resolved when: provider preflight precedes arm/send, and an explicit original-attempt
proof guarantees no delayed submission; remote rejection is safe only under
audited native semantics. timeout/lost reply retain original attempt uncertainty;
fenced replacement reasoning may proceed automatically with action recovery
barriers. preserve old evidence and qualify the migration. N001–N003 and N005 in
[n1](../native-agent-spec.md#9-delivery-and-acceptance)
must pass, with owning provider/kernel spec amendments.
