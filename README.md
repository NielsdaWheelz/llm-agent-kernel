# llm-agent-kernel

`llm-agent-kernel` is a small Python control plane for bounded, tool-using
agents. Applications import `llm_agent_kernel`.

It turns host-owned durable input into validated model steps, serial tool
observations, and durable host conclusions. Reasoning never grants authority:
the native provider containment policy and the host-selected frozen
`llm-tools` plan jointly define what a run can do.

Jarvis is the first consumer, but the package is not Jarvis-specific.

## Status

Version 0.1.0 implements the v1 kernel and targets Python 3.12 or newer. The
lockfile resolves the two runtime libraries from the exact qualified revisions
below, never from mutable branches or sibling worktrees.

The reviewed dependency baselines are:

- `provider-runtime` from `llm-calling` at
  `a5d9c8e0c1c851daee0731554e0a4a326d3c2819`
- `llm-tools` at `728f35c0b3a8be91b380ed4258d2b73ad68fc8fa`

V1 uses the real subscription-backed
`provider_runtime.agent_runtime.AgentRuntime` lane. It does not use stateless
generation, MCP application tools, or provider-native application tools.

## Install and verify

The package is independently buildable with `uv`:

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

The primary entry points are `run_thread(...)` and `run_one_shot(...)`.
Applications construct an immutable `AgentDefinition`, provide one qualified
frozen `llm-tools` plan and budget, and implement the typed ports. A continuing
run composes `CodexProvider` with `SessionCoordinator`; production provider work
therefore consumes `AgentRuntime.stream_turn` and never the event-discarding
`run_turn` projection.

The package root exports the public values, ports, outcomes, provider/session
lifecycle, protocol and context helpers, loop entry points, opt-in
`DiagnosticTranscript` redaction boundary, and deterministic fakes. Diagnostics
are emitted only after the caller's redactor returns an explicit `RedactedText`;
redactor and sink failures are nonfatal. The same API remains grouped by module
under `llm_agent_kernel` for consumers that prefer qualified imports.

The [minimal thread example](examples/minimal_thread.py) runs entirely against a
scripted `AgentRuntime` and the process-local fakes:

```console
uv run python examples/minimal_thread.py
```

It performs no provider or network I/O. Its checkpoint, session-reference, and
admission state disappear with the process; they are not examples of production
durability.

## Boundary

The kernel owns:

- Immutable definitions and complete containment fingerprints.
- Exact Codex agent-session request mapping and lifecycle.
- Provider-neutral cold-bootstrap and continuation context.
- A closed `say | call_tool | finish` protocol.
- Whole-step and output-contract validation.
- Exactly one serial host tool call per model step.
- Mid-loop input polling, preemption, cancellation, and settlement choreography.
- Per-run limits and conservative host-issued cross-run admission reservations.
- Session-reference, input-checkpoint, provider, context, dispatch, and event
  ports.
- Isolated structured one-shot runs containing no `Write` tool.
- Deterministic conformance tests across crash and multi-run seams.

The kernel does not own:

- Application schemas, migrations, queues, workflows, schedulers, or delivery.
- Product context, memory, connectors, credentials, approvals, or action state.
- Input priority, effect identity, durable effect recording, or reconciliation.
- A second tool catalog, executor, budget, recorder, prompt renderer, or
  provider SDK adapter.
- Program execution, semantic discovery, or a delegation graph.

Owning no schema does not mean requiring no durable state. A continuing host
with writes normally needs canonical input/conclusion/delivery state, disposable
provider-session-reference state, and a durable `llm-tools` recorder/effect
record.

The included `InMemory*`, `Static*`, `Scripted*`, and `Recording*` classes are
process-local test doubles. They are intentionally honest about restart: they
do not make input, conclusion, session-reference, effect, or admission facts
durable. A production continuing host must durably store:

- canonical input, exclusive claim ownership, attempt number, checkpoint, and
  atomic conclusion/consumption;
- session references keyed by thread and definition fingerprint with generation
  CAS;
- rolling admission reservations, actual usage, and orphaned-slot recovery;
- for every `Write`, the host action/effect record and `llm-tools` durable
  recorder state, using one stable ID as both `InvocationPosition` and
  `EffectId`;
- suspension references plus the original validated arguments and later safe
  reconciliation evidence.

The host also owns startup scans over canonical unconsumed input and orphaned
admission records. Kernel cleanup never schedules a successor.

## Execution at a glance

```text
durable host input
        |
        v
claim batch + reserve rolling admission + prove exact plan/catalog tightening
        |
        v
open/resume contained Codex agent session
        |
        v
poll new compatible input --> fully observed structured provider stream
                                  |
                       persist returned session ref
                                  |
                       validate complete model step
                         /                    \
                  call_tool                say / finish
                      |                         |
            poll, then serial dispatch      poll for stop
                 /             \                |
         completed          suspended      atomic settle
             |                  |                |
       bounded observation  durable host ref    v
             +-------> next provider turn     return
```

A deterministic no-progress stop consumes the poison input with a host-authored
conclusion. Cleanup never silently arms a fresh-budget successor. A crash can
leave input unconsumed, but durable attempt accounting and rolling admission
bound recovery before another provider call. Interrupted admission retains its
reserved rolling turn/token charge while startup releases only the orphaned
concurrency slot.

V1 commits a valid answer for the input it answered even if an ordinary
follow-up races with finalization; the follow-up is processed next. Explicit
stop/pause input can preempt. V1 also omits model-authored progress narration,
parallel calls, and a durable generic observation store.

## Documents

- [Specification](SPEC.md)
- [Architecture](docs/architecture.md)
- [Acceptance criteria](docs/acceptance.md)
- [Conformance map](docs/conformance.md)
- [Implementation plan](docs/implementation-plan.md)
- [Architecture decisions](docs/decisions/README.md)
- [Host integration and release qualification](docs/host-integration.md)
