# llm-agent-kernel

portable native agent supervision for jarvis and nexus. the kernel shares control,
callback ordering and truthful recovery; applications keep canonical context,
effects, consent and publication.

`run_native` supervises one exact native turn with declared host callbacks.
`run_one_shot` serves retained isolated read-only gate/context/memory roles.
`generation.run_generation` serves nexus's raw API lane. the conversational
structured-step loop and shell tool relay are removed.

install exact dependencies from `uv.lock` with `uv sync --frozen`.
run `uv run --frozen ruff format --check .`, `uv run --frozen ruff check .`,
`uv run --frozen pyright`, and `uv run --frozen pytest` for applicable conformance.
actual installed/live qualification is separately recorded in
[implementation evidence](docs/native-agent-evidence.md).

[specification](SPEC.md) owns the public contract;
[native detail](docs/native-agent-spec.md) owns behavior and schemas;
[architecture](docs/architecture.md) explains module ownership;
[host integration](docs/host-integration.md) explains durable application ports;
[delivery plan](docs/native-agent-plan.md) owns slices and temporary proof;
[metadata handoff](docs/integrations/nexus-metadata.md) names integration pins/status;
[decisions](docs/decisions/README.md) retains historical reasoning.
