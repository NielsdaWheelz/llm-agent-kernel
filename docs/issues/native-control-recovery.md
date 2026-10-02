# native control and input recovery

status: open; native supervision design/qualification gap, 2026-10-02.

problem: callback-boundary polling cannot handle silent reasoning or blocked
handlers. accepted steering is not necessarily incorporated input; interrupt
acknowledgment and detached session are not native completion.

impact: stop or useful progress can stall, input can be consumed twice or lost, and a stale stream can
submit effects after replacement ownership. an admitted Write cannot be undone by
native cancellation.

evidence: [control contract](../native-agent-spec.md#7-live-control-input-and-time),
provider stop/terminal race in pinned `runtime.py:1135–1161`, and jarvis's invalidated
owner rule at `SPEC.md:2020–2024`. codapt supplies useful correlated steering and
interrupt observation, not jarvis callback recovery proof.

resolved when: control works while no callback arrives and while a handler waits;
brief public progress/partial answers arrive without becoming effect authority
or false canonical completion;
new topics arrive promptly without implicitly cancelling unfinished work;
steering has original identity and truthful checkpoints; late old-owner callbacks
cannot dispatch; finite interruption grace records unresolved native execution.
transport failures may restart reasoning after fencing; explicit owner stop may
not. admitted effects remain settled or fenced for recovery. N011–N013,
N015–N018, plus nexus's separate N008 cancellation races.

selected design: [live control](../native-agent-spec.md#7-live-control-input-and-time)
and [consumer receipts](../native-agent-spec.md#jarvis-schema). preserve host-event
consumption separately from owner-request completion. native terminal commit cannot
let stale product settlement overwrite stop/resume; claim recovery processes retained
terminals locally before overlapping admission. see the separate delivery issue for
the current service mutex/outbox defects.
