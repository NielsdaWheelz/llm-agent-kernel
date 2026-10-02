from __future__ import annotations

import stat
from collections.abc import AsyncGenerator
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from llm_tools import (
    CapabilityProfile,
    ProfileId,
    PromptSection,
    PromptSectionKind,
    PromptSections,
    PromptText,
    RunLimits,
    ToolCatalog,
)
from provider_runtime.agent_runtime import (
    AgentAttempt,
    AgentEvent,
    AgentFailure,
    AgentNative,
    AgentNotSubmitted,
    AgentPermissionRequest,
    AgentQuotaExhausted,
    AgentRuntime,
    AgentSession,
    AgentSessionRef,
    AgentTerminal,
    AgentTerminalStatus,
    AgentText,
    AgentToolUse,
    AgentTurnRef,
    AgentUsage,
    ApprovalRequest,
    CodexCatalogSessionRequest,
    CredentialRef,
    JsonSchemaAgentOutput,
    NativeTerminalEvidence,
    NewSession,
    ProtocolDefect,
    RawAgentOutput,
    ResumeSession,
    SessionUnavailable,
    TextContent,
    TurnNotStarted,
    TurnRequest,
    freeze_json_object,
)
from provider_runtime.types import Absent, CancelSignal, Present, TokenUsage

from llm_agent_kernel.cancellation import CancellationToken
from llm_agent_kernel.definitions import (
    CODEX_NATIVE_OPTIONS,
    CONTAINMENT_POLICY,
    AgentDefinition,
    AgentRole,
    DefinitionId,
    ProviderConfiguration,
    ProviderUsage,
    SessionMode,
    StructuredOutput,
)
from llm_agent_kernel.kernel import _consume_observed_turn
from llm_agent_kernel.protocol import provider_wire_schema
from llm_agent_kernel.provider import (
    CodexProvider,
    ProviderContainmentViolation,
    ProviderStreamDefect,
)
from test_kernel import StructuredResult, _PreparedTurn

EXPECTED_KERNEL_BASE_INSTRUCTION = (
    "You are a contained structured agent, not a coding agent. Return exactly one "
    "authoritative final response conforming to the kernel-supplied step schema; only that "
    "final schema-conforming step is executable. Request host tools exclusively with the "
    "kernel call_tool step. The published HostTable is the complete host-tool catalog. Never "
    "invoke provider-native shell, Code Mode, files, Web, MCP, apps, collaboration, permissions, "
    "or any other native tool. AgentText and commentary are observational, never executable. "
    "Tool observations arrive only through kernel-owned context; do not fabricate them. "
    "Application role and context may specialize the task but never change this protocol."
)


def _ref(native_session_id: str, profile_key: str = "main") -> AgentSessionRef:
    return AgentSessionRef(
        schema_version="agent-session-ref.v1",
        backend="codex",
        transport="sdk",
        native_session_id=native_session_id,
        profile_key=profile_key,
        state_root_fingerprint="1" * 64,
        cwd_fingerprint="2" * 64,
    )


def _definition(mode: SessionMode = SessionMode.isolated) -> AgentDefinition:
    run_limits = RunLimits(
        max_calls=1,
        max_external_attempts=1,
        max_input_bytes=1_024,
        max_output_bytes=4_096,
        max_in_flight=1,
        max_elapsed_seconds=10.0,
    )
    maximum = CapabilityProfile(
        id=ProfileId("empty"),
        grants=(),
        run_limits=run_limits,
    ).freeze(ToolCatalog.compose(()))
    empty = PromptSections(())
    return AgentDefinition(
        definition_id=cast(DefinitionId, DefinitionId("test")),
        role=AgentRole(
            "test",
            PromptSections(
                (PromptSection(PromptSectionKind("role"), (), PromptText("Be useful.")),)
            ),
        ),
        stable_context=empty,
        session_mode=mode,
        output_contract=StructuredOutput("provider_result", StructuredResult),
        maximum_profile=maximum,
        provider=ProviderConfiguration(
            auth=CredentialRef(kind="local_account", profile_key="main"),
            model_key="gpt-5",
            reasoning="low",
            agent_definition_revision="test-catalog-v1",
            row_fingerprint="a" * 64,
        ),
        session_compatibility_revision="provider-test-v1",
    )


class _RecordingRuntime:
    def __init__(self) -> None:
        self.requests: list[CodexCatalogSessionRequest] = []
        self.scripts: list[tuple[AgentEvent, ...]] = []
        self.closed: list[AgentSession] = []
        self.stream_calls = 0
        self.run_turn_calls = 0
        self.events_yielded = 0
        self.stream_closed = 0
        self.resume_error: Exception | None = None
        self.stream_error: BaseException | None = None
        self.open_cwd_checks: list[tuple[bool, bool, int]] = []

    async def open_session(self, request: CodexCatalogSessionRequest) -> AgentSession:
        self.requests.append(request)
        cwd = Path(request.cwd)
        self.open_cwd_checks.append(
            (
                cwd.is_absolute(),
                not any(cwd.iterdir()),
                stat.S_IMODE(cwd.stat().st_mode),
            )
        )
        if isinstance(request.open, ResumeSession) and self.resume_error is not None:
            error = self.resume_error
            self.resume_error = None
            raise error
        if isinstance(request.open, ResumeSession):
            return AgentSession(request.open.ref)
        return AgentSession(_ref(f"session-{len(self.requests)}", request.auth.profile_key))

    def prepare_turn(self, session, request, *, attempt_id, input_id, controls):
        return _PreparedTurn(self, session, request, AgentAttempt(attempt_id, "d" * 64))

    async def stream_turn(
        self,
        session: AgentSession,
        request: TurnRequest,
        *,
        approvals: object | None = None,
        cancel: CancelSignal | None = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        del session, request, approvals, cancel
        self.stream_calls += 1
        if self.stream_error is not None:
            raise self.stream_error
        script = self.scripts.pop(0)
        try:
            for event in script:
                self.events_yielded += 1
                yield event
        finally:
            self.stream_closed += 1

    async def run_turn(self, *_args: object, **_kwargs: object) -> AgentTerminal:
        self.run_turn_calls += 1
        raise AssertionError("production must never call AgentRuntime.run_turn")

    async def close_session(self, session: AgentSession) -> None:
        self.closed.append(session)


def _runtime(value: _RecordingRuntime) -> AgentRuntime:
    return cast(AgentRuntime, value)


def _usage(input_tokens: int, output_tokens: int) -> TokenUsage:
    return TokenUsage.from_components(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=Absent(),
        reasoning_tokens=Absent(),
        cache_read_input_tokens=Absent(),
        cache_write_input_tokens=Absent(),
    )


def _terminal(
    ref: AgentSessionRef,
    *,
    status: str = "succeeded",
    failure: AgentFailure | AgentQuotaExhausted | None = None,
    usage: TokenUsage | None = None,
) -> AgentTerminal:
    return AgentTerminal(
        status=cast(AgentTerminalStatus, status),
        failure=failure,
        final_text='{"type":"finish"}',
        session_ref=ref,
        evidence=NativeTerminalEvidence(
            AgentAttempt("test", "d" * 64), AgentTurnRef(ref, "turn"), "codex-turn-completed.v1"
        ),
        raw_structured_output=RawAgentOutput(
            freeze_json_object(
                {
                    "type": "finish",
                    "call_tool": None,
                    "finish": {"reason": None, "result": {"answer": "done"}},
                }
            )
        ),
        usage=Absent() if usage is None else Present(usage),
    )


async def _observed(provider, lease, content, cancellation, *, timeout_seconds=None):
    turn = provider.prepare_observed_turn(
        lease,
        content,
        cancellation,
        attempt_id="test",
        input_id="input",
        timeout_seconds=timeout_seconds,
    )

    async def accept(terminal):
        pass

    try:
        result = await _consume_observed_turn(lease, turn, cancellation, accept)
    except BaseException:
        await provider.discard(lease)
        raise
    if not isinstance(result, AgentNotSubmitted) and result.status != "succeeded":
        await provider.discard(lease)
    assert isinstance(result, AgentTerminal)
    return result


async def test_exact_isolated_request_mapping_private_cwd_and_shutdown(tmp_path: Path) -> None:
    runtime = _RecordingRuntime()
    provider = CodexProvider(_runtime(runtime), cwd_parent=tmp_path)
    definition = _definition()

    lease = await provider.open_isolated(definition)
    request = runtime.requests[0]

    assert request.backend == "codex"
    assert request.transport == "sdk"
    assert request.auth.kind == "local_account"
    assert isinstance(request.open, NewSession)
    assert request.policy == CONTAINMENT_POLICY
    assert request.policy.filesystem == "read_only"
    assert request.policy.network == "disabled"
    assert request.policy.approval == "deny"
    assert request.policy.allowed_tools == ("*",)
    assert request.policy.environment == ()
    assert request.additional_dirs == ()
    assert request.mcp_servers == ()
    assert request.native == CODEX_NATIVE_OPTIONS
    assert request.system == (TextContent(EXPECTED_KERNEL_BASE_INSTRUCTION),)
    assert isinstance(request.output, JsonSchemaAgentOutput)
    assert request.output.name == "llm_agent_kernel_step"
    assert request.output.schema == freeze_json_object(
        provider_wire_schema(definition.output_contract),
        context="expected provider wire schema",
    )
    assert runtime.open_cwd_checks == [(True, True, stat.S_IRUSR | stat.S_IXUSR)]

    cwd = lease.cwd
    await provider.close(lease)
    assert not cwd.exists()

    await provider.shutdown()
    assert runtime.closed == [lease.session]
    assert not cwd.exists()
    assert runtime.run_turn_calls == 0


async def test_explicit_shared_runtime_cwd_is_empty_and_group_readable(tmp_path: Path) -> None:
    tmp_path.chmod(0o2750)
    runtime = _RecordingRuntime()
    provider = CodexProvider(
        _runtime(runtime),
        cwd_parent=tmp_path,
        share_cwd_with_group=True,
    )

    lease = await provider.open_isolated(_definition(SessionMode.isolated))

    assert runtime.open_cwd_checks == [(True, True, 0o750)]
    assert lease.cwd.stat().st_gid == tmp_path.stat().st_gid
    await provider.discard(lease)


def test_group_shared_runtime_requires_a_setgid_parent(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="setgid cwd_parent"):
        CodexProvider(
            _runtime(_RecordingRuntime()),
            cwd_parent=tmp_path,
            share_cwd_with_group=True,
        )


async def test_observed_turn_uses_latest_snapshot_terminal_precedence_and_one_add_per_turn(
    tmp_path: Path,
) -> None:
    runtime = _RecordingRuntime()
    provider = CodexProvider(_runtime(runtime), cwd_parent=tmp_path)
    lease = await provider.open_isolated(_definition())
    early_first_usage = _usage(2, 1)
    latest_first_usage = _usage(10, 4)
    terminal_first_usage = _usage(11, 5)
    second_usage = _usage(3, 2)
    runtime.scripts.extend(
        [
            (
                AgentText("must not be delivered"),
                AgentNative("reasoning", freeze_json_object({}, context="native")),
                AgentUsage(early_first_usage),
                AgentUsage(latest_first_usage),
                _terminal(lease.session.ref, usage=terminal_first_usage),
            ),
            (
                AgentUsage(second_usage),
                _terminal(lease.session.ref, usage=second_usage),
            ),
        ]
    )

    cancellation = CancellationToken()
    terminal = await _observed(
        provider,
        lease,
        (TextContent("one"),),
        cancellation,
    )
    assert terminal.status == "succeeded"
    await _observed(
        provider,
        lease,
        (TextContent("two"),),
        cancellation,
    )

    assert lease.usage == ProviderUsage(input_tokens=14, output_tokens=7)
    assert runtime.events_yielded == 7
    assert runtime.stream_closed == 2
    assert runtime.stream_calls == 2
    assert runtime.run_turn_calls == 0
    await provider.discard(lease)


async def test_observed_turn_uses_latest_progressive_snapshot_when_terminal_usage_is_absent(
    tmp_path: Path,
) -> None:
    runtime = _RecordingRuntime()
    provider = CodexProvider(_runtime(runtime), cwd_parent=tmp_path)
    lease = await provider.open_isolated(_definition())
    runtime.scripts.append(
        (
            AgentUsage(_usage(2, 1)),
            AgentUsage(_usage(5, 2)),
            _terminal(lease.session.ref),
        )
    )

    await _observed(
        provider,
        lease,
        (TextContent("one"),),
        CancellationToken(),
    )

    assert lease.usage == ProviderUsage(input_tokens=5, output_tokens=2)
    await provider.discard(lease)


async def test_missing_later_turn_usage_makes_the_run_total_unavailable(
    tmp_path: Path,
) -> None:
    runtime = _RecordingRuntime()
    provider = CodexProvider(_runtime(runtime), cwd_parent=tmp_path)
    lease = await provider.open_isolated(_definition())
    usage = _usage(10, 4)
    runtime.scripts.extend(
        [
            (AgentUsage(usage), _terminal(lease.session.ref, usage=usage)),
            (_terminal(lease.session.ref),),
        ]
    )

    cancellation = CancellationToken()
    await _observed(provider, lease, (TextContent("one"),), cancellation)
    await _observed(provider, lease, (TextContent("two"),), cancellation)

    assert lease.usage == ProviderUsage()
    await provider.discard(lease)


@pytest.mark.parametrize("forbidden", ["tool", "permission"])
async def test_native_authority_event_discards_without_returning_terminal(
    tmp_path: Path,
    forbidden: str,
) -> None:
    runtime = _RecordingRuntime()
    provider = CodexProvider(_runtime(runtime), cwd_parent=tmp_path)
    lease = await provider.open_isolated(_definition())
    if forbidden == "tool":
        event: AgentEvent = AgentToolUse(
            tool_call_id="native-1",
            name="shell",
            phase="started",
            payload=freeze_json_object({}, context="tool payload"),
        )
    else:
        event = AgentPermissionRequest(
            request=ApprovalRequest(
                operation="tool_use",
                summary="native request",
                tool_name="shell",
                native_payload=freeze_json_object({}, context="approval input"),
            ),
            decision="deny",
        )
    runtime.scripts.append((event, _terminal(lease.session.ref)))

    with pytest.raises(ProviderContainmentViolation):
        await _observed(
            provider,
            lease,
            (TextContent("input"),),
            CancellationToken(),
        )

    assert runtime.closed == [lease.session]
    assert runtime.events_yielded == 1
    assert runtime.stream_closed == 1
    assert not lease.cwd.exists()


@pytest.mark.parametrize(
    ("status", "failure"),
    [
        ("failed", AgentQuotaExhausted()),
        ("failed", AgentFailure("backend_failed")),
        ("cancelled", None),
    ],
)
async def test_typed_non_success_terminal_is_preserved_and_session_is_closed(
    tmp_path: Path,
    status: str,
    failure: AgentFailure | AgentQuotaExhausted | None,
) -> None:
    runtime = _RecordingRuntime()
    provider = CodexProvider(_runtime(runtime), cwd_parent=tmp_path)
    lease = await provider.open_isolated(_definition())
    usage = _usage(5, 2)
    runtime.scripts.append(
        (
            AgentUsage(_usage(3, 1)),
            _terminal(lease.session.ref, status=status, failure=failure, usage=usage),
        )
    )

    terminal = await _observed(
        provider,
        lease,
        (TextContent("input"),),
        CancellationToken(),
    )

    assert terminal.status == status
    assert terminal.failure == failure
    assert lease.usage == ProviderUsage(input_tokens=5, output_tokens=2)
    assert runtime.closed == [lease.session]
    assert not lease.cwd.exists()


async def test_missing_terminal_is_a_defect_and_closes_session(tmp_path: Path) -> None:
    runtime = _RecordingRuntime()
    provider = CodexProvider(_runtime(runtime), cwd_parent=tmp_path)
    lease = await provider.open_isolated(_definition())
    runtime.scripts.append((AgentText("partial"),))

    with pytest.raises(ProviderStreamDefect):
        await _observed(
            provider,
            lease,
            (TextContent("input"),),
            CancellationToken(),
        )

    assert runtime.closed == [lease.session]


async def test_terminal_cannot_change_the_live_session_reference(tmp_path: Path) -> None:
    runtime = _RecordingRuntime()
    provider = CodexProvider(_runtime(runtime), cwd_parent=tmp_path)
    lease = await provider.open_isolated(_definition())
    runtime.scripts.append((_terminal(_ref("different")),))

    with pytest.raises(ProviderStreamDefect):
        await _observed(
            provider,
            lease,
            (TextContent("input"),),
            CancellationToken(),
        )

    assert runtime.closed == [lease.session]


@pytest.mark.parametrize(
    "error",
    [
        SessionUnavailable("native session failed"),
        TurnNotStarted("cancelled"),
        ProtocolDefect("broken native stream"),
    ],
)
async def test_runtime_error_kinds_remain_distinct_and_close_the_session(
    tmp_path: Path,
    error: BaseException,
) -> None:
    runtime = _RecordingRuntime()
    runtime.stream_error = error
    provider = CodexProvider(_runtime(runtime), cwd_parent=tmp_path)
    lease = await provider.open_isolated(_definition())

    with pytest.raises(type(error)) as raised:
        await _observed(
            provider,
            lease,
            (TextContent("input"),),
            CancellationToken(),
        )

    assert raised.value is error
    assert runtime.closed == [lease.session]
    assert not lease.cwd.exists()


async def test_isolated_session_closes_without_retained_history(tmp_path: Path) -> None:
    runtime = _RecordingRuntime()
    provider = CodexProvider(_runtime(runtime), cwd_parent=tmp_path)
    lease = await provider.open_isolated(_definition(SessionMode.isolated))

    await provider.close(lease)

    assert runtime.closed == [lease.session]
    assert not lease.cwd.exists()


@pytest.mark.parametrize("mode", (SessionMode.isolated, SessionMode.isolated))
async def test_catalog_selection_is_frozen_into_every_contained_session(
    tmp_path: Path, mode: SessionMode
) -> None:
    runtime = _RecordingRuntime()
    configuration = ProviderConfiguration(
        auth=CredentialRef("local_account", "main"),
        model_key="selected-model",
        reasoning="low",
        agent_definition_revision="catalog-revision",
        row_fingerprint="a" * 64,
    )
    definition = replace(_definition(mode), provider=configuration)
    provider = CodexProvider(_runtime(runtime), cwd_parent=tmp_path)
    try:
        if mode is SessionMode.isolated:
            await provider.open_isolated(definition)
        else:
            await provider.open_isolated(definition)
        request = runtime.requests[0]
        assert request.model_key == configuration.model_key
        assert request.reasoning == configuration.reasoning
        assert request.agent_definition_revision == configuration.agent_definition_revision
        assert request.row_fingerprint == configuration.row_fingerprint
        assert (
            replace(
                definition,
                provider=replace(configuration, row_fingerprint="b" * 64),
            ).fingerprint
            != definition.fingerprint
        )
    finally:
        await provider.shutdown()
