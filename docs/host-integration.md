# Host integration and release qualification

`llm-agent-kernel` deliberately stops at asynchronous ports. A production host
must implement persistence and product policy outside this package; replacing a
store with an in-memory adapter changes the recovery guarantee and is not a
deployment option for continuing effectful work.

## Required durable facts

The checkpoint store is canonical for ordered input, exclusive claim ownership,
the oldest-input attempt number, checkpoint advancement, and atomic
conclusion/consumption. `release` is idempotent cleanup and never signals new
work. Startup scans the same unconsumed input used by `claim`.

The kernel calls `park` before returning `configuration_error`; the checkpoint
implementation must atomically release ownership into a durable operator-only
park and trip the applicable thread or deployment circuit breaker. Only
operator correction may clear it. `release` remains ordinary cleanup and is
deliberately not a hidden scheduling or parking operation.

The session-reference store is keyed by `(thread_id, definition_fingerprint)`
and implements generation CAS. A successful provider terminal is stored before
validation, display, dispatch, or settlement. Recovery discards a speculative
reference before cold-bootstrap replay.

The admission journal reserves the run's configured maximum turns and token
allowances plus one live root slot before provider I/O. Clean settlement records
available actual usage and refunds unused capacity. Startup recovery releases
only an orphan's live slot; its rolling turn/token reservation remains charged.
A corrupt or missing journal fails closed.

`AgentRuntime` reports token usage after a turn and supplies no hard turn-level
token cap. The admission adapter must therefore add a finite, route-qualified
one-turn input/output overshoot allowance to the requested token reservation.
This only protects the rolling journal from a terminal report above the kernel
threshold; it does not increase `KernelLimits`. Jarvis must record and qualify
those route-specific values before release.

The dispatcher owns effect identity and execution. Before a `Write` enters
`llm-tools`, it durably creates or resolves the action record and supplies its
stable ID as both `InvocationPosition` and `EffectId`. It preserves the kernel's
immutable claim/checkpoint/input/model-step lineage. Suspension persistence
includes the opaque host reference, tool ID, original validated arguments,
resolution state, and safe evidence.

No database transaction or blocking row lock may span provider or external tool
I/O.

## Qualification

Ordinary CI is deterministic and network-disabled. It proves exact request
shape, complete `stream_turn` inspection, disabled native authority, pure plan
and whole-step validation, serial dispatch, session CAS ordering, bounded
context, polling/finalization races, admission recovery, and isolated cleanup.

Before a release, the first real consumer must additionally qualify its durable
checkpoint, action/recorder, admission, and delivery implementations under
process termination at each boundary. Jarvis must run its paid Codex account
qualification for the exact provider-runtime pin and record only sanitized
route, revision, status, usage, timing, and trace identifiers. Provider-native
transcripts remain unredacted third-party data at rest; deleting a local
reference does not promise provider deletion.

The library release commands are:

```console
uv sync --frozen --all-groups
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest -q
uv build
uv run pip-audit
git diff --check
```
