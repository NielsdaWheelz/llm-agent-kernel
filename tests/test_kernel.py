from __future__ import annotations

import json
from collections import deque
from collections.abc import AsyncGenerator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from llm_tools import (
    Available,
    BudgetState,
    CapabilityProfile,
    HostTable,
    NoDeclaredError,
    PolicyEpoch,
    ProfileId,
    PromptDocument,
    PromptSection,
    PromptSectionKind,
    PromptSections,
    PromptText,
    ReplayPolicy,
    RunLimits,
    ToolBinding,
    ToolCatalog,
    ToolEffect,
    ToolFamily,
    ToolGrant,
    ToolId,
    ToolLimits,
    ToolPlan,
    ToolSpec,
)
from provider_runtime.agent_runtime import (
    AgentEvent,
    AgentFailure,
    AgentQuotaExhausted,
    AgentRuntime,
    AgentSession,
    AgentSessionRef,
    AgentSessionRequest,
    AgentTerminal,
    AgentText,
    AgentToolUse,
    AgentUsage,
    CredentialRef,
    FrozenJsonDict,
    ResumeSession,
    TextContent,
    TurnNotStarted,
    TurnRequest,
    freeze_json_object,
)
from provider_runtime.types import Absent, CancelSignal, Present, TokenUsage
from pydantic import BaseModel, ConfigDict

from llm_agent_kernel.cancellation import CancellationToken
from llm_agent_kernel.coordination import (
    AdmissionDeferred,
    AdmissionGranted,
    AdmissionRequest,
    AdmissionStateDefect,
    AdmissionToken,
    AdmissionUsage,
    CheckpointStateDefect,
    ClaimAcquired,
    ClaimNoWork,
    SettleMoreInput,
    StaleSessionRef,
    ToolDispatchDefect,
)
from llm_agent_kernel.definitions import (
    AgentDefinition,
    AgentRole,
    Checkpoint,
    ClaimId,
    ConversationalOutput,
    ConversationConclusion,
    DefinitionId,
    DispatchCompleted,
    DispatchLineage,
    DispatchSuspended,
    HostInput,
    HostRef,
    InputClaim,
    InputId,
    KernelLimits,
    OneShotCompleted,
    OwnerToken,
    ProviderConfiguration,
    RunId,
    SessionMode,
    StoppedConclusion,
    StopReason,
    StructuredOutput,
    SuspensionConclusion,
    ThreadId,
    ThreadStopKind,
    WaitingFor,
)
from llm_agent_kernel.events import (
    DiagnosticKind,
    DiagnosticRecord,
    DiagnosticTranscript,
    EventKind,
    RedactedText,
)
from llm_agent_kernel.fakes import (
    InMemoryAdmissionPort,
    InMemoryInputCheckpointPort,
    InMemorySessionRefPort,
    RecordingEventSink,
    ScriptedToolDispatchPort,
    StaticContextSource,
)
from llm_agent_kernel.kernel import KernelConfigurationDefect, run_one_shot, run_thread
from llm_agent_kernel.provider import CodexProvider
from llm_agent_kernel.sessions import SessionCoordinator


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str


class ToolSuccess(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str


class StructuredResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str


async def _must_not_execute(value: object, context: object) -> object:
    raise AssertionError(f"host dispatcher owns execution: {value!r}, {context!r}")


def _sections(text: str = "context") -> PromptSections:
    return PromptSections((PromptSection(PromptSectionKind("context"), (), PromptText(text)),))


def _authority(
    effect: ToolEffect | None = None,
) -> tuple[Any, Any, ToolBinding[Any, Any, Any] | None]:
    run_limits = RunLimits(8, 8, 32_768, 32_768, 1, 30.0)
    if effect is None:
        catalog = ToolCatalog.compose(())
        profile = CapabilityProfile(ProfileId("empty"), (), run_limits).freeze(catalog)
        return profile, ToolPlan(profile.id, HostTable()).freeze(catalog, profile), None
    spec = ToolSpec(
        id=ToolId("test.observe"),
        summary="Observe a value",
        documentation=PromptDocument("Return one bounded observation."),
        input_type=ToolInput,
        success_type=ToolSuccess,
        error_type=NoDeclaredError,
        effect=effect,
        limits=ToolLimits(1_024, 4_096, 1, 5.0),
    )
    binding = ToolBinding(
        spec=spec,
        execute=Available(_must_not_execute),
        replay_policy=ReplayPolicy.ReDispatchable,
        implementation_revision="observe-v1",
        policy_epoch=PolicyEpoch("v1"),
        policy_inputs={},
    )
    catalog = ToolCatalog.compose((ToolFamily("test", (spec,), (binding,)),))
    profile = CapabilityProfile(
        ProfileId("maximum"),
        (ToolGrant(spec.id, None),),
        run_limits,
    ).freeze(catalog)
    plan = ToolPlan(profile.id, HostTable()).freeze(catalog, profile)
    return profile, plan, cast(ToolBinding[Any, Any, Any], binding)


def _definition(
    *,
    mode: SessionMode = SessionMode.continuing,
    structured: bool = False,
    effect: ToolEffect | None = None,
    limits: KernelLimits | None = None,
) -> tuple[AgentDefinition, Any, ToolBinding[Any, Any, Any] | None]:
    maximum, plan, binding = _authority(effect)
    return (
        AgentDefinition(
            DefinitionId("assistant"),
            AgentRole("assistant", _sections("role")),
            _sections("stable"),
            mode,
            StructuredOutput("answer", StructuredResult) if structured else ConversationalOutput(),
            maximum,
            ProviderConfiguration(
                CredentialRef("local_account", "test"),
                "gpt-5",
            ),
            "kernel-test-v1",
            limits or KernelLimits(),
        ),
        plan,
        binding,
    )


def _input(name: str = "input-1", text: str = "hello") -> HostInput:
    return HostInput(InputId(name), _sections(text), datetime.now(UTC))


def _claim(plan: Any, *, attempt: int = 1) -> InputClaim:
    return InputClaim(
        ClaimId("claim-1"),
        (_input(),),
        Checkpoint("checkpoint-1"),
        datetime.now(UTC),
        plan,
        attempt,
    )


def _ref(name: str = "session-1") -> AgentSessionRef:
    return AgentSessionRef(
        "agent-session-ref.v1",
        "codex",
        "sdk",
        name,
        "test",
        "1" * 64,
        "2" * 64,
    )


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
    value: dict[str, object],
    ref: AgentSessionRef | None = None,
    usage: TokenUsage | None = None,
) -> AgentTerminal:
    return AgentTerminal(
        status="succeeded",
        failure=None,
        final_text="not a trusted projection",
        session_ref=ref or _ref(),
        structured_output=freeze_json_object(_wire_step(value)),
        usage=Absent() if usage is None else Present(usage),
    )


def _wire_step(value: dict[str, object]) -> dict[str, object]:
    step_type = value.get("type")
    wire: dict[str, object] = {
        "type": step_type,
        "say": None,
        "call_tool": None,
        "finish": None,
    }
    if step_type == "say":
        wire["say"] = {key: child for key, child in value.items() if key != "type"}
    elif step_type == "call_tool":
        payload = {key: child for key, child in value.items() if key != "type"}
        if "arguments" in payload:
            payload["arguments"] = json.dumps(payload["arguments"], separators=(",", ":"))
        wire["call_tool"] = payload
    elif step_type == "finish":
        payload = {key: child for key, child in value.items() if key != "type"}
        payload.setdefault("reason", None)
        wire["finish"] = payload
    return wire


def _failed_terminal(
    failure: AgentFailure | AgentQuotaExhausted,
    ref: AgentSessionRef | None = None,
    usage: TokenUsage | None = None,
) -> AgentTerminal:
    return AgentTerminal(
        status="failed",
        failure=failure,
        final_text="",
        session_ref=ref or _ref(),
        structured_output=None,
        usage=Absent() if usage is None else Present(usage),
    )


class _Runtime:
    def __init__(
        self,
        scripts: list[tuple[AgentEvent, ...]],
        *,
        stream_error: BaseException | None = None,
    ) -> None:
        self.scripts = deque(scripts)
        self.stream_error = stream_error
        self.opens: list[AgentSessionRequest] = []
        self.turns: list[TurnRequest] = []
        self.closed: list[AgentSession] = []
        self.run_turn_calls = 0

    async def open_session(self, request: AgentSessionRequest) -> AgentSession:
        self.opens.append(request)
        ref = request.open.ref if isinstance(request.open, ResumeSession) else None
        return AgentSession(ref or _ref(f"session-{len(self.opens)}"))

    async def stream_turn(
        self,
        session: AgentSession,
        request: TurnRequest,
        *,
        approvals: object | None = None,
        cancel: CancelSignal | None = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        del session, approvals, cancel
        self.turns.append(request)
        if self.stream_error is not None:
            raise self.stream_error
        for event in self.scripts.popleft():
            yield event

    async def run_turn(self, *_args: object, **_kwargs: object) -> AgentTerminal:
        self.run_turn_calls += 1
        raise AssertionError("the kernel must consume stream_turn")

    async def close_session(self, session: AgentSession) -> None:
        self.closed.append(session)


class _CancellingRuntime(_Runtime):
    def __init__(
        self,
        scripts: list[tuple[AgentEvent, ...]],
        cancellation: CancellationToken,
    ) -> None:
        super().__init__(scripts)
        self.cancellation = cancellation

    async def stream_turn(
        self,
        session: AgentSession,
        request: TurnRequest,
        *,
        approvals: object | None = None,
        cancel: CancelSignal | None = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        del session, approvals, cancel
        self.turns.append(request)
        self.cancellation.cancel()
        for event in self.scripts.popleft():
            yield event


class _Budgets:
    def __init__(self, limits: RunLimits) -> None:
        self.limits = limits

    @property
    def remaining_elapsed_seconds(self) -> float:
        return 30.0

    async def reserve(self, *_args: object, **_kwargs: object) -> bool:
        raise AssertionError("scripted dispatch does not mutate tool budgets")

    async def settle(self, *_args: object, **_kwargs: object) -> None:
        raise AssertionError("scripted dispatch does not mutate tool budgets")


class _BudgetFactory:
    def __init__(self, limits: RunLimits | None = None) -> None:
        self.limits = limits
        self.plans: list[Any] = []

    def create(self, plan: Any) -> BudgetState:
        self.plans.append(plan)
        return cast(BudgetState, _Budgets(self.limits or plan.profile.run_limits))


def _budget_factory(limits: RunLimits | None = None) -> _BudgetFactory:
    return _BudgetFactory(limits)


class _FailingSettlement(InMemoryInputCheckpointPort):
    async def settle(self, *args: Any, **kwargs: Any):
        del args, kwargs
        raise CheckpointStateDefect("injected settlement failure")


class _FailingDispatch(ScriptedToolDispatchPort):
    async def dispatch(self, **kwargs: Any):
        del kwargs
        raise ToolDispatchDefect("injected dispatch failure")


class _FailingUsageSettlement(InMemoryAdmissionPort):
    async def settle(self, *args: Any, **kwargs: Any) -> None:
        await super().settle(*args, **kwargs)
        raise AdmissionStateDefect("injected usage settlement failure")


class _FailingClaim(InMemoryInputCheckpointPort):
    async def claim(self, thread_id: ThreadId, owner_token: OwnerToken):
        del thread_id, owner_token
        raise CheckpointStateDefect("injected claim failure")


class _FailingRelease(InMemoryInputCheckpointPort):
    async def release(self, *args: Any, **kwargs: Any):
        del args, kwargs
        raise CheckpointStateDefect("injected release failure")


class _FailingReservation(InMemoryAdmissionPort):
    async def reserve(self, request: AdmissionRequest):
        del request
        raise AdmissionStateDefect("injected reservation failure")


class _ForgedChildAdmission(InMemoryAdmissionPort):
    def __init__(self) -> None:
        super().__init__()
        self.settled = False

    async def reserve(self, request: AdmissionRequest):
        return AdmissionGranted(
            AdmissionToken(
                request.run_id,
                "wrong-window",
                "wrong-epoch",
                request.maximum_turns,
                request.maximum_input_tokens,
                request.maximum_output_tokens,
                True,
            )
        )

    async def settle(self, token: AdmissionToken, usage: AdmissionUsage) -> None:
        del token, usage
        self.settled = True


async def _thread(
    tmp_path: Path,
    definition: AgentDefinition,
    claim: InputClaim,
    runtime: _Runtime,
    checkpoints: InMemoryInputCheckpointPort,
    dispatch: ScriptedToolDispatchPort | None = None,
    admission: InMemoryAdmissionPort | None = None,
    references: InMemorySessionRefPort | None = None,
    cancellation: CancellationToken | None = None,
    diagnostics: DiagnosticTranscript | None = None,
    event_sink: RecordingEventSink | None = None,
    budget_factory: Any | None = None,
    context_source: StaticContextSource | None = None,
):
    provider = CodexProvider(cast(AgentRuntime, runtime), cwd_parent=tmp_path)
    refs = references or InMemorySessionRefPort()
    try:
        outcome = await run_thread(
            run_id=RunId("run-1"),
            thread_id=ThreadId("thread-1"),
            owner_token=OwnerToken("owner-1"),
            definition=definition,
            checkpoints=checkpoints,
            admission=admission or InMemoryAdmissionPort(),
            sessions=SessionCoordinator(provider, refs),
            context_source=context_source or StaticContextSource(_sections("canonical")),
            dispatcher=dispatch or ScriptedToolDispatchPort(()),
            budget_factory=budget_factory or _budget_factory(),
            cancellation=cancellation,
            diagnostics=diagnostics,
            event_sink=event_sink,
        )
    finally:
        await provider.shutdown()
    return outcome, refs


class _DiagnosticSink:
    def __init__(self) -> None:
        self.records: list[DiagnosticRecord] = []

    def emit(self, record: DiagnosticRecord) -> None:
        self.records.append(record)


async def test_no_work_and_deferred_admission_call_no_provider(tmp_path: Path) -> None:
    definition, plan, _ = _definition()
    runtime = _Runtime([])
    no_work = InMemoryInputCheckpointPort((ClaimNoWork(),))
    factory = _BudgetFactory()

    outcome, _ = await _thread(
        tmp_path,
        definition,
        _claim(plan),
        runtime,
        no_work,
        budget_factory=factory,
    )

    assert outcome.type == "no_work"
    assert factory.plans == []
    assert runtime.opens == []

    deferred = InMemoryAdmissionPort(max_live_slots=1)
    until = datetime.now(UTC) + timedelta(minutes=1)
    original_reserve = deferred.reserve

    async def reserve(_request: object):
        return AdmissionDeferred(until)

    deferred.reserve = reserve  # type: ignore[method-assign]
    claimed = InMemoryInputCheckpointPort((ClaimAcquired(_claim(plan)),))
    outcome, _ = await _thread(
        tmp_path,
        definition,
        _claim(plan),
        runtime,
        claimed,
        admission=deferred,
    )
    deferred.reserve = original_reserve  # type: ignore[method-assign]

    assert outcome.type == "deferred"
    assert runtime.opens == []
    assert len(claimed.release_reasons) == 1


async def test_claim_reservation_and_release_defects_never_reach_provider(
    tmp_path: Path,
) -> None:
    definition, plan, _ = _definition()
    claim = _claim(plan)

    with pytest.raises(CheckpointStateDefect, match="claim failure"):
        await _thread(tmp_path, definition, claim, _Runtime([]), _FailingClaim())

    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    outcome, _ = await _thread(
        tmp_path,
        definition,
        claim,
        _Runtime([]),
        checkpoints,
        admission=_FailingReservation(),
    )
    assert outcome.type is ThreadStopKind.configuration_error
    assert len(checkpoints.park_reasons) == 1

    until = datetime.now(UTC) + timedelta(minutes=1)
    failing_release = _FailingRelease((ClaimAcquired(claim),))
    deferred = InMemoryAdmissionPort()

    async def reserve(_request: AdmissionRequest):
        return AdmissionDeferred(until)

    deferred.reserve = reserve  # type: ignore[method-assign]
    with pytest.raises(CheckpointStateDefect, match="release failure"):
        await _thread(
            tmp_path,
            definition,
            claim,
            _Runtime([]),
            failing_release,
            admission=deferred,
        )

    failing_early_settlement = _FailingSettlement((ClaimAcquired(claim),))
    outcome, _ = await _thread(
        tmp_path,
        definition,
        claim,
        _Runtime([]),
        failing_early_settlement,
        admission=InMemoryAdmissionPort(max_turns=1),
    )
    assert outcome.type is ThreadStopKind.configuration_error
    assert len(failing_early_settlement.park_reasons) == 1

    interrupted = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    unexpected = InMemoryAdmissionPort()

    async def crash(_request: AdmissionRequest):
        raise RuntimeError("injected interruption")

    unexpected.reserve = crash  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="injected interruption"):
        await _thread(
            tmp_path,
            definition,
            claim,
            _Runtime([]),
            interrupted,
            admission=unexpected,
        )
    assert len(interrupted.release_reasons) == 1


async def test_checkpoint_boundary_rejects_unknown_closed_results(tmp_path: Path) -> None:
    definition, plan, _ = _definition()
    claim = _claim(plan)

    invalid_release = InMemoryInputCheckpointPort((ClaimAcquired(claim),))

    async def release_none(*_args: object, **_kwargs: object):
        return None

    invalid_release.release = release_none  # type: ignore[method-assign]
    admission = InMemoryAdmissionPort()

    async def defer(_request: AdmissionRequest):
        return AdmissionDeferred(datetime.now(UTC) + timedelta(minutes=1))

    admission.reserve = defer  # type: ignore[method-assign]
    with pytest.raises(KernelConfigurationDefect, match="release result"):
        await _thread(
            tmp_path,
            definition,
            claim,
            _Runtime([]),
            invalid_release,
            admission=admission,
        )

    forged = replace(plan, plan_revision="0" * 64)
    invalid_park = InMemoryInputCheckpointPort((ClaimAcquired(_claim(forged)),))

    async def park_none(*_args: object, **_kwargs: object):
        return None

    invalid_park.park = park_none  # type: ignore[method-assign]
    with pytest.raises(KernelConfigurationDefect, match="park result"):
        await _thread(
            tmp_path,
            definition,
            _claim(forged),
            _Runtime([]),
            invalid_park,
        )

    invalid_settle = InMemoryInputCheckpointPort((ClaimAcquired(claim),))

    async def settle_none(*_args: object, **_kwargs: object):
        return None

    invalid_settle.settle = settle_none  # type: ignore[method-assign]
    outcome, _ = await _thread(
        tmp_path,
        definition,
        claim,
        _Runtime([(_terminal({"type": "say", "text": "not committed"}),)]),
        invalid_settle,
    )
    assert outcome.type is ThreadStopKind.configuration_error
    assert outcome.metrics.input_consumed is False
    assert len(invalid_settle.park_reasons) == 1


async def test_thread_streams_stores_ref_then_settles_valid_say(tmp_path: Path) -> None:
    definition, plan, _ = _definition()
    claim = _claim(plan)
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    runtime = _Runtime([(_terminal({"type": "say", "text": "done"}),)])

    outcome, refs = await _thread(tmp_path, definition, claim, runtime, checkpoints)

    assert outcome.type == "completed"
    assert outcome.metrics.provider_turns == 1
    assert runtime.run_turn_calls == 0
    assert [record.conclusion for record in checkpoints.settlements] == [
        ConversationConclusion("done")
    ]
    assert await refs.load(ThreadId("thread-1"), definition.fingerprint) is not None


async def test_six_turn_resumed_session_settles_invocation_local_usage_once_per_turn(
    tmp_path: Path,
) -> None:
    limits = KernelLimits(
        max_provider_turns=6,
        max_provider_input_tokens=60,
        max_provider_output_tokens=12,
    )
    definition, plan, _ = _definition(effect=ToolEffect.Read, limits=limits)
    claim = _claim(plan)
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    saved = _ref("saved-six-turn-session")
    references = InMemorySessionRefPort()
    await references.compare_and_set(ThreadId("thread-1"), definition.fingerprint, None, saved)
    local_usage = _usage(10, 2)
    scripts: list[tuple[AgentEvent, ...]] = [
        (
            _terminal(
                {
                    "type": "call_tool",
                    "tool_id": "test.observe",
                    "arguments": {"value": f"turn-{turn}"},
                },
                saved,
                local_usage,
            ),
        )
        for turn in range(1, 6)
    ]
    scripts.append((_terminal({"type": "say", "text": "done"}, saved, local_usage),))
    dispatch = ScriptedToolDispatchPort(
        tuple(
            DispatchCompleted({"type": "Success", "value": {"value": f"seen-{turn}"}})
            for turn in range(1, 6)
        )
    )
    admission = InMemoryAdmissionPort(
        max_turns=6,
        max_input_tokens=60,
        max_output_tokens=12,
    )
    runtime = _Runtime(scripts)

    outcome, _ = await _thread(
        tmp_path,
        definition,
        claim,
        runtime,
        checkpoints,
        dispatch,
        admission,
        references,
    )

    assert outcome.type == "completed"
    assert outcome.metrics.provider_turns == 6
    assert outcome.metrics.usage.input_tokens == 60
    assert outcome.metrics.usage.output_tokens == 12
    assert isinstance(runtime.opens[0].open, ResumeSession)
    assert len(dispatch.calls) == 5
    assert admission.charged_turns == 6
    assert admission.charged_input_tokens == 60
    assert admission.charged_output_tokens == 12
    assert admission.live_slots == 0


async def test_absent_invocation_usage_retains_full_admission_token_reservation(
    tmp_path: Path,
) -> None:
    limits = KernelLimits(
        max_provider_turns=2,
        max_provider_input_tokens=20,
        max_provider_output_tokens=10,
    )
    definition, plan, _ = _definition(limits=limits)
    claim = _claim(plan)
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    admission = InMemoryAdmissionPort(
        max_turns=2,
        max_input_tokens=20,
        max_output_tokens=10,
    )

    outcome, _ = await _thread(
        tmp_path,
        definition,
        claim,
        _Runtime([(_terminal({"type": "say", "text": "done"}),)]),
        checkpoints,
        admission=admission,
    )

    assert outcome.type == "completed"
    assert outcome.metrics.provider_turns == 1
    assert outcome.metrics.usage.input_tokens is None
    assert outcome.metrics.usage.output_tokens is None
    assert admission.charged_turns == 1
    assert admission.charged_input_tokens == 20
    assert admission.charged_output_tokens == 10
    assert admission.live_slots == 0


async def test_diagnostic_transcript_is_opt_in_and_redacted_before_sink(
    tmp_path: Path,
) -> None:
    definition, plan, _ = _definition()
    claim = _claim(plan)
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    runtime = _Runtime([(_terminal({"type": "say", "text": "private answer"}),)])
    sink = _DiagnosticSink()
    diagnostics = DiagnosticTranscript(sink, lambda _text: RedactedText("[redacted]"))

    outcome, _ = await _thread(
        tmp_path,
        definition,
        claim,
        runtime,
        checkpoints,
        diagnostics=diagnostics,
    )

    assert outcome.type == "completed"
    assert [record.kind for record in sink.records] == [
        DiagnosticKind.provider_input,
        DiagnosticKind.provider_terminal,
    ]
    assert [record.content for record in sink.records] == ["[redacted]", "[redacted]"]
    assert all("hello" not in record.content for record in sink.records)
    assert all("not a trusted projection" not in record.content for record in sink.records)


async def test_frozen_plan_is_rejected_before_rendering_admission_or_provider(
    tmp_path: Path,
) -> None:
    definition, plan, _ = _definition()
    forged = replace(plan, plan_revision="0" * 64)
    claim = _claim(forged)
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    admission = InMemoryAdmissionPort()
    runtime = _Runtime([])
    factory = _BudgetFactory()
    context_source = StaticContextSource(_sections("must not render"))

    outcome, _ = await _thread(
        tmp_path,
        definition,
        claim,
        runtime,
        checkpoints,
        admission=admission,
        budget_factory=factory,
        context_source=context_source,
    )

    assert outcome.type is ThreadStopKind.configuration_error
    assert factory.plans == []
    assert context_source.bootstrap_calls == []
    assert context_source.continuation_calls == []
    assert admission.charged_turns == 0
    assert runtime.opens == []


async def test_claimed_plan_constructs_and_verifies_its_own_tool_budget_before_io(
    tmp_path: Path,
) -> None:
    definition, plan, _ = _definition()
    claim = _claim(plan)
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    admission = InMemoryAdmissionPort()
    runtime = _Runtime([(_terminal({"type": "say", "text": "done"}),)])
    factory = _BudgetFactory()

    outcome, _ = await _thread(
        tmp_path,
        definition,
        claim,
        runtime,
        checkpoints,
        admission=admission,
        budget_factory=factory,
    )

    assert outcome.type == "completed"
    assert factory.plans == [plan]
    assert runtime.opens


async def test_mismatched_claimed_plan_budget_parks_before_rendering_or_io(
    tmp_path: Path,
) -> None:
    definition, plan, _ = _definition()
    claim = _claim(plan)
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    admission = InMemoryAdmissionPort()
    runtime = _Runtime([])
    context_source = StaticContextSource(_sections("must not render"))
    wrong_limits = RunLimits(7, 8, 32_768, 32_768, 1, 30.0)
    factory = _BudgetFactory(wrong_limits)

    outcome, _ = await _thread(
        tmp_path,
        definition,
        claim,
        runtime,
        checkpoints,
        admission=admission,
        budget_factory=factory,
        context_source=context_source,
    )

    assert outcome.type is ThreadStopKind.configuration_error
    assert factory.plans == [plan]
    assert len(checkpoints.park_reasons) == 1
    assert context_source.bootstrap_calls == []
    assert context_source.continuation_calls == []
    assert admission.charged_turns == 0
    assert runtime.opens == []


async def test_whole_step_repair_is_effect_free_and_bounded(tmp_path: Path) -> None:
    definition, plan, _ = _definition(effect=ToolEffect.Read)
    claim = _claim(plan)
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    dispatch = ScriptedToolDispatchPort(())
    runtime = _Runtime(
        [
            (
                _terminal(
                    {
                        "type": "call_tool",
                        "tool_id": "test.observe",
                        "arguments": {"value": 3},
                    }
                ),
            ),
            (_terminal({"type": "say", "text": "repaired"}),),
        ]
    )

    outcome, _ = await _thread(
        tmp_path,
        definition,
        claim,
        runtime,
        checkpoints,
        dispatch,
    )

    assert outcome.type == "completed"
    assert outcome.metrics.provider_turns == 2
    assert dispatch.calls == []
    correction = runtime.turns[1].input[0]
    assert isinstance(correction, TextContent)
    assert "protocol_correction" in correction.text


async def test_protocol_poison_is_consumed_without_rearm(tmp_path: Path) -> None:
    limits = KernelLimits(max_protocol_repairs=0)
    definition, plan, _ = _definition(effect=ToolEffect.Read, limits=limits)
    claim = _claim(plan)
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    runtime = _Runtime([(_terminal({"type": "say", "text": "", "extra": True}),)])

    outcome, _ = await _thread(tmp_path, definition, claim, runtime, checkpoints)

    assert outcome.type is ThreadStopKind.protocol_error
    assert outcome.metrics.input_consumed is True
    assert checkpoints.settlements[0].conclusion == StoppedConclusion(StopReason.protocol_error)
    assert checkpoints.release_reasons == []


async def test_reported_token_limit_stops_after_cas_before_model_action(
    tmp_path: Path,
) -> None:
    limits = KernelLimits(max_provider_input_tokens=1)
    definition, plan, _ = _definition(limits=limits)
    claim = _claim(plan)
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    usage = TokenUsage.from_components(
        input_tokens=2,
        output_tokens=1,
        total_tokens=Absent(),
        reasoning_tokens=Absent(),
        cache_read_input_tokens=Absent(),
        cache_write_input_tokens=Absent(),
    )
    runtime = _Runtime([(AgentUsage(usage), _terminal({"type": "say", "text": "must not settle"}))])

    outcome, refs = await _thread(
        tmp_path,
        definition,
        claim,
        runtime,
        checkpoints,
        admission=InMemoryAdmissionPort(provider_input_token_overshoot=9),
    )

    assert outcome.type is ThreadStopKind.budget_exhausted
    assert checkpoints.settlements[0].conclusion == StoppedConclusion(StopReason.budget_exhausted)
    assert await refs.load(ThreadId("thread-1"), definition.fingerprint) is None


async def test_turn_timeout_is_a_zero_turn_budget_stop_and_closes_session(
    tmp_path: Path,
) -> None:
    definition, plan, _ = _definition()
    claim = _claim(plan)
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    runtime = _Runtime([], stream_error=TurnNotStarted("turn_timeout"))

    outcome, refs = await _thread(tmp_path, definition, claim, runtime, checkpoints)

    assert outcome.type is ThreadStopKind.budget_exhausted
    assert outcome.metrics.provider_turns == 0
    assert checkpoints.settlements[0].conclusion == StoppedConclusion(StopReason.budget_exhausted)
    assert await refs.load(ThreadId("thread-1"), definition.fingerprint) is None
    assert len(runtime.closed) == 1


async def test_runtime_cancelled_before_turn_is_a_typed_cancelled_stop(tmp_path: Path) -> None:
    definition, plan, _ = _definition()
    claim = _claim(plan)
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    runtime = _Runtime([], stream_error=TurnNotStarted("cancelled"))

    outcome, _ = await _thread(tmp_path, definition, claim, runtime, checkpoints)

    assert outcome.type is ThreadStopKind.cancelled
    assert outcome.metrics.provider_turns == 0
    assert checkpoints.settlements[0].conclusion == StoppedConclusion(StopReason.cancelled)
    assert len(runtime.closed) == 1


@pytest.mark.parametrize(
    ("failure", "kind", "reason"),
    [
        (
            AgentQuotaExhausted(),
            ThreadStopKind.quota_exhausted,
            StopReason.quota_exhausted,
        ),
        (
            AgentFailure("backend_failed"),
            ThreadStopKind.provider_error,
            StopReason.provider_error,
        ),
    ],
)
async def test_provider_stop_kinds_consume_without_automatic_retry(
    tmp_path: Path,
    failure: AgentFailure | AgentQuotaExhausted,
    kind: ThreadStopKind,
    reason: StopReason,
) -> None:
    definition, plan, _ = _definition()
    claim = _claim(plan)
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    runtime = _Runtime([(_failed_terminal(failure),)])

    outcome, _ = await _thread(tmp_path, definition, claim, runtime, checkpoints)

    assert outcome.type is kind
    assert outcome.metrics.input_consumed is True
    assert checkpoints.settlements[0].conclusion == StoppedConclusion(reason)
    assert len(runtime.turns) == 1


async def test_failed_resumed_turn_discards_saved_session_reference(tmp_path: Path) -> None:
    definition, plan, _ = _definition()
    claim = _claim(plan)
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    refs = InMemorySessionRefPort()
    saved = _ref("saved")
    await refs.compare_and_set(ThreadId("thread-1"), definition.fingerprint, None, saved)
    runtime = _Runtime([(_failed_terminal(AgentFailure("backend_failed"), saved),)])

    outcome, _ = await _thread(
        tmp_path,
        definition,
        claim,
        runtime,
        checkpoints,
        references=refs,
    )

    assert outcome.type is ThreadStopKind.provider_error
    assert isinstance(runtime.opens[0].open, ResumeSession)
    assert await refs.load(ThreadId("thread-1"), definition.fingerprint) is None


async def test_containment_stop_preserves_observed_usage_in_outcome(tmp_path: Path) -> None:
    definition, plan, _ = _definition(effect=ToolEffect.Read)
    claim = _claim(plan)
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    usage = TokenUsage.from_components(
        input_tokens=7,
        output_tokens=3,
        total_tokens=Absent(),
        reasoning_tokens=Absent(),
        cache_read_input_tokens=Absent(),
        cache_write_input_tokens=Absent(),
    )
    runtime = _Runtime(
        [(AgentUsage(usage), AgentToolUse("native-1", "shell", "started", FrozenJsonDict({})))]
    )

    outcome, _ = await _thread(tmp_path, definition, claim, runtime, checkpoints)

    assert outcome.type is ThreadStopKind.configuration_error
    assert outcome.metrics.usage.input_tokens == 7
    assert outcome.metrics.usage.output_tokens == 3
    assert len(checkpoints.park_reasons) == 1


async def test_serial_dispatch_lineage_includes_mid_loop_input(tmp_path: Path) -> None:
    definition, plan, binding = _definition(effect=ToolEffect.Read)
    assert binding is not None
    claim = _claim(plan)
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    from llm_agent_kernel.coordination import AppendInputs, NoNewInput

    checkpoints.queue_poll(
        claim.claim_id,
        NoNewInput(),
        AppendInputs(
            (_input("input-2", "compatible follow-up"),),
            Checkpoint("checkpoint-2"),
            datetime.now(UTC),
        ),
    )
    dispatch = ScriptedToolDispatchPort(
        (DispatchCompleted({"type": "Success", "value": {"value": "seen"}}),)
    )
    runtime = _Runtime(
        [
            (
                _terminal(
                    {
                        "type": "call_tool",
                        "tool_id": "test.observe",
                        "arguments": {"value": "x"},
                    }
                ),
            ),
            (
                _terminal(
                    {
                        "type": "call_tool",
                        "tool_id": "test.observe",
                        "arguments": {"value": "x"},
                    }
                ),
            ),
            (_terminal({"type": "say", "text": "done"}),),
        ]
    )

    outcome, _ = await _thread(
        tmp_path,
        definition,
        claim,
        runtime,
        checkpoints,
        dispatch,
    )

    assert outcome.type == "completed"
    assert len(dispatch.calls) == 1
    lineage = dispatch.calls[0].lineage
    assert isinstance(lineage, DispatchLineage)
    assert lineage.input_ids == (InputId("input-1"), InputId("input-2"))
    assert lineage.through_checkpoint == Checkpoint("checkpoint-2")
    appended = runtime.turns[1].input[0]
    observation = runtime.turns[2].input[0]
    assert isinstance(appended, TextContent)
    assert isinstance(observation, TextContent)
    assert "compatible follow-up" in appended.text
    assert "tool_observation" in observation.text


async def test_pre_dispatch_append_revalidates_before_any_tool_action(tmp_path: Path) -> None:
    from llm_agent_kernel.coordination import AppendInputs, NoNewInput

    definition, plan, _ = _definition(effect=ToolEffect.Write)
    claim = _claim(plan)
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    checkpoints.queue_poll(
        claim.claim_id,
        NoNewInput(),
        AppendInputs(
            (_input("input-2", "steer before action"),),
            Checkpoint("checkpoint-2"),
            datetime.now(UTC),
        ),
    )
    call = _terminal(
        {
            "type": "call_tool",
            "tool_id": "test.observe",
            "arguments": {"value": "x"},
        }
    )
    runtime = _Runtime([(call,), (call,)])
    dispatch = ScriptedToolDispatchPort(
        (DispatchSuspended(HostRef("action-1"), WaitingFor.system),)
    )

    outcome, _ = await _thread(
        tmp_path,
        definition,
        claim,
        runtime,
        checkpoints,
        dispatch,
    )

    assert outcome.type == "suspended"
    assert len(runtime.turns) == 2
    assert "steer before action" in cast(TextContent, runtime.turns[1].input[0]).text
    assert len(dispatch.calls) == 1
    assert dispatch.calls[0].lineage.model_step_ordinal == 2


async def test_append_at_final_check_retains_paid_answer_for_old_checkpoint(
    tmp_path: Path,
) -> None:
    definition, plan, _ = _definition()
    claim = _claim(plan)
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    from llm_agent_kernel.coordination import AppendInputs, NoNewInput

    checkpoints.queue_poll(
        claim.claim_id,
        NoNewInput(),
        AppendInputs(
            (_input("input-2", "late compatible input"),),
            Checkpoint("checkpoint-2"),
            datetime.now(UTC),
        ),
    )
    checkpoints.settle_results.append(SettleMoreInput())
    runtime = _Runtime(
        [
            (_terminal({"type": "say", "text": "first answer"}),),
            (_terminal({"type": "say", "text": "combined answer"}),),
        ]
    )

    outcome, _ = await _thread(tmp_path, definition, claim, runtime, checkpoints)

    assert outcome.type == "completed"
    assert len(runtime.turns) == 1
    assert checkpoints.settlements[0].through_checkpoint == Checkpoint("checkpoint-1")
    assert checkpoints.settlements[0].conclusion == ConversationConclusion("first answer")


class _StaleReferences(InMemorySessionRefPort):
    async def compare_and_set(
        self,
        thread_id: ThreadId,
        definition_fingerprint: str,
        expected_generation: int | None,
        new_ref: AgentSessionRef,
    ):
        del thread_id, definition_fingerprint, expected_generation, new_ref
        return StaleSessionRef()


async def test_stale_session_cas_permits_no_dispatch_or_settlement(tmp_path: Path) -> None:
    definition, plan, _ = _definition(effect=ToolEffect.Read)
    claim = _claim(plan)
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    dispatch = ScriptedToolDispatchPort(())
    sink = _DiagnosticSink()
    runtime = _Runtime(
        [
            (
                _terminal(
                    {
                        "type": "call_tool",
                        "tool_id": "test.observe",
                        "arguments": {"value": "x"},
                    }
                ),
            )
        ]
    )

    outcome, _ = await _thread(
        tmp_path,
        definition,
        claim,
        runtime,
        checkpoints,
        dispatch,
        references=_StaleReferences(),
        diagnostics=DiagnosticTranscript(sink, lambda _text: RedactedText("[redacted]")),
    )

    assert outcome.type is ThreadStopKind.configuration_error
    assert dispatch.calls == []
    assert checkpoints.settlements == []
    assert len(checkpoints.park_reasons) == 1
    assert [record.kind for record in sink.records] == [DiagnosticKind.provider_input]


async def test_dispatch_and_checkpoint_defects_park_without_fabricated_success(
    tmp_path: Path,
) -> None:
    definition, plan, _ = _definition(effect=ToolEffect.Read)
    call = _terminal(
        {
            "type": "call_tool",
            "tool_id": "test.observe",
            "arguments": {"value": "x"},
        }
    )
    claim = _claim(plan)
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    outcome, _ = await _thread(
        tmp_path,
        definition,
        claim,
        _Runtime([(call,)]),
        checkpoints,
        _FailingDispatch(()),
    )
    assert outcome.type is ThreadStopKind.configuration_error
    assert checkpoints.settlements == []
    assert len(checkpoints.park_reasons) == 1

    no_tools, empty_plan, _ = _definition()
    empty_claim = _claim(empty_plan)
    failing_checkpoint = _FailingSettlement((ClaimAcquired(empty_claim),))
    outcome, refs = await _thread(
        tmp_path,
        no_tools,
        empty_claim,
        _Runtime([(_terminal({"type": "say", "text": "answer"}),)]),
        failing_checkpoint,
    )
    assert outcome.type is ThreadStopKind.configuration_error
    assert len(failing_checkpoint.park_reasons) == 1
    assert await refs.load(ThreadId("thread-1"), no_tools.fingerprint) is None


async def test_usage_settlement_defect_is_not_hidden_after_canonical_conclusion(
    tmp_path: Path,
) -> None:
    definition, plan, _ = _definition()
    claim = _claim(plan)
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))

    with pytest.raises(AdmissionStateDefect, match="usage settlement"):
        await _thread(
            tmp_path,
            definition,
            claim,
            _Runtime([(_terminal({"type": "say", "text": "answer"}),)]),
            checkpoints,
            admission=_FailingUsageSettlement(),
        )

    assert checkpoints.settlements[0].conclusion == ConversationConclusion("answer")


async def test_native_authority_event_fail_stops_without_host_action(tmp_path: Path) -> None:
    definition, plan, _ = _definition(effect=ToolEffect.Read)
    claim = _claim(plan)
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    dispatch = ScriptedToolDispatchPort(())
    runtime = _Runtime(
        [
            (
                AgentText("suppressed"),
                AgentToolUse("native-1", "shell", "started", FrozenJsonDict({})),
                _terminal({"type": "say", "text": "must not escape"}),
            )
        ]
    )

    outcome, _ = await _thread(
        tmp_path,
        definition,
        claim,
        runtime,
        checkpoints,
        dispatch,
    )

    assert outcome.type is ThreadStopKind.configuration_error
    assert dispatch.calls == []
    assert checkpoints.settlements == []


async def test_suspension_is_durably_settled_and_returns(tmp_path: Path) -> None:
    definition, plan, _ = _definition(effect=ToolEffect.Write)
    claim = _claim(plan)
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    dispatch = ScriptedToolDispatchPort(
        (DispatchSuspended(HostRef("action-1"), WaitingFor.system),)
    )
    runtime = _Runtime(
        [
            (
                _terminal(
                    {
                        "type": "call_tool",
                        "tool_id": "test.observe",
                        "arguments": {"value": "x"},
                    }
                ),
            )
        ]
    )

    outcome, _ = await _thread(
        tmp_path,
        definition,
        claim,
        runtime,
        checkpoints,
        dispatch,
    )

    assert outcome.type == "suspended"
    assert checkpoints.settlements[0].conclusion == SuspensionConclusion(
        HostRef("action-1"), WaitingFor.system
    )


async def test_attempt_ceiling_stops_before_admission_or_provider(tmp_path: Path) -> None:
    definition, plan, _ = _definition(limits=KernelLimits(max_no_progress_attempts=2))
    claim = _claim(plan, attempt=3)
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    admission = InMemoryAdmissionPort()
    runtime = _Runtime([])

    outcome, _ = await _thread(
        tmp_path,
        definition,
        claim,
        runtime,
        checkpoints,
        admission=admission,
    )

    assert outcome.type is ThreadStopKind.provider_error
    assert runtime.opens == []
    assert admission.charged_turns == 0


async def test_cooperative_limit_stops_before_a_provider_turn(tmp_path: Path) -> None:
    class Clock:
        calls = 0

        def __call__(self) -> float:
            self.calls += 1
            return 0.0 if self.calls == 1 else 2.0

    definition, plan, _ = _definition(limits=KernelLimits(max_cooperative_seconds=1.0))
    claim = _claim(plan)
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    runtime = _Runtime([])
    provider = CodexProvider(cast(AgentRuntime, runtime), cwd_parent=tmp_path)
    refs = InMemorySessionRefPort()
    try:
        outcome = await run_thread(
            run_id=RunId("wall-limit"),
            thread_id=ThreadId("thread-1"),
            owner_token=OwnerToken("owner-1"),
            definition=definition,
            checkpoints=checkpoints,
            admission=InMemoryAdmissionPort(),
            sessions=SessionCoordinator(provider, refs),
            context_source=StaticContextSource(_sections("canonical")),
            dispatcher=ScriptedToolDispatchPort(()),
            budget_factory=_budget_factory(),
            clock=Clock(),
        )
    finally:
        await provider.shutdown()

    assert outcome.type is ThreadStopKind.budget_exhausted
    assert outcome.metrics.provider_turns == 0
    assert runtime.turns == []


async def test_cooperative_limit_does_not_wrap_write_dispatch(
    tmp_path: Path,
) -> None:
    class Clock:
        now = 0.0

        def __call__(self) -> float:
            return self.now

    class AdvancingDispatch(ScriptedToolDispatchPort):
        async def dispatch(self, **kwargs: Any):
            result = await super().dispatch(**kwargs)
            clock.now = 2.0
            return result

    clock = Clock()
    definition, plan, _ = _definition(
        effect=ToolEffect.Write,
        limits=KernelLimits(max_cooperative_seconds=1.0),
    )
    claim = _claim(plan)
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    runtime = _Runtime(
        [
            (
                _terminal(
                    {
                        "type": "call_tool",
                        "tool_id": "test.observe",
                        "arguments": {"value": "write once"},
                    }
                ),
            )
        ]
    )
    dispatch = AdvancingDispatch(
        (DispatchCompleted({"type": "Success", "value": {"value": "written"}}),)
    )
    provider = CodexProvider(cast(AgentRuntime, runtime), cwd_parent=tmp_path)
    try:
        outcome = await run_thread(
            run_id=RunId("cooperative-write"),
            thread_id=ThreadId("thread-1"),
            owner_token=OwnerToken("owner-1"),
            definition=definition,
            checkpoints=checkpoints,
            admission=InMemoryAdmissionPort(),
            sessions=SessionCoordinator(provider, InMemorySessionRefPort()),
            context_source=StaticContextSource(_sections("canonical")),
            dispatcher=dispatch,
            budget_factory=_budget_factory(),
            clock=clock,
        )
    finally:
        await provider.shutdown()

    assert outcome.type is ThreadStopKind.budget_exhausted
    assert len(dispatch.calls) == 1
    assert checkpoints.settlements[0].conclusion == StoppedConclusion(StopReason.budget_exhausted)


async def test_turn_limit_consumes_after_the_reserved_turn(tmp_path: Path) -> None:
    definition, plan, _ = _definition(
        limits=KernelLimits(max_provider_turns=1, max_protocol_repairs=1),
    )
    claim = _claim(plan)
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    runtime = _Runtime([(_terminal({"type": "say", "text": "", "extra": True}),)])

    outcome, _ = await _thread(tmp_path, definition, claim, runtime, checkpoints)

    assert outcome.type is ThreadStopKind.budget_exhausted
    assert outcome.metrics.provider_turns == 1
    assert checkpoints.settlements[0].conclusion == StoppedConclusion(StopReason.budget_exhausted)


async def test_preempt_releases_without_settlement_or_automatic_rearm(tmp_path: Path) -> None:
    definition, plan, _ = _definition()
    claim = _claim(plan)
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    from llm_agent_kernel.coordination import Preempt

    checkpoints.queue_poll(claim.claim_id, Preempt("higher priority input"))
    runtime = _Runtime([])

    outcome, _ = await _thread(tmp_path, definition, claim, runtime, checkpoints)

    assert outcome.type is ThreadStopKind.preempted
    assert checkpoints.settlements == []
    assert len(checkpoints.release_reasons) == 1
    assert runtime.turns == []


async def test_preempt_while_stopping_discards_one_speculative_generation(
    tmp_path: Path,
) -> None:
    from llm_agent_kernel.coordination import NoNewInput, Preempt

    definition, plan, _ = _definition(
        limits=KernelLimits(max_provider_input_tokens=1),
    )
    claim = _claim(plan)
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    checkpoints.queue_poll(
        claim.claim_id,
        NoNewInput(),
        Preempt("host policy changed while stopping"),
    )
    usage = TokenUsage.from_components(
        input_tokens=2,
        output_tokens=1,
        total_tokens=Absent(),
        reasoning_tokens=Absent(),
        cache_read_input_tokens=Absent(),
        cache_write_input_tokens=Absent(),
    )
    runtime = _Runtime([(AgentUsage(usage), _terminal({"type": "say", "text": "unused"}))])

    outcome, refs = await _thread(
        tmp_path,
        definition,
        claim,
        runtime,
        checkpoints,
        admission=InMemoryAdmissionPort(provider_input_token_overshoot=9),
    )

    assert outcome.type is ThreadStopKind.preempted
    assert checkpoints.settlements == []
    assert len(checkpoints.release_reasons) == 1
    assert await refs.load(ThreadId("thread-1"), definition.fingerprint) is None


async def test_isolated_structured_run_is_fresh_closed_and_uses_no_saved_state(
    tmp_path: Path,
) -> None:
    definition, plan, _ = _definition(mode=SessionMode.isolated, structured=True)
    runtime = _Runtime([(_terminal({"type": "finish", "result": {"answer": "yes"}}),)])
    provider = CodexProvider(cast(AgentRuntime, runtime), cwd_parent=tmp_path)
    admission = InMemoryAdmissionPort()

    outcome = await run_one_shot(
        run_id=RunId("isolated-1"),
        definition=definition,
        inputs=(_input(),),
        as_of=datetime.now(UTC),
        plan=plan,
        source_sections=_sections("canonical"),
        admission=admission,
        provider=provider,
        dispatcher=ScriptedToolDispatchPort(()),
        budget_factory=_budget_factory(),
    )

    assert outcome.type == "completed"
    assert isinstance(outcome, OneShotCompleted)
    assert cast(FrozenJsonDict, outcome.result)["answer"] == "yes"
    assert len(runtime.opens) == 1
    assert not isinstance(runtime.opens[0].open, ResumeSession)
    assert len(runtime.closed) == 1
    assert admission.live_slots == 0


async def test_isolated_provider_failure_closes_and_returns_typed_stop(tmp_path: Path) -> None:
    definition, plan, _ = _definition(mode=SessionMode.isolated, structured=True)
    runtime = _Runtime([(_failed_terminal(AgentFailure("backend_failed")),)])
    provider = CodexProvider(cast(AgentRuntime, runtime), cwd_parent=tmp_path)

    outcome = await run_one_shot(
        run_id=RunId("isolated-failure"),
        definition=definition,
        inputs=(_input(),),
        as_of=datetime.now(UTC),
        plan=plan,
        source_sections=_sections("canonical"),
        admission=InMemoryAdmissionPort(),
        provider=provider,
        dispatcher=ScriptedToolDispatchPort(()),
        budget_factory=_budget_factory(),
    )

    assert outcome.type is ThreadStopKind.provider_error
    assert len(runtime.closed) == 1


async def test_isolated_write_plan_is_rejected_before_admission_or_provider(
    tmp_path: Path,
) -> None:
    definition, plan, _ = _definition(
        mode=SessionMode.isolated,
        structured=True,
        effect=ToolEffect.Write,
    )
    runtime = _Runtime([])
    provider = CodexProvider(cast(AgentRuntime, runtime), cwd_parent=tmp_path)
    admission = InMemoryAdmissionPort()
    factory = _BudgetFactory()

    with pytest.raises(ValueError, match="Write"):
        await run_one_shot(
            run_id=RunId("isolated-1"),
            definition=definition,
            inputs=(_input(),),
            as_of=datetime.now(UTC),
            plan=plan,
            source_sections=_sections(),
            admission=admission,
            provider=provider,
            dispatcher=ScriptedToolDispatchPort(()),
            budget_factory=factory,
        )

    assert factory.plans == []
    assert runtime.opens == []
    assert admission.charged_turns == 0


async def test_isolated_budget_mismatch_is_rejected_before_admission_or_provider(
    tmp_path: Path,
) -> None:
    definition, plan, _ = _definition(mode=SessionMode.isolated, structured=True)
    runtime = _Runtime([])
    provider = CodexProvider(cast(AgentRuntime, runtime), cwd_parent=tmp_path)
    admission = InMemoryAdmissionPort()
    factory = _BudgetFactory(RunLimits(7, 8, 32_768, 32_768, 1, 30.0))

    with pytest.raises(KernelConfigurationDefect, match="budget limits"):
        await run_one_shot(
            run_id=RunId("isolated-budget-mismatch"),
            definition=definition,
            inputs=(_input(),),
            as_of=datetime.now(UTC),
            plan=plan,
            source_sections=_sections("must not render"),
            admission=admission,
            provider=provider,
            dispatcher=ScriptedToolDispatchPort(()),
            budget_factory=factory,
        )

    assert factory.plans == [plan]
    assert admission.charged_turns == 0
    assert runtime.opens == []


async def test_isolated_admission_rejection_returns_without_provider_io(tmp_path: Path) -> None:
    definition, plan, _ = _definition(mode=SessionMode.isolated, structured=True)
    runtime = _Runtime([])
    provider = CodexProvider(cast(AgentRuntime, runtime), cwd_parent=tmp_path)
    admission = InMemoryAdmissionPort(max_turns=1)

    outcome = await run_one_shot(
        run_id=RunId("isolated-rejected"),
        definition=definition,
        inputs=(_input(),),
        as_of=datetime.now(UTC),
        plan=plan,
        source_sections=_sections("canonical"),
        admission=admission,
        provider=provider,
        dispatcher=ScriptedToolDispatchPort(()),
        budget_factory=_budget_factory(),
    )

    assert outcome.type is ThreadStopKind.budget_exhausted
    assert runtime.opens == []
    assert admission.charged_turns == 0


async def test_isolated_cancellation_before_dispatch_closes_without_tool_action(
    tmp_path: Path,
) -> None:
    definition, plan, _ = _definition(
        mode=SessionMode.isolated,
        structured=True,
        effect=ToolEffect.Read,
    )
    cancellation = CancellationToken()
    runtime = _CancellingRuntime(
        [
            (
                _terminal(
                    {
                        "type": "call_tool",
                        "tool_id": "test.observe",
                        "arguments": {"value": "x"},
                    }
                ),
            )
        ],
        cancellation,
    )
    provider = CodexProvider(cast(AgentRuntime, runtime), cwd_parent=tmp_path)
    dispatch = ScriptedToolDispatchPort(())

    outcome = await run_one_shot(
        run_id=RunId("isolated-1"),
        definition=definition,
        inputs=(_input(),),
        as_of=datetime.now(UTC),
        plan=plan,
        source_sections=_sections("canonical"),
        admission=InMemoryAdmissionPort(),
        provider=provider,
        dispatcher=dispatch,
        budget_factory=_budget_factory(),
        cancellation=cancellation,
    )

    assert outcome.type is ThreadStopKind.cancelled
    assert dispatch.calls == []
    assert len(runtime.closed) == 1


async def test_child_one_shot_rejects_a_forged_independent_slot_before_provider(
    tmp_path: Path,
) -> None:
    definition, plan, _ = _definition(mode=SessionMode.isolated, structured=True)
    runtime = _Runtime([])
    provider = CodexProvider(cast(AgentRuntime, runtime), cwd_parent=tmp_path)
    parent = AdmissionToken(
        RunId("parent"),
        "window",
        "epoch",
        8,
        100_000,
        20_000,
        True,
    )
    admission = _ForgedChildAdmission()

    outcome = await run_one_shot(
        run_id=RunId("isolated-1"),
        definition=definition,
        inputs=(_input(),),
        as_of=datetime.now(UTC),
        plan=plan,
        source_sections=_sections("canonical"),
        admission=admission,
        provider=provider,
        dispatcher=ScriptedToolDispatchPort(()),
        budget_factory=_budget_factory(),
        parent_admission=parent,
    )

    assert outcome.type is ThreadStopKind.configuration_error
    assert runtime.opens == []
    assert admission.settled is True


async def test_cancelled_before_provider_consumes_only_under_declared_rule(
    tmp_path: Path,
) -> None:
    definition, plan, _ = _definition()
    claim = _claim(plan)
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    cancellation = CancellationToken()
    cancellation.cancel()
    runtime = _Runtime([])

    outcome, _ = await _thread(
        tmp_path,
        definition,
        claim,
        runtime,
        checkpoints,
        cancellation=cancellation,
    )

    assert outcome.type is ThreadStopKind.cancelled
    assert checkpoints.settlements[0].conclusion == StoppedConclusion(StopReason.cancelled)
    assert runtime.turns == []
    assert runtime.opens == []


async def test_isolated_pre_cancel_emits_metadata_without_opening_provider(
    tmp_path: Path,
) -> None:
    definition, plan, _ = _definition(mode=SessionMode.isolated, structured=True)
    cancellation = CancellationToken()
    cancellation.cancel()
    runtime = _Runtime([])
    provider = CodexProvider(cast(AgentRuntime, runtime), cwd_parent=tmp_path)
    events = RecordingEventSink()

    outcome = await run_one_shot(
        run_id=RunId("isolated-cancel"),
        definition=definition,
        inputs=(_input(),),
        as_of=datetime.now(UTC),
        plan=plan,
        source_sections=_sections("canonical"),
        admission=InMemoryAdmissionPort(),
        provider=provider,
        dispatcher=ScriptedToolDispatchPort(()),
        budget_factory=_budget_factory(),
        cancellation=cancellation,
        event_sink=events,
    )

    assert outcome.type is ThreadStopKind.cancelled
    assert runtime.opens == []
    assert [event.kind for event in events.events].count(EventKind.cancellation) == 1
    assert events.events[-1].kind is EventKind.outcome
    assert events.events[-1].attributes[0].value == ThreadStopKind.cancelled.value


async def test_bounded_event_rejection_never_changes_one_shot_work(tmp_path: Path) -> None:
    definition, plan, _ = _definition(mode=SessionMode.isolated, structured=True)
    runtime = _Runtime([(_terminal({"type": "finish", "result": {"answer": "yes"}}),)])
    provider = CodexProvider(cast(AgentRuntime, runtime), cwd_parent=tmp_path)
    events = RecordingEventSink()

    outcome = await run_one_shot(
        run_id=RunId("r" * 257),
        definition=definition,
        inputs=(_input(),),
        as_of=datetime.now(UTC),
        plan=plan,
        source_sections=_sections("canonical"),
        admission=InMemoryAdmissionPort(),
        provider=provider,
        dispatcher=ScriptedToolDispatchPort(()),
        budget_factory=_budget_factory(),
        event_sink=events,
    )

    assert outcome.type == "completed"
    assert events.events == []
