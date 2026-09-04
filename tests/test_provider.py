from __future__ import annotations

import asyncio
import stat
from collections.abc import AsyncGenerator
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
    AgentEvent,
    AgentFailure,
    AgentNative,
    AgentPermissionRequest,
    AgentQuotaExhausted,
    AgentRuntime,
    AgentSession,
    AgentSessionRef,
    AgentSessionRequest,
    AgentTerminal,
    AgentTerminalStatus,
    AgentText,
    AgentToolUse,
    AgentUsage,
    ApprovalRequest,
    CredentialRef,
    JsonSchemaAgentOutput,
    NewSession,
    ProtocolDefect,
    ResumeSession,
    SessionUnavailable,
    TextContent,
    TurnNotStarted,
    TurnRequest,
    freeze_json_object,
)
from provider_runtime.types import Absent, CancelSignal, Present, TokenUsage

from llm_agent_kernel.definitions import (
    CODEX_NATIVE_OPTIONS,
    CONTAINMENT_POLICY,
    AgentDefinition,
    AgentRole,
    ConversationalOutput,
    DefinitionId,
    ProviderConfiguration,
    ProviderUsage,
    SessionMode,
)
from llm_agent_kernel.protocol import provider_wire_schema
from llm_agent_kernel.provider import (
    CodexProvider,
    ProviderContainmentViolation,
    ProviderStreamDefect,
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


def _definition(mode: SessionMode = SessionMode.continuing) -> AgentDefinition:
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
        output_contract=ConversationalOutput(),
        maximum_profile=maximum,
        provider=ProviderConfiguration(
            auth=CredentialRef(kind="local_account", profile_key="main"),
            model="gpt-5",
        ),
        session_compatibility_revision="provider-test-v1",
    )


class _RecordingRuntime:
    def __init__(self) -> None:
        self.requests: list[AgentSessionRequest] = []
        self.scripts: list[tuple[AgentEvent, ...]] = []
        self.closed: list[AgentSession] = []
        self.stream_calls = 0
        self.run_turn_calls = 0
        self.events_yielded = 0
        self.stream_closed = 0
        self.resume_error: Exception | None = None
        self.stream_error: BaseException | None = None
        self.open_cwd_checks: list[tuple[bool, bool, int]] = []

    async def open_session(self, request: AgentSessionRequest) -> AgentSession:
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
        structured_output=freeze_json_object({"type": "finish"}, context="test structured output"),
        usage=Absent() if usage is None else Present(usage),
    )


async def test_exact_request_mapping_private_cwd_cache_and_shutdown(tmp_path: Path) -> None:
    runtime = _RecordingRuntime()
    provider = CodexProvider(_runtime(runtime), cwd_parent=tmp_path)
    definition = _definition()

    lease = await provider.acquire_continuing(definition, None)
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
    assert isinstance(request.output, JsonSchemaAgentOutput)
    assert request.output.name == "llm_agent_kernel_step"
    assert request.output.schema == freeze_json_object(
        provider_wire_schema(definition.output_contract),
        context="expected provider wire schema",
    )
    assert runtime.open_cwd_checks == [(True, True, stat.S_IRUSR | stat.S_IXUSR)]

    cwd = lease.cwd
    ref = lease.session.ref
    await provider.release(lease)
    assert cwd.exists()
    cached = await provider.acquire_continuing(definition, ref)
    assert cached.session is lease.session
    assert len(runtime.requests) == 1
    await provider.release(cached)

    await provider.shutdown()
    assert runtime.closed == [lease.session]
    assert not cwd.exists()
    assert runtime.run_turn_calls == 0


async def test_observed_turn_uses_latest_snapshot_terminal_precedence_and_one_add_per_turn(
    tmp_path: Path,
) -> None:
    runtime = _RecordingRuntime()
    provider = CodexProvider(_runtime(runtime), cwd_parent=tmp_path)
    lease = await provider.acquire_continuing(_definition(), None)
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

    cancellation = cast(CancelSignal, asyncio.Event())
    terminal = await provider.run_observed_turn(
        lease,
        (TextContent("one"),),
        cancellation,
    )
    assert terminal.status == "succeeded"
    await provider.run_observed_turn(
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
    lease = await provider.acquire_continuing(_definition(), None)
    runtime.scripts.append(
        (
            AgentUsage(_usage(2, 1)),
            AgentUsage(_usage(5, 2)),
            _terminal(lease.session.ref),
        )
    )

    await provider.run_observed_turn(
        lease,
        (TextContent("one"),),
        cast(CancelSignal, asyncio.Event()),
    )

    assert lease.usage == ProviderUsage(input_tokens=5, output_tokens=2)
    await provider.discard(lease)


async def test_resumed_session_charges_only_invocation_local_usage(tmp_path: Path) -> None:
    runtime = _RecordingRuntime()
    provider = CodexProvider(_runtime(runtime), cwd_parent=tmp_path)
    saved = _ref("saved")
    lease = await provider.acquire_continuing(_definition(), saved)
    local_usage = _usage(7, 3)
    runtime.scripts.append((AgentUsage(local_usage), _terminal(saved, usage=local_usage)))

    await provider.run_observed_turn(
        lease,
        (TextContent("continued"),),
        cast(CancelSignal, asyncio.Event()),
    )

    assert isinstance(runtime.requests[0].open, ResumeSession)
    assert lease.usage == ProviderUsage(input_tokens=7, output_tokens=3)
    await provider.discard(lease)


async def test_missing_later_turn_usage_makes_the_run_total_unavailable(
    tmp_path: Path,
) -> None:
    runtime = _RecordingRuntime()
    provider = CodexProvider(_runtime(runtime), cwd_parent=tmp_path)
    lease = await provider.acquire_continuing(_definition(), None)
    usage = _usage(10, 4)
    runtime.scripts.extend(
        [
            (AgentUsage(usage), _terminal(lease.session.ref, usage=usage)),
            (_terminal(lease.session.ref),),
        ]
    )

    cancellation = cast(CancelSignal, asyncio.Event())
    await provider.run_observed_turn(lease, (TextContent("one"),), cancellation)
    await provider.run_observed_turn(lease, (TextContent("two"),), cancellation)

    assert lease.usage == ProviderUsage()
    await provider.discard(lease)


@pytest.mark.parametrize("forbidden", ["tool", "permission"])
async def test_native_authority_event_discards_without_returning_terminal(
    tmp_path: Path,
    forbidden: str,
) -> None:
    runtime = _RecordingRuntime()
    provider = CodexProvider(_runtime(runtime), cwd_parent=tmp_path)
    lease = await provider.acquire_continuing(_definition(), None)
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
        await provider.run_observed_turn(
            lease,
            (TextContent("input"),),
            cast(CancelSignal, asyncio.Event()),
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
    lease = await provider.acquire_continuing(_definition(), None)
    usage = _usage(5, 2)
    runtime.scripts.append(
        (
            AgentUsage(_usage(3, 1)),
            _terminal(lease.session.ref, status=status, failure=failure, usage=usage),
        )
    )

    terminal = await provider.run_observed_turn(
        lease,
        (TextContent("input"),),
        cast(CancelSignal, asyncio.Event()),
    )

    assert terminal.status == status
    assert terminal.failure == failure
    assert lease.usage == ProviderUsage(input_tokens=5, output_tokens=2)
    assert runtime.closed == [lease.session]
    assert not lease.cwd.exists()


async def test_missing_terminal_is_a_defect_and_closes_session(tmp_path: Path) -> None:
    runtime = _RecordingRuntime()
    provider = CodexProvider(_runtime(runtime), cwd_parent=tmp_path)
    lease = await provider.acquire_continuing(_definition(), None)
    runtime.scripts.append((AgentText("partial"),))

    with pytest.raises(ProviderStreamDefect):
        await provider.run_observed_turn(
            lease,
            (TextContent("input"),),
            cast(CancelSignal, asyncio.Event()),
        )

    assert runtime.closed == [lease.session]


async def test_terminal_cannot_change_the_live_session_reference(tmp_path: Path) -> None:
    runtime = _RecordingRuntime()
    provider = CodexProvider(_runtime(runtime), cwd_parent=tmp_path)
    lease = await provider.acquire_continuing(_definition(), None)
    runtime.scripts.append((_terminal(_ref("different")),))

    with pytest.raises(ProviderStreamDefect):
        await provider.run_observed_turn(
            lease,
            (TextContent("input"),),
            cast(CancelSignal, asyncio.Event()),
        )

    assert runtime.closed == [lease.session]


async def test_resume_incompatibility_gets_exactly_one_cold_open(tmp_path: Path) -> None:
    runtime = _RecordingRuntime()
    runtime.resume_error = SessionUnavailable("native session is unavailable")
    provider = CodexProvider(_runtime(runtime), cwd_parent=tmp_path)
    saved = _ref("saved")

    lease = await provider.acquire_continuing(_definition(), saved)

    assert len(runtime.requests) == 2
    assert isinstance(runtime.requests[0].open, ResumeSession)
    assert isinstance(runtime.requests[1].open, NewSession)
    assert lease.cold_bootstrap is True
    assert lease.fallback_used is True
    assert not Path(runtime.requests[0].cwd).exists()
    await provider.discard(lease)


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
    lease = await provider.acquire_continuing(_definition(), None)

    with pytest.raises(type(error)) as raised:
        await provider.run_observed_turn(
            lease,
            (TextContent("input"),),
            cast(CancelSignal, asyncio.Event()),
        )

    assert raised.value is error
    assert runtime.closed == [lease.session]
    assert not lease.cwd.exists()


async def test_isolated_session_is_never_cached(tmp_path: Path) -> None:
    runtime = _RecordingRuntime()
    provider = CodexProvider(_runtime(runtime), cwd_parent=tmp_path)
    lease = await provider.open_isolated(_definition(SessionMode.isolated))

    await provider.release(lease)

    assert runtime.closed == [lease.session]
    assert not lease.cwd.exists()
