# ADR 0003: Preserve provider-runtime and llm-tools ownership

- Status: Accepted
- Date: 2026-09-01

## Context

Codapt2 contains its own provider adapter, host-function registry, schema
boundary, prompt renderer, semantic discovery, and durable operation machinery.
The Python ecosystem in scope already has focused libraries for those concerns.
Duplicating them would create divergent security and replay behavior.

## Decision

Use public `provider-runtime` contracts for:

- Provider calls and normalized model outcomes.
- Native Codex/Claude session creation, resume, cancellation, containment, and
  session references.
- Provider-specific structured-output lowering and normalized events.

Use public `llm-tools` contracts for:

- Typed prompt sections and rendering.
- Tool declarations, bindings, catalogs, frozen profiles, and exposure plans.
- Input/output validation, budgets, execution, invocation positions, effect
  identities, recorder contracts, and optional discovery.

The kernel coordinates these contracts. It does not import provider SDKs,
execute application bindings directly, decide approval policy, resolve
credentials, or construct a second registry.

Applications supply a dispatcher because authority and asynchronous approval
belong to the product. The dispatcher may return a pending-approval observation;
the kernel concludes that proposing input and later consumes a host-authored
action-resolution input correlated by the dispatcher's opaque reference.

## Consequences

Positive:

- Security-critical behavior retains one owner.
- Provider and tool evolution can be qualified independently.
- The kernel stays small enough for other applications.

Costs:

- Compatibility spans three packages and requires an integration matrix.
- Some types require narrow adapters rather than direct re-export.
- Applications remain responsible for durable tool/action storage.

## Rejected alternatives

- Port Codapt2's registry: weaker than and duplicative of `llm-tools`.
- Add provider SDK adapters: duplicates `provider-runtime` lifecycle and
  containment.
- Put application approval states in the kernel: turns product authority into a
  misleading generic policy.
- Treat prompt markup as a security boundary: formatting cannot neutralize
  semantic prompt injection.
