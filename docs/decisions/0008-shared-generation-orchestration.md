# ADR 0008: Share ordered generation choreography with Nexus

- Status: Accepted
- Date: 2026-09-09
- Supersedes the package-wide lane restriction in ADR 0005; preserves its
  contained AgentRuntime protocol and authority requirements.

## Context

Nexus now has API and Codex generation routes. Its accepted runtime durably
arms each native child, commits a terminal and successor continuation together,
acknowledges observations, executes model-proposed tools serially, and reopens
the committed continuation before preparing another child. Nexus also owns
frozen product selections, SQL transactions, encrypted continuation records,
native transports, tool authority, and delivery. Those are not portable kernel
implementations.

Jarvis uses a contained structured AgentRuntime loop with input polling,
checkpoint settlement, and disposable provider sessions. Pretending these
provider lifecycles are interchangeable would erase their different contracts.
Keeping a second Nexus-owned model/tool loop would duplicate orchestration.

## Decision

Add `llm_agent_kernel.generation.run_generation` as the shared owner of the
actual Nexus child/tool sequence. Its frozen generic values carry typed native
payloads without importing Nexus schemas or inventing a third provider wire.
Native session orchestration remains in provider-runtime. Frozen request
projection and durable transactions remain host-owned.

The driver exposes only an event stream and pure successor preparation. Its
stream must await one kernel-supplied arming callback after native admission
and before dispatch. This callback is necessary because Codex admission can
refuse work before a child may safely be marked uncertain. Native transports
retain in-flight cancellation and resource cleanup.

The kernel validates the complete child stream before accepting a terminal.
It rejects any later event, mismatched proposal/continuation, or reordered
sequence. It awaits durable completion before acknowledging proposals and
the terminal, and awaits acknowledgment before executing any dependent tool.
The continuation contains the ordered original tool calls. Each tool executes
through the application's existing authority and llm-tools recorder. No
kernel-generated effect identity, automatic retry, or parallel dispatch exists.

Resumption starts from an exact continuation reopened and validated by the
host. Tool execution still uses the original recorder positions. Reopening a
continuation for the successor verifies that durable identity and canonical
bytes still equal the accepted decision. The package owns no decision table,
encryption key, reconciliation algorithm, or migration.

Turn exhaustion and cooperative cancellation return `GenerationStopped`,
including the last accepted terminal when available. They do not return an
ordinary completion or fabricate provider truth. The host persists its own
stopped parent outcome while preserving accepted child evidence. An accepted
final native failure is still `GenerationCompleted`: that value means the
generation has a durable final child, not that the model succeeded.

The contained AgentRuntime entry points remain explicit protocols in the same
package. Their sealed prompt, native authority containment, plan tightening,
admission, input polling, and action/effect boundary remain mandatory. Shared
invariants are durable decision before recoverable effects, authoritative
terminal selection, ordered dispatch, cancellation between effects, and no
synthetic success on exhaustion. A reducer rewrite is not required to enforce
those invariants.

## Consequences

- Nexus can delete its model/tool loop while retaining its accepted storage and
  provider contracts. Jarvis retains its contained interaction semantics.
- Adapters must prove their native request identity, dispatch timing,
  cancellation, and durable store behavior. Deterministic kernel fakes prove
  call ordering; they do not prove production crash durability.
- Full-stream validation can delay terminal acknowledgment until transport
  closure. Provider-owned deadlines must bound that wait.
- A host failure after a tool executes may require reconciliation; the kernel
  propagates that failure and never repeats a possibly effectful call itself.
- Generic payload parameters add a small typed integration surface. We accept
  this instead of exporting Nexus domain schemas or discarding native types.

## Rejected alternatives

- Wrap the existing Nexus loop: leaves two orchestration owners.
- Copy Nexus's generation schemas, ledger, or ToolAuthority into the kernel:
  transfers application authority and data ownership without a reusable need.
- Force both consumers into one provider protocol: loses established native
  terminal, admission, and continuation semantics.
- Resume the model to regenerate an unrecorded tool decision: cannot establish
  that the new effect matches the originally accepted one.
- Treat maximum-turn exhaustion as the last successful tool-request terminal:
  presents incomplete work as ordinary completion.
- Introduce a workflow service or parallel tool scheduler: neither is required
  by the two accepted consumer contracts.
