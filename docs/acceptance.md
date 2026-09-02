# Acceptance criteria

These criteria define the future implementation's release contract. The slice
assignment table is authoritative; every criterion belongs to exactly one
slice.

## Boundary and package

- **K001** — The package supports Python 3.12 or newer and imports as
  `llm_agent_kernel`.
- **K002** — Importing the package performs no I/O, starts no worker, opens no
  provider session, and grants no tool authority.
- **K003** — The package contains no application database schema, migration,
  connector, transport, credential resolver, memory store, approval policy, or
  application tool binding.
- **K004** — Provider integration uses a qualified pinned git revision and the
  public `provider-runtime` contract; no provider SDK type crosses the adapter
  boundary.
- **K005** — Tool and prompt integration uses a qualified pinned git revision
  and public `llm-tools` contracts; the package contains no second catalog,
  profile, executor, discovery engine, or XML-like prompt renderer.

## Definitions and context

- **K006** — Public types distinguish an agent definition, application thread,
  run/drain, model step, provider session, and role.
- **K007** — One agent definition freezes its role instructions, session mode,
  maximum capability envelope, context projection, conversational or closed
  structured output contract, and explicit limits. Each run plan is frozen and
  must be a subset of that envelope. V1 thread runs require continuing mode;
  one-shot runs require isolated mode and structured output.
- **K008** — Context is represented as provider-neutral typed sections and can
  be projected for a continuing session or a cold bootstrap without changing
  canonical context selection.
- **K009** — A cold bootstrap is sufficient to continue useful work after all
  provider-session state is deleted.
- **K010** — Source timestamps and one host-supplied `as_of` value survive
  context construction without making wall-clock access ambient to later steps.

## Step protocol and tools

- **K011** — The only standard model steps are closed `say`, `call_tools`, and
  `finish` variants. Conversational definitions forbid terminal results;
  structured definitions forbid user-facing text and require a schema-valid
  terminal result.
- **K012** — `call_tools` contains one or more canonical granted tool IDs with
  closed arguments, no user-facing text, and no model-authored authority
  classification.
- **K013** — The entire step is decoded and validated before any output is
  emitted or any tool is dispatched, including validation of a structured
  terminal result against the frozen output contract.
- **K014** — Missing, malformed, ungranted, or protocol-invalid output dispatches
  no tool and returns bounded corrective feedback to the next model step.
- **K015** — Independent calls may execute concurrently only within the frozen
  capability plan and shared run budgets, and only when declared non-effectful
  and host-classified automatic/non-stopping; observations retain deterministic
  call order.
- **K016** — Tool dispatch goes through an application-supplied dispatcher and
  `llm-tools`; the kernel never invokes an application binding directly.
- **K017** — The dispatcher can return executed, pending-approval, denied,
  failed, or uncertain observations without the kernel deciding which applies.
- **K018** — A pending-approval observation concludes the proposing input without
  holding an interpreter, provider call, process, or database transaction open;
  compatible newer input may continue under the drain and other classes are
  handed off.

## Loop, coordination, and failure

- **K019** — Every run has explicit model-call, tool-call, elapsed-time, input,
  output, observation, and concurrency limits; no unbounded default exists.
- **K020** — Cancellation is checked before model calls, before tool dispatch,
  while awaiting concurrent calls, and before finalization.
- **K021** — At most one drain owns an application thread through the supplied
  coordination port; a competing claim returns busy rather than running twice.
- **K022** — Semantic input is consumed through an opaque ordered checkpoint and
  host-defined run class; the kernel requires no particular ID type, class
  representation, or database layout.
- **K023** — Finalization compares the consumed checkpoint atomically through a
  host port. Compatible new waking input causes continuation; incompatible or
  over-budget input causes an atomically armed deferred run before claim
  release, never a lost wake-up or cross-plan drain.
- **K024** — Protocol feedback and tool observations are offered to the event
  sink before reuse; sink failure is nonfatal, persistence is optional, and
  correctness relies only on terminal-conclusion and effect boundaries.
- **K025** — Provider-session resume failure discards the session reference and
  attempts at most one cold bootstrap when the host permits it.
- **K026** — A model turn is never blindly retried after a possibly effectful
  tool dispatch; recovery is driven by the host dispatcher and effect ledger.
- **K027** — Kernel defects, model/protocol failures, cancellations, budget
  exhaustion, provider/adapter failures, and typed host-dispatch observations
  remain distinguishable; ordinary dispatch observations are not mislabeled as
  terminal run outcomes.

## Assurance

- **K028** — Deterministic fakes cover every model, session, dispatcher,
  checkpoint, finalization, event-sink, clock, and cancellation port.
- **K029** — Conformance tests inject failures before and after claim, model
  result, trace emission, effectful dispatch commit, and finalization.
- **K030** — Race tests prove that input arriving during the final model call is
  not lost, budget-exhausted handoff arms another run before claim release, and
  cancellation/error cleanup also arms a run for any still-unconsumed input;
  two drainers cannot both own one thread. Mixed-class tests prove a claim reads
  only the maximal same-class prefix, a mismatched initial claim calls no
  provider and arms the correct run, and a newer incompatible input forces an
  armed defer even when budget remains.
- **K031** — Protocol fuzz tests prove that invalid steps produce no partial
  output or tool execution.
- **K032** — Session-loss tests prove continuation, compatible resume, cold
  bootstrap, the single-bootstrap-attempt limit, and safe discard of a
  speculative reference when canonical input remains unconsumed. A stale
  compare-and-set cannot dispatch or settle, and successful stores advance the
  expected generation.
- **K033** — Pending-approval tests prove suspension and later continuation from
  a host-authored action-resolution input correlated by opaque host reference,
  without replaying the original effect.
- **K034** — Budget and cancellation tests prove bounded cleanup and exactly one
  terminal kernel outcome per started run. Isolated one-shot tests prove a fresh
  session, structured output, a non-effectful plan, no checkpoint or saved-
  session-reference access, and one schema-valid result. Provider-internal
  continuation state is non-canonical. Invalid mode/façade combinations fail
  before I/O.
- **K035** — An opt-in live qualification matrix covers the supported
  `provider-runtime` route without running in ordinary CI or printing prompts,
  credentials, or private tool payloads.

## Slice assignment

| Slice | Acceptance IDs |
| --- | --- |
| 0 — contract and package | K001–K007, K028 |
| 1 — context and provider sessions | K008–K010, K025 |
| 2 — strict step and tool loop | K011–K020, K024, K026–K027, K031, K034 |
| 3 — drain and finalization | K021–K023, K029–K030, K032–K033 |
| 4 — qualification and release | K035 |
