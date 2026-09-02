# llm-agent-kernel

`llm-agent-kernel` is a small Python control plane for bounded, tool-using
agents. Applications import `llm_agent_kernel`.

It turns host-owned durable input into validated model steps, serial tool
observations, and durable host conclusions. Reasoning never grants authority:
the native provider containment policy and the host-selected frozen
`llm-tools` plan jointly define what a run can do.

Jarvis is the first consumer, but the package is not Jarvis-specific.

## Status

This repository specifies v1. Runtime implementation begins only after the
required `llm-tools` public seams are added and pinned. The target is Python
3.12 or newer.

The reviewed dependency baselines are:

- `provider-runtime` from `llm-calling` at
  `a5d9c8e0c1c851daee0731554e0a4a326d3c2819`
- `llm-tools` at `8df458a199703120005296ae12f997b39d208fed`

V1 uses the real subscription-backed
`provider_runtime.agent_runtime.AgentRuntime` lane. It does not use stateless
generation, MCP application tools, or provider-native application tools.

## Boundary

The kernel owns:

- Immutable definitions and complete containment fingerprints.
- Exact Codex agent-session request mapping and lifecycle.
- Provider-neutral cold-bootstrap and continuation context.
- A closed `say | call_tool | finish` protocol.
- Whole-step and output-contract validation.
- Exactly one serial host tool call per model step.
- Mid-loop input polling, preemption, cancellation, and settlement choreography.
- Per-run limits and enforcement of host-issued cross-run admission.
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

## Execution at a glance

```text
durable host input
        |
        v
claim non-empty batch + check rolling admission + prove plan tightening
        |
        v
open/resume contained Codex agent session
        |
        v
poll new compatible input --> structured provider turn
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
bound recovery before another provider call.

V1 commits a valid answer for the input it answered even if an ordinary
follow-up races with finalization; the follow-up is processed next. Explicit
stop/pause input can preempt. V1 also omits model-authored progress narration,
parallel calls, and a durable generic observation store.

## Documents

- [Specification](SPEC.md)
- [Architecture](docs/architecture.md)
- [Acceptance criteria](docs/acceptance.md)
- [Implementation plan](docs/implementation-plan.md)
- [Architecture decisions](docs/decisions/README.md)
