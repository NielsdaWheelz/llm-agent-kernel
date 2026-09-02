# llm-agent-kernel

`llm-agent-kernel` is a small, provider-neutral runtime for bounded tool-using
agents. The Python distribution is `llm-agent-kernel`; applications import
`llm_agent_kernel`.

It turns durable application input into a sequence of validated model steps,
tool observations, and terminal outcomes. It preserves a hard boundary between
reasoning and authority: models propose steps, `llm-tools` validates and executes
granted tools, and the application decides policy, persistence, and delivery.

Jarvis is the first consumer. The package is deliberately not Jarvis-specific.

## Status

This repository currently specifies the v1 package. Implementation begins only
after the specification and ADRs are accepted.

Runtime target: Python 3.12.

Direct dependencies:

- `llm-calling` (`provider-runtime`) for provider calls and resumable sessions.
- `llm-tools` for frozen capability plans, typed prompt sections, tool schemas,
  validation, execution, effect boundaries, and result envelopes.

## The boundary

The kernel owns:

- A bounded run/drain loop.
- Strict whole-step validation for `say`, `call_tools`, and `finish`.
- Continuation and cold-bootstrap context projections.
- Provider-session reference lifecycle through an application port.
- Input checkpoints, exclusive plan-class drains, and race-safe idle transitions
  through an application port.
- Budgets, cancellation, turn-local protocol feedback, and normalized trace
  events.
- Fresh one-shot runs with schema-validated terminal results for recomputable
  read-only internal cognitive work.
- Thin adapters to `provider-runtime` and `llm-tools`.

The kernel does **not** own:

- Database schemas, migrations, queues, workflows, or schedulers.
- Connectors, credentials, memory, approval policy, or user interfaces.
- A tool registry, tool implementation, effect recorder, or policy engine.
- Provider implementations or provider-shaped canonical history.
- XML rendering or parsing.
- Lua, generated-code execution, sandboxes, or a subagent graph.

Applications implement narrow ports over state they already own. Adopting this
package must not require a new persistent table.

## Terminology

- **Agent definition:** immutable runtime configuration: role, stable context,
  maximum capability envelope, provider profile, context policy, output
  contract, and limits. It is not a database row or a running process. Each run
  receives a frozen plan that may only narrow that envelope.
- **Role:** the behavioral purpose and instructions inside an agent definition.
  Several invocations may use the same role.
- **Application thread:** the host-owned durable workstream whose ordered input
  and terminal conclusions survive providers and processes.
- **Run:** one host invocation asking the kernel to process an application
  thread or perform an isolated one-shot invocation.
- **Drain:** the exclusive processing epoch inside a run. It consumes the
  maximal ordered input prefix eligible for one host-defined plan class until a
  race-safe idle transition, class handoff, or bounded stop outcome.
- **Model step:** one provider response, parsed as exactly one of `say`,
  `call_tools`, or `finish`.
- **Provider session:** an opaque, disposable continuation optimization. It is
  never the canonical application thread.

Thread runs use the drain shown below. Isolated one-shot runs reuse the same
bounded step loop but open a fresh session, use no checkpoint or saved session
reference, accept only non-effectful tools, and return a schema-valid structured
terminal result for the host to commit. V1 thread runs require continuing
definitions; v1 one-shot runs require isolated structured definitions.

## Execution at a glance

```text
durable waking input
        |
        v
exclusive drain claim + input checkpoint
        |
        v
continuation context ──────┐
or cold-bootstrap context  │
        |                  │
        v                  │
provider model step        │
        |                  │
strict whole-step check    │
        |                  │
   call_tools ──> llm-tools/host dispatch ──> observations ──┘
        |
   say / finish / pending approval / uncertain
        |
        v
durable conclusion + consumed checkpoint
        |
        v
compare-and-set idle; continue only for compatible newer input
otherwise arm the correct class before releasing the claim
```

Malformed output produces no user-visible text and no tool effect. The kernel
emits a bounded corrective diagnostic and may ask the model again. A tool
dispatcher may return `pending_approval` after the application durably creates
an approval request, but the kernel neither decides that policy nor executes the
pending action.

`call_tools` itself contains no user-facing prose. The model sees correlated
results first and may then produce a separate `say`, avoiding pre-action claims
and nonterminal delivery state.

## Design documents

- [Specification](SPEC.md)
- [Architecture](docs/architecture.md)
- [ADR 0001: Library boundary](docs/decisions/0001-library-boundary.md)
- [ADR 0002: Event-drain kernel](docs/decisions/0002-event-drain-kernel.md)
- [ADR 0003: Provider and tool ownership](docs/decisions/0003-provider-and-tool-ownership.md)
- [ADR 0004: Defer program agents and delegation](docs/decisions/0004-defer-program-agents-and-delegation.md)
