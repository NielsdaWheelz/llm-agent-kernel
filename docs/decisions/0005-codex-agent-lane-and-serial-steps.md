# ADR 0005: Use the Codex AgentRuntime lane and one serial tool step

- Status: Accepted
- Date: 2026-09-02

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
writeable filesystem, and provider approvals are disabled. The cwd is private,
empty, and read-only. Any native tool-use or permission-request event is a
fail-stop containment violation. The complete policy and native configuration
participate in the definition fingerprint.

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

- One-shot work opens a subprocess/session per invocation.
- Serial tools can be slower than safe parallel reads.
- V1 is not provider-lane-neutral at runtime; future lanes need separate
  qualified adapters and semantics.
- The wire envelope and JSON-string arguments add tokens and require a separate
  strict decode before logical validation.
- No model-authored progress prose appears during long loops.

## Rejected alternatives

- A synthetic provider port combining stateless and agent surfaces: impossible
  to implement faithfully.
- Provider-native application tools: bypass the host tool/effect boundary.
- Multi-call steps: require durable partial execution semantics v1 does not
  need.
- Parallel reads: a `Read` can still suspend, fail, rebill, or return an
  uncertainty boundary.
