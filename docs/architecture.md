# architecture

provider-runtime owns native protocol facts; llm-tools owns executable tool
contracts; the kernel orders those mechanisms beneath host authority. jarvis and
nexus supply different durable application ports to the same `run_native`.

| module | hidden responsibility | public contract |
| --- | --- | --- |
| `native_contract.py` | frozen definition/work identity, base instruction and port types | `NativeDefinition`, `NativeRequest`, journal/input/message ports |
| `native.py` | one native turn, independent control, bounded callback queue and serial dispatch | `run_native` |
| `provider.py` | contained isolated sessions and typed native-event consumption | `CodexProvider`, `ProviderSessionLease` |
| `decisions.py` | exact paid model-decision recovery before interpretation | durable/transient isolated decision selection |
| `kernel.py`, `protocol.py` | isolated `call_tool`/`finish` loop and whole-step validation | `run_one_shot` |
| `generation.py` | retained raw-API child lifecycle and ordered proposals | `run_generation`, lifecycle/control/executor ports |
| `definitions.py`, `coordination.py` | owner permits, explicit dispatch lineage and host ports | immutable values and async contracts |
| `tools.py` | effective frozen authority, validation and declaration publication | host/native/read-only plan requirements |
| `context.py`, `events.py` | canonical rendering and redacted observation | context projections and event sinks |

callbacks flow through validation, host acceptance, one existing llm-tools
executor, durable result and durable wire reply. a completed callback receipt is
immutable. the reader/control lane does not share the dispatch lock.

provider seal, local fencing and product completion are different facts. native
truth commits before product work. the application can repeat product resolution
without repeating inference or an action. canonical context makes native history
disposable; restarting reasoning retains unresolved effect references.

private persistent codex hosts expose a uid-restricted socket and read-only cwd.
workers retain no account credentials. no remote HTTP shell relay or second
registry/executor exists. an owned handle's cancellation cannot stop its sibling.

the kernel adds no operational store. jarvis's real request/attempt/invocation
rows and nexus's existing journal/model-turn/tool-position rows own durability.
owner checks grant entry authority; original accepted work may still record its
factual result after entry authority is revoked.

[spec](../SPEC.md), [native contract](native-agent-spec.md) and
[host integration](host-integration.md) define the interfaces precisely.
