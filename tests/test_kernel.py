from __future__ import annotations

import hashlib
import json
from collections import deque
from collections.abc import AsyncGenerator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from llm_tools import (
    Available,
    BudgetState,
    CapabilityProfile,
    HostTable,
    InvocationPosition,
    NoDeclaredError,
    PolicyEpoch,
    ProfileId,
    PromptDocument,
    PromptSection,
    PromptSectionKind,
    PromptSections,
    PromptText,
    RecoveryRequired,
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
    canonical_json_bytes,
)
from provider_runtime.agent_runtime import (
    AgentAccepted,
    AgentAttempt,
    AgentCloseResult,
    AgentControlReceipt,
    AgentEvent,
    AgentFailure,
    AgentNotSubmitted,
    AgentQuotaExhausted,
    AgentRuntime,
    AgentSession,
    AgentSessionRef,
    AgentSessionRequest,
    AgentTerminal,
    AgentText,
    AgentTurnRef,
    CredentialRef,
    FrozenJsonDict,
    NativeTerminalEvidence,
    RawAgentOutput,
    ResumeSession,
    TextContent,
    TurnRequest,
    freeze_json_object,
)
from provider_runtime.types import Absent, CancelSignal, Present, TokenUsage
from pydantic import BaseModel, ConfigDict

from llm_agent_kernel.cancellation import CancellationToken
from llm_agent_kernel.context import bootstrap_context
from llm_agent_kernel.coordination import ToolDispatchDefect
from llm_agent_kernel.decisions import (
    IsolatedDecisionScope,
    TransientModelDecisions,
    model_decision_id,
)
from llm_agent_kernel.definitions import (
    KERNEL_BASE_INSTRUCTION,
    AgentDefinition,
    AgentRole,
    BatchAsOfMode,
    DefinitionId,
    DispatchCompleted,
    HostInput,
    InitialReadCall,
    InitialReadDispatchLineage,
    InputId,
    InputProjectionPolicy,
    InputProjectionRequest,
    IsolatedDispatchLineage,
    KernelLimits,
    OneShotCompleted,
    OneShotStopKind,
    OwnerPermit,
    OwnerToken,
    ProviderConfiguration,
    RunId,
    SessionMode,
    StructuredOutput,
)
from llm_agent_kernel.events import (
    EventKind,
)
from llm_agent_kernel.fakes import (
    RecordingEventSink,
    ScriptedToolDispatchPort,
)
from llm_agent_kernel.kernel import KernelConfigurationDefect, run_one_shot
from llm_agent_kernel.provider import CodexProvider


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
    mode: SessionMode = SessionMode.isolated,
    structured: bool = True,
    effect: ToolEffect | None = None,
    limits: KernelLimits | None = None,
    input_projection_policy: InputProjectionPolicy | None = None,
) -> tuple[AgentDefinition, Any, ToolBinding[Any, Any, Any] | None]:
    maximum, plan, binding = _authority(effect)
    return (
        AgentDefinition(
            DefinitionId("assistant"),
            AgentRole("assistant", _sections("role")),
            _sections("stable"),
            mode,
            StructuredOutput("answer", StructuredResult),
            maximum,
            ProviderConfiguration(
                CredentialRef("local_account", "test"),
                "gpt-5",
                "low",
                "test-catalog-v1",
                "a" * 64,
            ),
            "kernel-test-v1",
            limits or KernelLimits(),
            input_projection_policy or InputProjectionPolicy(),
        ),
        plan,
        binding,
    )


def _input(name: str = "input-1", text: str = "hello") -> HostInput:
    return HostInput(InputId(name), _sections(text), datetime.now(UTC))


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
    attempt: AgentAttempt | None = None,
) -> AgentTerminal:
    session_ref = ref or _ref()
    attempt = attempt or AgentAttempt(
        model_decision_id(IsolatedDecisionScope("test-operation"), 1), "d" * 64
    )
    return AgentTerminal(
        status="succeeded",
        failure=None,
        final_text="not a trusted projection",
        session_ref=session_ref,
        evidence=NativeTerminalEvidence(
            attempt, AgentTurnRef(session_ref, "turn"), "codex-turn-completed.v1"
        ),
        raw_structured_output=RawAgentOutput(freeze_json_object(_wire_step(value))),
        usage=Absent() if usage is None else Present(usage),
    )


def _wire_step(value: dict[str, object]) -> dict[str, object]:
    step_type = value.get("type")
    wire: dict[str, object] = {
        "type": step_type,
        "call_tool": None,
        "finish": None,
    }
    if step_type == "call_tool":
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
    session_ref = ref or _ref()
    attempt = AgentAttempt(model_decision_id(IsolatedDecisionScope("test-operation"), 1), "d" * 64)
    return AgentTerminal(
        status="failed",
        failure=failure,
        final_text="",
        session_ref=session_ref,
        evidence=NativeTerminalEvidence(
            attempt, AgentTurnRef(session_ref, "turn"), "codex-turn-completed.v1"
        ),
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

    def prepare_observed_turn(self, session, request, *, attempt_id, input_id, controls):
        digest = hashlib.sha256(
            json.dumps([part.text for part in request.input]).encode()
        ).hexdigest()
        return _PreparedTurn(self, session, request, AgentAttempt(attempt_id, digest))

    def session_usable(self, session) -> bool:
        return session not in self.closed

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


class _PreparedTurn:
    def __init__(self, runtime, session, request, attempt):
        self.runtime, self.session, self.request, self.attempt = runtime, session, request, attempt
        self.submission = None
        self.terminal = None
        self.revoked = False
        self.native_stream = None
        self.submitted_request = freeze_json_object(
            {"method": "turn/start", "params": {"input": [part.text for part in request.input]}}
        )

    async def submit(self):
        self.submission = (
            AgentNotSubmitted(self.attempt, "revoked before submission")
            if self.revoked
            else AgentAccepted(self.attempt, AgentTurnRef(self.session.ref, "turn"))
        )
        return self.submission

    async def events(self):
        self.native_stream = self.runtime.stream_turn(self.session, self.request)
        try:
            async for event in self.native_stream:
                if isinstance(event, AgentTerminal):
                    evidence = NativeTerminalEvidence(
                        self.attempt,
                        AgentTurnRef(event.session_ref, "turn"),
                        "codex-turn-completed.v1",
                    )
                    event = replace(event, evidence=evidence)
                    self.terminal = event
                yield event
        finally:
            await self.native_stream.aclose()

    def revoke(self):
        self.revoked = True

    async def interrupt(self):
        assert isinstance(self.submission, AgentAccepted)
        return AgentControlReceipt(
            "interrupt", "interrupt", self.submission.turn, "accepted", None, "test acknowledged"
        )

    async def close(self):
        if self.native_stream is not None:
            await self.native_stream.aclose()
        return AgentCloseResult(True, ())


class _Owner:
    def __init__(self, current: bool = True):
        self.current = current
        self.permits = []

    async def require_current(self, permit: OwnerPermit) -> None:
        if not self.current or permit.owner_token != OwnerToken("owner"):
            raise RuntimeError("stale owner")
        self.permits.append(permit)


def _permit():
    return OwnerPermit("test", OwnerToken("owner"), "isolated-operation", None)


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
        self.budgets: list[BudgetState] = []

    def create(self, plan: Any) -> BudgetState:
        self.plans.append(plan)
        budgets = cast(BudgetState, _Budgets(self.limits or plan.profile.run_limits))
        self.budgets.append(budgets)
        return budgets


def _budget_factory(limits: RunLimits | None = None) -> _BudgetFactory:
    return _BudgetFactory(limits)


class _FailingDispatch(ScriptedToolDispatchPort):
    async def dispatch(self, **kwargs: Any):
        del kwargs
        raise ToolDispatchDefect("injected dispatch failure")


async def test_isolated_structured_run_is_fresh_closed_and_uses_no_saved_state(
    tmp_path: Path,
) -> None:
    definition, plan, _ = _definition(mode=SessionMode.isolated, structured=True)
    runtime = _Runtime([(_terminal({"type": "finish", "result": {"answer": "yes"}}),)])
    provider = CodexProvider(cast(AgentRuntime, runtime), cwd_parent=tmp_path)
    owner = _Owner()

    outcome = await run_one_shot(
        decisions=TransientModelDecisions(),
        run_id=RunId("isolated-1"),
        definition=definition,
        inputs=(_input(),),
        as_of=datetime.now(UTC),
        plan=plan,
        source_sections=_sections("canonical"),
        owner=owner,
        permit=_permit(),
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


async def test_one_shot_without_initial_read_is_exactly_unchanged(tmp_path: Path) -> None:
    definition, plan, _ = _definition(mode=SessionMode.isolated, structured=True)
    inputs = (_input(),)
    as_of = datetime(2026, 9, 6, 10, 0, tzinfo=UTC)
    source_sections = _sections("canonical")
    expected = bootstrap_context(
        definition,
        inputs,
        as_of,
        plan,
        source_sections,
    ).rendered
    runtimes = [
        _Runtime([(_terminal({"type": "finish", "result": {"answer": "yes"}}),)]),
        _Runtime([(_terminal({"type": "finish", "result": {"answer": "yes"}}),)]),
    ]
    submissions: list[tuple[TextContent, ...]] = []
    variants: tuple[dict[str, Any], ...] = ({}, {"initial_read": None})

    for runtime, kwargs in zip(runtimes, variants, strict=True):
        provider = CodexProvider(cast(AgentRuntime, runtime), cwd_parent=tmp_path)
        dispatcher = ScriptedToolDispatchPort(())
        outcome = await run_one_shot(
            decisions=TransientModelDecisions(),
            run_id=RunId("no-initial-read"),
            definition=definition,
            inputs=inputs,
            as_of=as_of,
            plan=plan,
            source_sections=source_sections,
            owner=_Owner(),
            permit=_permit(),
            provider=provider,
            dispatcher=dispatcher,
            budget_factory=_budget_factory(),
            **kwargs,
        )
        assert isinstance(outcome, OneShotCompleted)
        assert dispatcher.calls == []
        submissions.append(cast(tuple[TextContent, ...], runtime.turns[0].input))

    assert submissions[0] == submissions[1]
    assert submissions[0] == (TextContent(expected),)


async def test_initial_read_precedes_provider_and_shares_budget_with_model_calls(
    tmp_path: Path,
) -> None:
    definition, plan, _ = _definition(
        mode=SessionMode.isolated,
        structured=True,
        effect=ToolEffect.Read,
    )
    runtime = _Runtime(
        [
            (
                _terminal(
                    {
                        "type": "call_tool",
                        "tool_id": "test.observe",
                        "arguments": {"value": "model-call"},
                    }
                ),
            ),
            (_terminal({"type": "finish", "result": {"answer": "used observation"}}),),
        ]
    )

    class OrderingDispatcher(ScriptedToolDispatchPort):
        async def dispatch(self, **kwargs: Any):
            if not self.calls:
                assert runtime.opens == []
                assert runtime.turns == []
            return await super().dispatch(**kwargs)

    dispatcher = OrderingDispatcher(
        (
            DispatchCompleted(
                {"type": "Success", "value": {"value": "memory-value"}},
                canonical_json_bytes(
                    {"type": "Success", "value": {"value": "memory-value"}}
                ).decode(),
            ),
            DispatchCompleted(
                {"type": "Success", "value": {"value": "model-value"}},
                canonical_json_bytes(
                    {"type": "Success", "value": {"value": "model-value"}}
                ).decode(),
            ),
        )
    )
    owner = _Owner()

    class OrderedBudgetFactory(_BudgetFactory):
        def create(self, plan: Any) -> BudgetState:

            return super().create(plan)

    factory = OrderedBudgetFactory()
    provider = CodexProvider(cast(AgentRuntime, runtime), cwd_parent=tmp_path)

    outcome = await run_one_shot(
        decisions=TransientModelDecisions(),
        run_id=RunId("initial-read-order"),
        definition=definition,
        inputs=(_input(),),
        as_of=datetime.now(UTC),
        plan=plan,
        source_sections=_sections("canonical"),
        owner=owner,
        permit=_permit(),
        provider=provider,
        dispatcher=dispatcher,
        budget_factory=factory,
        initial_read=InitialReadCall(ToolId("test.observe"), {"value": "memory-query"}),
    )

    assert isinstance(outcome, OneShotCompleted)
    assert cast(FrozenJsonDict, outcome.result)["answer"] == "used observation"
    assert factory.plans == [plan]
    assert len(factory.budgets) == 1
    assert len(dispatcher.calls) == 2
    assert dispatcher.calls[0].budgets is dispatcher.calls[1].budgets is factory.budgets[0]
    initial_lineage = dispatcher.calls[0].lineage
    model_lineage = dispatcher.calls[1].lineage
    assert isinstance(initial_lineage, InitialReadDispatchLineage)
    assert isinstance(model_lineage, IsolatedDispatchLineage)
    assert isinstance(initial_lineage.position, InvocationPosition)
    assert isinstance(model_lineage.position, InvocationPosition)
    assert initial_lineage.position != model_lineage.position
    assert model_lineage.model_step_ordinal == 1
    first_provider_input = cast(TextContent, runtime.turns[0].input[0]).text
    assert "memory-value" in first_provider_input
    assert 'origin="initial_read"' in first_provider_input
    assert "initial_read_position=" not in first_provider_input
    assert "model_step_ordinal=" not in first_provider_input
    assert runtime.opens[0].system[0] == TextContent(KERNEL_BASE_INSTRUCTION)


async def test_declared_initial_read_failure_is_a_typed_first_turn_observation(
    tmp_path: Path,
) -> None:
    definition, plan, _ = _definition(
        mode=SessionMode.isolated,
        structured=True,
        effect=ToolEffect.Read,
    )
    runtime = _Runtime([(_terminal({"type": "finish", "result": {"answer": "no memory"}}),)])
    provider = CodexProvider(cast(AgentRuntime, runtime), cwd_parent=tmp_path)
    dispatcher = ScriptedToolDispatchPort(
        (
            DispatchCompleted(
                {"type": "Failure", "error": {"reason": "not-found"}},
                canonical_json_bytes(
                    {"type": "Failure", "error": {"reason": "not-found"}}
                ).decode(),
            ),
        )
    )

    outcome = await run_one_shot(
        decisions=TransientModelDecisions(),
        run_id=RunId("initial-read-failure"),
        definition=definition,
        inputs=(_input(),),
        as_of=datetime.now(UTC),
        plan=plan,
        source_sections=_sections("canonical"),
        owner=_Owner(),
        permit=_permit(),
        provider=provider,
        dispatcher=dispatcher,
        budget_factory=_budget_factory(),
        initial_read=InitialReadCall(ToolId("test.observe"), {"value": "missing"}),
    )

    assert isinstance(outcome, OneShotCompleted)
    submitted = cast(TextContent, runtime.turns[0].input[0]).text
    assert '"type":"Failure"' in submitted
    assert '"reason":"not-found"' in submitted


@pytest.mark.parametrize("effect", [ToolEffect.Pure, ToolEffect.Write])
async def test_initial_read_rejects_non_read_effects_before_io(
    tmp_path: Path,
    effect: ToolEffect,
) -> None:
    definition, plan, _ = _definition(
        mode=SessionMode.isolated,
        structured=True,
        effect=effect,
    )
    runtime = _Runtime([])
    provider = CodexProvider(cast(AgentRuntime, runtime), cwd_parent=tmp_path)
    owner = _Owner()
    dispatcher = ScriptedToolDispatchPort(())
    factory = _BudgetFactory()

    with pytest.raises(ValueError, match="Read|Write"):
        await run_one_shot(
            decisions=TransientModelDecisions(),
            run_id=RunId(f"reject-{effect.value}"),
            definition=definition,
            inputs=(_input(),),
            as_of=datetime.now(UTC),
            plan=plan,
            source_sections=_sections("canonical"),
            owner=owner,
            permit=_permit(),
            provider=provider,
            dispatcher=dispatcher,
            budget_factory=factory,
            initial_read=InitialReadCall(ToolId("test.observe"), {"value": "x"}),
        )

    assert factory.plans == []

    assert dispatcher.calls == []
    assert runtime.opens == []


@pytest.mark.parametrize(
    "initial_read",
    [
        InitialReadCall(ToolId("test.missing"), {"value": "x"}),
        InitialReadCall(ToolId("test.observe"), {"value": 7}),
    ],
)
async def test_invalid_initial_read_fails_before_admission_tool_or_provider_io(
    tmp_path: Path,
    initial_read: InitialReadCall,
) -> None:
    definition, plan, _ = _definition(
        mode=SessionMode.isolated,
        structured=True,
        effect=ToolEffect.Read,
    )
    runtime = _Runtime([])
    provider = CodexProvider(cast(AgentRuntime, runtime), cwd_parent=tmp_path)
    owner = _Owner()
    dispatcher = ScriptedToolDispatchPort(())
    factory = _BudgetFactory()

    with pytest.raises(ValueError):
        await run_one_shot(
            decisions=TransientModelDecisions(),
            run_id=RunId("invalid-initial-read"),
            definition=definition,
            inputs=(_input(),),
            as_of=datetime.now(UTC),
            plan=plan,
            source_sections=_sections("canonical"),
            owner=owner,
            permit=_permit(),
            provider=provider,
            dispatcher=dispatcher,
            budget_factory=factory,
            initial_read=initial_read,
        )

    assert factory.plans == []

    assert dispatcher.calls == []
    assert runtime.opens == []


async def test_initial_read_tool_in_maximum_but_not_selected_plan_is_ungranted(
    tmp_path: Path,
) -> None:
    first_maximum, _first_plan, first = _authority(ToolEffect.Read)
    assert first is not None
    second_spec = ToolSpec(
        id=ToolId("test.ungranted"),
        summary="Ungrantable observation",
        documentation=PromptDocument("Not selected for this run."),
        input_type=ToolInput,
        success_type=ToolSuccess,
        error_type=NoDeclaredError,
        effect=ToolEffect.Read,
        limits=ToolLimits(1_024, 4_096, 1, 5.0),
    )
    second = ToolBinding(
        spec=second_spec,
        execute=Available(_must_not_execute),
        replay_policy=ReplayPolicy.ReDispatchable,
        implementation_revision="ungranted-v1",
        policy_epoch=PolicyEpoch("v1"),
        policy_inputs={},
    )
    catalog = ToolCatalog.compose((ToolFamily("test", (first.spec, second.spec), (first, second)),))
    maximum = CapabilityProfile(
        ProfileId("maximum-two"),
        (ToolGrant(first.spec.id, None), ToolGrant(second.spec.id, None)),
        first_maximum.run_limits,
    ).freeze(catalog)
    selected = CapabilityProfile(
        ProfileId("selected-one"),
        (ToolGrant(first.spec.id, None),),
        first_maximum.run_limits,
    ).freeze(catalog)
    plan = ToolPlan(selected.id, HostTable()).freeze(catalog, selected)
    definition = AgentDefinition(
        DefinitionId("isolated-ungranted"),
        AgentRole("assistant", _sections("role")),
        _sections("stable"),
        SessionMode.isolated,
        StructuredOutput("answer", StructuredResult),
        maximum,
        ProviderConfiguration(
            CredentialRef("local_account", "test"), "gpt-5", "low", "test-catalog-v1", "a" * 64
        ),
        "ungranted-test-v1",
    )
    runtime = _Runtime([])
    owner = _Owner()
    dispatcher = ScriptedToolDispatchPort(())

    with pytest.raises(ValueError, match="not granted"):
        await run_one_shot(
            decisions=TransientModelDecisions(),
            run_id=RunId("ungranted-initial-read"),
            definition=definition,
            inputs=(_input(),),
            as_of=datetime.now(UTC),
            plan=plan,
            source_sections=_sections("canonical"),
            owner=owner,
            permit=_permit(),
            provider=CodexProvider(cast(AgentRuntime, runtime), cwd_parent=tmp_path),
            dispatcher=dispatcher,
            budget_factory=_budget_factory(),
            initial_read=InitialReadCall(second.spec.id, {"value": "x"}),
        )

    assert dispatcher.calls == []
    assert runtime.opens == []


async def test_stale_initial_read_plan_fails_before_any_external_boundary(
    tmp_path: Path,
) -> None:
    definition, plan, _ = _definition(
        mode=SessionMode.isolated,
        structured=True,
        effect=ToolEffect.Read,
    )
    stale = replace(plan, plan_revision="0" * 64)
    runtime = _Runtime([])
    provider = CodexProvider(cast(AgentRuntime, runtime), cwd_parent=tmp_path)
    owner = _Owner()
    dispatcher = ScriptedToolDispatchPort(())
    factory = _BudgetFactory()

    with pytest.raises(ValueError):
        await run_one_shot(
            decisions=TransientModelDecisions(),
            run_id=RunId("stale-initial-read"),
            definition=definition,
            inputs=(_input(),),
            as_of=datetime.now(UTC),
            plan=stale,
            source_sections=_sections("canonical"),
            owner=owner,
            permit=_permit(),
            provider=provider,
            dispatcher=dispatcher,
            budget_factory=factory,
            initial_read=InitialReadCall(ToolId("test.observe"), {"value": "x"}),
        )

    assert factory.plans == []

    assert dispatcher.calls == []
    assert runtime.opens == []


async def test_initial_read_budget_boundary_is_rendered_without_external_work(
    tmp_path: Path,
) -> None:
    definition, plan, _ = _definition(
        mode=SessionMode.isolated,
        structured=True,
        effect=ToolEffect.Read,
    )
    runtime = _Runtime([(_terminal({"type": "finish", "result": {"answer": "budget closed"}}),)])
    provider = CodexProvider(cast(AgentRuntime, runtime), cwd_parent=tmp_path)
    dispatcher = ScriptedToolDispatchPort(
        (
            DispatchCompleted(
                {"type": "BudgetExceeded"},
                canonical_json_bytes({"type": "BudgetExceeded"}).decode(),
            ),
        )
    )

    outcome = await run_one_shot(
        decisions=TransientModelDecisions(),
        run_id=RunId("initial-read-over-budget"),
        definition=definition,
        inputs=(_input(),),
        as_of=datetime.now(UTC),
        plan=plan,
        source_sections=_sections("canonical"),
        owner=_Owner(),
        permit=_permit(),
        provider=provider,
        dispatcher=dispatcher,
        budget_factory=_budget_factory(),
        initial_read=InitialReadCall(ToolId("test.observe"), {"value": "x"}),
    )

    assert isinstance(outcome, OneShotCompleted)
    assert len(dispatcher.calls) == 1
    assert '"type":"BudgetExceeded"' in cast(TextContent, runtime.turns[0].input[0]).text


async def test_initial_read_cancellation_before_dispatch_and_after_completion(
    tmp_path: Path,
) -> None:
    definition, plan, _ = _definition(
        mode=SessionMode.isolated,
        structured=True,
        effect=ToolEffect.Read,
    )
    initial_read = InitialReadCall(ToolId("test.observe"), {"value": "x"})

    cancelled_before = CancellationToken()
    cancelled_before.cancel()
    before_runtime = _Runtime([])
    before_dispatcher = ScriptedToolDispatchPort(())
    before = await run_one_shot(
        decisions=TransientModelDecisions(),
        run_id=RunId("initial-read-cancelled-before"),
        definition=definition,
        inputs=(_input(),),
        as_of=datetime.now(UTC),
        plan=plan,
        source_sections=_sections("canonical"),
        owner=_Owner(),
        permit=_permit(),
        provider=CodexProvider(cast(AgentRuntime, before_runtime), cwd_parent=tmp_path),
        dispatcher=before_dispatcher,
        budget_factory=_budget_factory(),
        initial_read=initial_read,
        cancellation=cancelled_before,
    )
    assert before.type is OneShotStopKind.cancelled
    assert before_dispatcher.calls == []
    assert before_runtime.opens == []

    cancelled_after = CancellationToken()
    after_runtime = _Runtime([])

    class CancellingDispatcher(ScriptedToolDispatchPort):
        async def dispatch(self, **kwargs: Any):
            result = await super().dispatch(**kwargs)
            cancelled_after.cancel()
            return result

    after_dispatcher = CancellingDispatcher(
        (
            DispatchCompleted(
                {"type": "Success", "value": {"value": "seen"}},
                canonical_json_bytes({"type": "Success", "value": {"value": "seen"}}).decode(),
            ),
        )
    )
    after = await run_one_shot(
        decisions=TransientModelDecisions(),
        run_id=RunId("initial-read-cancelled-after"),
        definition=definition,
        inputs=(_input(),),
        as_of=datetime.now(UTC),
        plan=plan,
        source_sections=_sections("canonical"),
        owner=_Owner(),
        permit=_permit(),
        provider=CodexProvider(cast(AgentRuntime, after_runtime), cwd_parent=tmp_path),
        dispatcher=after_dispatcher,
        budget_factory=_budget_factory(),
        initial_read=initial_read,
        cancellation=cancelled_after,
    )
    assert after.type is OneShotStopKind.cancelled
    assert len(after_dispatcher.calls) == 1
    assert after_runtime.opens == []


async def test_initial_read_observation_context_limit_stops_before_provider(
    tmp_path: Path,
) -> None:
    definition, plan, _ = _definition(
        mode=SessionMode.isolated,
        structured=True,
        effect=ToolEffect.Read,
        limits=KernelLimits(max_new_context_bytes=5_000),
    )
    runtime = _Runtime([])
    provider = CodexProvider(cast(AgentRuntime, runtime), cwd_parent=tmp_path)
    dispatcher = ScriptedToolDispatchPort(
        (
            DispatchCompleted(
                {"type": "Success", "value": {"value": "x" * 10_000}},
                canonical_json_bytes(
                    {"type": "Success", "value": {"value": "x" * 10_000}}
                ).decode(),
            ),
        )
    )
    owner = _Owner()

    outcome = await run_one_shot(
        decisions=TransientModelDecisions(),
        run_id=RunId("initial-read-context-limit"),
        definition=definition,
        inputs=(_input(),),
        as_of=datetime.now(UTC),
        plan=plan,
        source_sections=_sections("canonical"),
        owner=owner,
        permit=_permit(),
        provider=provider,
        dispatcher=dispatcher,
        budget_factory=_budget_factory(),
        initial_read=InitialReadCall(ToolId("test.observe"), {"value": "x"}),
    )

    assert outcome.type is OneShotStopKind.configuration_error
    assert len(dispatcher.calls) == 1
    assert runtime.opens == []


@pytest.mark.parametrize(
    "error",
    [
        ToolDispatchDefect("initial dispatch configuration defect"),
        RecoveryRequired("initial Read requires recovery"),
    ],
)
async def test_initial_read_dispatch_defects_settle_admission_and_open_no_provider(
    tmp_path: Path,
    error: Exception,
) -> None:
    definition, plan, _ = _definition(
        mode=SessionMode.isolated,
        structured=True,
        effect=ToolEffect.Read,
    )
    runtime = _Runtime([])

    class DefectiveDispatcher(ScriptedToolDispatchPort):
        async def dispatch(self, **kwargs: Any):
            await super().dispatch(**kwargs)
            raise error

    dispatcher = DefectiveDispatcher(
        (
            DispatchCompleted(
                {"type": "Success", "value": {"value": "unused"}},
                canonical_json_bytes({"type": "Success", "value": {"value": "unused"}}).decode(),
            ),
        )
    )
    owner = _Owner()

    outcome = await run_one_shot(
        decisions=TransientModelDecisions(),
        run_id=RunId("initial-read-defect"),
        definition=definition,
        inputs=(_input(),),
        as_of=datetime.now(UTC),
        plan=plan,
        source_sections=_sections("canonical"),
        owner=owner,
        permit=_permit(),
        provider=CodexProvider(cast(AgentRuntime, runtime), cwd_parent=tmp_path),
        dispatcher=dispatcher,
        budget_factory=_budget_factory(),
        initial_read=InitialReadCall(ToolId("test.observe"), {"value": "x"}),
    )

    assert outcome.type is OneShotStopKind.configuration_error
    assert len(dispatcher.calls) == 1
    assert runtime.opens == []


async def test_initial_read_commentary_call_is_non_executable_and_usage_settles(
    tmp_path: Path,
) -> None:
    limits = KernelLimits(
        max_provider_turns=1,
        max_provider_input_tokens=10,
        max_provider_output_tokens=2,
    )
    definition, plan, _ = _definition(
        mode=SessionMode.isolated,
        structured=True,
        effect=ToolEffect.Read,
        limits=limits,
    )
    commentary = json.dumps(
        _wire_step(
            {
                "type": "call_tool",
                "tool_id": "test.observe",
                "arguments": {"value": "commentary must not execute"},
            }
        ),
        separators=(",", ":"),
    )
    usage = _usage(10, 2)
    runtime = _Runtime(
        [
            (
                AgentText(commentary),
                _terminal(
                    {"type": "finish", "result": {"answer": "terminal only"}},
                    usage=usage,
                ),
            )
        ]
    )
    dispatcher = ScriptedToolDispatchPort(
        (
            DispatchCompleted(
                {"type": "Success", "value": {"value": "memory"}},
                canonical_json_bytes({"type": "Success", "value": {"value": "memory"}}).decode(),
            ),
        )
    )
    owner = _Owner()

    outcome = await run_one_shot(
        decisions=TransientModelDecisions(),
        run_id=RunId("initial-read-commentary"),
        definition=definition,
        inputs=(_input(),),
        as_of=datetime.now(UTC),
        plan=plan,
        source_sections=_sections("canonical"),
        owner=owner,
        permit=_permit(),
        provider=CodexProvider(cast(AgentRuntime, runtime), cwd_parent=tmp_path),
        dispatcher=dispatcher,
        budget_factory=_budget_factory(),
        initial_read=InitialReadCall(ToolId("test.observe"), {"value": "memory-query"}),
    )

    assert isinstance(outcome, OneShotCompleted)
    assert len(dispatcher.calls) == 1
    assert outcome.metrics.provider_turns == 1
    assert outcome.metrics.usage.input_tokens == 10
    assert outcome.metrics.usage.output_tokens == 2


async def test_isolated_empty_plan_honors_restricted_input_projection(
    tmp_path: Path,
) -> None:
    definition, plan, binding = _definition(
        mode=SessionMode.isolated,
        structured=True,
        input_projection_policy=InputProjectionPolicy(
            render_source_timestamps=False,
            batch_as_of=BatchAsOfMode.never,
        ),
    )
    assert binding is None
    runtime = _Runtime([(_terminal({"type": "finish", "result": {"answer": "yes"}}),)])
    provider = CodexProvider(cast(AgentRuntime, runtime), cwd_parent=tmp_path)

    outcome = await run_one_shot(
        decisions=TransientModelDecisions(),
        run_id=RunId("isolated-projection"),
        definition=definition,
        inputs=(_input(),),
        as_of=datetime.now(UTC),
        plan=plan,
        source_sections=_sections("canonical"),
        owner=_Owner(),
        permit=_permit(),
        provider=provider,
        dispatcher=ScriptedToolDispatchPort(()),
        budget_factory=_budget_factory(),
    )

    assert outcome.type == "completed"
    submitted = cast(TextContent, runtime.turns[0].input[0]).text
    assert 'input_id="input-1"' in submitted
    assert "hello" in submitted
    assert '"count":0' in submitted
    assert "source_timestamp=" not in submitted
    assert "as_of=" not in submitted
    assert len(runtime.closed) == 1


async def test_unauthorized_one_shot_projection_precedes_rendering_admission_and_provider(
    tmp_path: Path,
) -> None:
    definition, plan, _ = _definition(
        mode=SessionMode.isolated,
        structured=True,
        input_projection_policy=InputProjectionPolicy(batch_as_of=BatchAsOfMode.never),
    )
    runtime = _Runtime([])
    provider = CodexProvider(cast(AgentRuntime, runtime), cwd_parent=tmp_path)
    owner = _Owner()
    factory = _BudgetFactory()

    with pytest.raises(ValueError, match="prohibits model-visible batch as_of"):
        await run_one_shot(
            decisions=TransientModelDecisions(),
            run_id=RunId("isolated-unauthorized-projection"),
            definition=definition,
            inputs=(_input(),),
            as_of=datetime.now(UTC),
            plan=plan,
            source_sections=_sections("must not render"),
            owner=owner,
            permit=_permit(),
            provider=provider,
            dispatcher=ScriptedToolDispatchPort(()),
            budget_factory=factory,
            input_projection=InputProjectionRequest(render_batch_as_of=True),
        )

    assert factory.plans == []

    assert runtime.opens == []


async def test_isolated_provider_failure_closes_and_returns_typed_stop(tmp_path: Path) -> None:
    definition, plan, _ = _definition(mode=SessionMode.isolated, structured=True)
    runtime = _Runtime([(_failed_terminal(AgentFailure("backend_failed")),)])
    provider = CodexProvider(cast(AgentRuntime, runtime), cwd_parent=tmp_path)

    outcome = await run_one_shot(
        decisions=TransientModelDecisions(),
        run_id=RunId("isolated-failure"),
        definition=definition,
        inputs=(_input(),),
        as_of=datetime.now(UTC),
        plan=plan,
        source_sections=_sections("canonical"),
        owner=_Owner(),
        permit=_permit(),
        provider=provider,
        dispatcher=ScriptedToolDispatchPort(()),
        budget_factory=_budget_factory(),
    )

    assert outcome.type is OneShotStopKind.provider_error
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
    owner = _Owner()
    factory = _BudgetFactory()

    with pytest.raises(ValueError, match="Write"):
        await run_one_shot(
            decisions=TransientModelDecisions(),
            run_id=RunId("isolated-1"),
            definition=definition,
            inputs=(_input(),),
            as_of=datetime.now(UTC),
            plan=plan,
            source_sections=_sections(),
            owner=owner,
            permit=_permit(),
            provider=provider,
            dispatcher=ScriptedToolDispatchPort(()),
            budget_factory=factory,
        )

    assert factory.plans == []
    assert runtime.opens == []


async def test_isolated_budget_mismatch_is_rejected_before_admission_or_provider(
    tmp_path: Path,
) -> None:
    definition, plan, _ = _definition(mode=SessionMode.isolated, structured=True)
    runtime = _Runtime([])
    provider = CodexProvider(cast(AgentRuntime, runtime), cwd_parent=tmp_path)
    owner = _Owner()
    factory = _BudgetFactory(RunLimits(7, 8, 32_768, 32_768, 1, 30.0))

    with pytest.raises(KernelConfigurationDefect, match="budget limits"):
        await run_one_shot(
            decisions=TransientModelDecisions(),
            run_id=RunId("isolated-budget-mismatch"),
            definition=definition,
            inputs=(_input(),),
            as_of=datetime.now(UTC),
            plan=plan,
            source_sections=_sections("must not render"),
            owner=owner,
            permit=_permit(),
            provider=provider,
            dispatcher=ScriptedToolDispatchPort(()),
            budget_factory=factory,
        )

    assert factory.plans == [plan]

    assert runtime.opens == []


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
        decisions=TransientModelDecisions(),
        run_id=RunId("isolated-1"),
        definition=definition,
        inputs=(_input(),),
        as_of=datetime.now(UTC),
        plan=plan,
        source_sections=_sections("canonical"),
        owner=_Owner(),
        permit=_permit(),
        provider=provider,
        dispatcher=dispatch,
        budget_factory=_budget_factory(),
        cancellation=cancellation,
    )

    assert outcome.type is OneShotStopKind.cancelled
    assert dispatch.calls == []
    assert len(runtime.closed) == 1


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
        decisions=TransientModelDecisions(),
        run_id=RunId("isolated-cancel"),
        definition=definition,
        inputs=(_input(),),
        as_of=datetime.now(UTC),
        plan=plan,
        source_sections=_sections("canonical"),
        owner=_Owner(),
        permit=_permit(),
        provider=provider,
        dispatcher=ScriptedToolDispatchPort(()),
        budget_factory=_budget_factory(),
        cancellation=cancellation,
        event_sink=events,
    )

    assert outcome.type is OneShotStopKind.cancelled
    assert runtime.opens == []
    assert [event.kind for event in events.events].count(EventKind.cancellation) == 1
    assert events.events[-1].kind is EventKind.outcome
    assert events.events[-1].attributes[0].value == OneShotStopKind.cancelled.value


async def test_bounded_event_rejection_never_changes_one_shot_work(tmp_path: Path) -> None:
    definition, plan, _ = _definition(mode=SessionMode.isolated, structured=True)
    runtime = _Runtime([(_terminal({"type": "finish", "result": {"answer": "yes"}}),)])
    provider = CodexProvider(cast(AgentRuntime, runtime), cwd_parent=tmp_path)
    events = RecordingEventSink()

    outcome = await run_one_shot(
        decisions=TransientModelDecisions(),
        run_id=RunId("r" * 257),
        definition=definition,
        inputs=(_input(),),
        as_of=datetime.now(UTC),
        plan=plan,
        source_sections=_sections("canonical"),
        owner=_Owner(),
        permit=_permit(),
        provider=provider,
        dispatcher=ScriptedToolDispatchPort(()),
        budget_factory=_budget_factory(),
        event_sink=events,
    )

    assert outcome.type == "completed"
    assert events.events == []
