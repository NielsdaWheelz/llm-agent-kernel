# ADR 0005: Use the Codex AgentRuntime lane and one serial tool step

- Status: Accepted
- Date: 2026-09-02
- Amended: 2026-09-09

## Context

`provider-runtime` exposes two distinct surfaces. Root stateless generation and
stateful native `AgentRuntime` sessions do not share one lifecycle or terminal
type. The first kernel draft described a union matching neither. It also allowed
multi-call parallel steps, which require durable partial-outcome vectors and
not-initiated outcomes to recover safely.

Jarvis benefits from Codex's own session history and compaction, but application
tools must remain behind the host's plan, approval, and recorder boundaries.

## Decision

V1 uses only subscription-backed
`provider_runtime.agent_runtime.AgentRuntime` with explicit open/stream/close
lifecycle and `JsonSchemaAgentOutput`. The adapter consumes the public
`stream_turn` event stream and does not use the `run_turn` convenience
projection, because the latter exposes only the terminal and cannot support the
required native-authority fail-stop.

Provider-native built-ins, native Web, MCP, network, copied environment,
writeable filesystem, and provider approvals are disabled. The cwd is empty
and read-only, private by default or explicitly shared through the documented
host-provisioned group boundary. Any native tool-use or permission-request event is a
fail-stop containment violation. The complete policy and native configuration
participate in the definition fingerprint.

The kernel also supplies one bounded immutable base instruction in the system
channel before application system material. It replaces Codex's coding-agent
base prompt and defines the contained structured-agent protocol, including the
complete `HostTable`, final-step-only execution, observational commentary, and
kernel-owned tool observations. Its revision and digest participate in every
definition fingerprint, automatically rotating saved-session identity when the
kernel protocol changes. The prompt is behavioral guidance; authority remains
the provider event fail-stop plus the frozen host plan.

The provider owns the WebSocket/Unix-socket connection to the externally
supervised Codex App Server behind the preserved `transport="sdk"` route literal. A
`ProtocolDefect` is fatal and yields no acceptable terminal. Native Code Mode is
contained/detected rather than proven absent before its first event, and the
read-only cwd is not a host-confidentiality boundary.

Application tools are represented through a frozen `llm-tools HostTable` in
structured host context. The model emits exactly one `call_tool(tool_id,
arguments)` step. Calls execute serially and the model supplies no call or
effect identity.

That step is the logical protocol, not the literal Codex transport object. The
`JsonSchemaAgentOutput` wire uses one closed root envelope with required nullable
branch payloads because Codex does not accept a root discriminated union or
omitted object properties. Arbitrary tool arguments cross as a strict JSON
object encoded in a string, then decode into the unchanged logical `arguments`
mapping before pure tool validation. Structured result schemas are compiled or
rejected before provider I/O.

The provider session is a disposable continuation optimization. The host saves
generation-checked refs, may cache one live session, and can cold-bootstrap from
canonical context.

## Consequences

Benefits:

- The specification matches the real dependency API.
- Codex session history and compaction provide cache/latency benefits without
  becoming canonical state.
- One-call steps eliminate partial vectors, parallel uncertainty, and a false
  “all reads are safe” invariant.

Costs:

- One-shot work opens a native session on the shared server per invocation.
- Serial tools can be slower than safe parallel reads.
- V1 is not provider-lane-neutral at runtime; future lanes need separate
  qualified adapters and semantics.
- The wire envelope and JSON-string arguments add tokens and require a separate
  strict decode before logical validation.
- Kernel instruction changes deliberately cold-bootstrap continuing sessions;
  strict protocol drift can reduce availability until audited.
- No model-authored progress prose appears during long loops.

## Rejected alternatives

- A synthetic provider port combining stateless and agent surfaces: impossible
  to implement faithfully.
- Provider-native application tools: bypass the host tool/effect boundary.
- Multi-call steps: require durable partial execution semantics v1 does not
  need.
- Parallel reads: a `Read` can still suspend, fail, rebill, or return an
  uncertainty boundary.
