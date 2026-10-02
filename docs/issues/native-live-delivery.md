# live delivery and approvals during native work

status: design selected; implementation and qualification pending, 2026-10-02.

problem: jarvis holds its execution mutex over the full drain/native run; approval
handling waits on that mutex and outbox flushing follows the run. its assistant
outbox also treats source_message_id as the actual discord delivery id, not a
native message deduplication id.

impact: merely adding progress events/pending callback receipts still leaves the
owner without progress or approval resolution until native finality. storing a
native id in source_message_id can falsely mark an update delivered.

evidence: jarvis service.py:304,418–419,493–497; db.py:99–104 and
messages.py:1171–1231. [selected control design](../native-agent-spec.md#7-live-control-input-and-time).

resolved when: ingress, consent and outbox delivery remain live; only actual tool/
action dispatch is serialized. use deterministic message.id for native deduplication
and leave source_message_id null until delivery. prove an open native turn emits
visible progress and receives an approved action's resolution before finality.
real service/outbox acceptance belongs to n4, N016/N019.
