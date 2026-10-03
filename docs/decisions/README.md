# Architecture decisions

| ADR | Decision | Status |
| --- | --- | --- |
| [0001](0001-library-boundary.md) | Create a narrow Python agent kernel | Accepted |
| [0002](0002-event-drain-kernel.md) | Use host-owned claims, polling, settlement, and admission | Accepted |
| [0003](0003-provider-and-tool-ownership.md) | Preserve real provider-runtime and llm-tools ownership | Accepted |
| [0004](0004-defer-program-agents-and-delegation.md) | Defer program agents, discovery, and delegation | Accepted |
| [0005](0005-codex-agent-lane-and-serial-steps.md) | Use the Codex AgentRuntime lane and one serial tool step | Accepted |
| [0006](0006-bound-work-across-runs.md) | Bound work across runs | superseded for native main by 0010 |
| [0007](0007-configuration-defect-parking.md) | Park configuration defects atomically | Accepted |
| [0008](0008-shared-generation-orchestration.md) | Share ordered generation choreography with Nexus | Accepted |
| [0009](0009-durable-paid-decisions.md) | Retain original paid decisions and uncertainty | Accepted |
| [0010](0010-native-agent-supervision.md) | supervise native agents with explicit submission and invocation evidence | accepted; implemented, see current evidence |
| [0011](0011-contained-native-host.md) | require a restricted stock host and separate jarvis endpoint | accepted; installed qualification in progress |
