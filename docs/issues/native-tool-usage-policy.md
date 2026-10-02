# task-wide tool quotas are optional in the native target

status: open engineering change; owner preference settled, 2026-10-02.

problem: pinned llm-tools `RunLimits` requires finite cumulative calls, external
attempts, input/output bytes and elapsed time. those ceilings can terminate a
native task even after model-token budgets and the six-hour cutoff are removed.

impact: the existing public contract cannot directly express the owner's selected
no-usage-limit, no-arbitrary-jarvis-cutoff behavior. a huge sentinel or resetting
the budget every callback would conceal the mismatch.

evidence: llm-tools `9e6d155…`, [profiles.py:31](../../../llm-tools/src/llm_tools/profiles.py#L31)
defines and validates the limits; tightening compares them at 190–196;
[testing.py:93](../../../llm-tools/src/llm_tools/testing.py#L93) demonstrates cumulative
reservation semantics. host durable budget adapters must adopt the same contract.

resolved when: extend the existing public limit/plan representation so task-wide
usage/elapsed quotas can be absent, with canonical identity and correct tightening.
retain finite concurrency/backpressure, per-operation byte/time/attempt bounds,
effect authority, result recording and replay. no duplicate executor or hidden
quota resets. qualify the real consumer budget adapters and N010/N015. numeric
usage may remain observational; missing usage cannot block new work.

selected API: [tools and limits](../native-agent-spec.md#tools-and-limits).
null means no cumulative ceiling; one shared predicate handles tightening/reservation
semantics. promote the reusable budget implementation, not the test recorder.
implementation and final consumer proof remain open.
