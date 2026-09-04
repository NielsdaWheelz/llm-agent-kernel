from __future__ import annotations

import json
from collections import deque
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

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
    AgentRuntime,
    AgentSession,
    AgentSessionRef,
    AgentSessionRequest,
    AgentTerminal,
    CredentialRef,
    ResumeSession,
    SessionUnavailable,
    TextContent,
    TurnRequest,
    freeze_json_object,
)
from provider_runtime.types import Absent, CancelSignal
from pydantic import BaseModel, ConfigDict

from llm_agent_kernel import (
    AdmissionGranted,
    AdmissionRequest,
    AgentDefinition,
    AgentRole,
    AppendInputs,
    Checkpoint,
    ClaimAcquired,
    ClaimId,
    ClaimNoWork,
    CodexProvider,
    ConversationalOutput,
    ConversationConclusion,
    DefinitionId,
    DispatchCompleted,
    DispatchSuspended,
    HostInput,
    HostRef,
    InMemoryAdmissionPort,
    InMemoryInputCheckpointPort,
    InMemorySessionRefPort,
    InputClaim,
    InputId,
    IsolatedDispatchLineage,
    KernelLimits,
    NoNewInput,
    OneShotCompleted,
    OwnerToken,
    Preempt,
    ProviderConfiguration,
    RunId,
    ScriptedToolDispatchPort,
    SessionCoordinator,
    SessionMode,
    SettleMoreInput,
    StaticContextSource,
    StoppedConclusion,
    StopReason,
    StructuredOutput,
    SuspensionConclusion,
    ThreadId,
    ThreadStopKind,
    WaitingFor,
    run_one_shot,
    run_thread,
)

AS_OF = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
RUN_LIMITS = RunLimits(8, 8, 32_768, 32_768, 1, 30.0)


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


def _sections(text: str) -> PromptSections:
    return PromptSections((PromptSection(PromptSectionKind("context"), (), PromptText(text)),))


def _definition(
    *,
    mode: SessionMode = SessionMode.continuing,
    structured: bool = False,
    effect: ToolEffect = ToolEffect.Read,
    replay_policy: ReplayPolicy = ReplayPolicy.ReDispatchable,
    limits: KernelLimits | None = None,
) -> tuple[AgentDefinition, Any]:
    spec = ToolSpec(
        id=ToolId("test.observe"),
        summary="Observe a bounded value",
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
        replay_policy=replay_policy,
        implementation_revision="observe-v1",
        policy_epoch=PolicyEpoch("v1"),
        policy_inputs={},
    )
    catalog = ToolCatalog.compose((ToolFamily("test", (spec,), (binding,)),))
    maximum = CapabilityProfile(
        ProfileId("maximum"),
        (ToolGrant(spec.id, None),),
        RUN_LIMITS,
    ).freeze(catalog)
    plan = ToolPlan(maximum.id, HostTable()).freeze(catalog, maximum)
    definition = AgentDefinition(
        DefinitionId("assistant"),
        AgentRole("assistant", _sections("role")),
        _sections("stable"),
        mode,
        StructuredOutput("answer", StructuredResult) if structured else ConversationalOutput(),
        maximum,
        ProviderConfiguration(CredentialRef("local_account", "test"), "gpt-5"),
        "composed-test-v1",
        limits or KernelLimits(),
    )
    return definition, plan


def _input(name: str, text: str) -> HostInput:
    return HostInput(InputId(name), _sections(text), AS_OF)


def _claim(
    plan: Any,
    *,
    name: str,
    text: str,
    attempt: int = 1,
) -> InputClaim:
    return InputClaim(
        ClaimId(f"claim-{name}"),
        (_input(f"input-{name}", text),),
        Checkpoint(f"checkpoint-{name}"),
        AS_OF,
        plan,
        attempt,
    )


def _ref(index: int) -> AgentSessionRef:
    return AgentSessionRef(
        "agent-session-ref.v1",
        "codex",
        "sdk",
        f"session-{index}",
        "test",
        "1" * 64,
        "2" * 64,
    )


class _Runtime:
    def __init__(
        self,
        steps: list[dict[str, object]],
        *,
        reject_next_resume: bool = False,
    ) -> None:
        self.steps = deque(steps)
        self.reject_next_resume = reject_next_resume
        self.opens: list[AgentSessionRequest] = []
        self.turns: list[TurnRequest] = []
        self.closed: list[AgentSession] = []
        self._sessions = 0

    async def open_session(self, request: AgentSessionRequest) -> AgentSession:
        self.opens.append(request)
        if isinstance(request.open, ResumeSession) and self.reject_next_resume:
            self.reject_next_resume = False
            raise SessionUnavailable("scripted discarded session")
        self._sessions += 1
        ref = request.open.ref if isinstance(request.open, ResumeSession) else _ref(self._sessions)
        return AgentSession(ref)

    async def stream_turn(
        self,
        session: AgentSession,
        request: TurnRequest,
        *,
        approvals: object | None = None,
        cancel: CancelSignal | None = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        del approvals, cancel
        self.turns.append(request)
        yield AgentTerminal(
            status="succeeded",
            failure=None,
            final_text="untrusted projection",
            session_ref=session.ref,
            structured_output=freeze_json_object(_wire_step(self.steps.popleft())),
            usage=Absent(),
        )

    async def run_turn(self, *_args: object, **_kwargs: object) -> AgentTerminal:
        raise AssertionError("the kernel must consume stream_turn")

    async def close_session(self, session: AgentSession) -> None:
        self.closed.append(session)


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


class _Budgets:
    def __init__(self) -> None:
        self.limits = RUN_LIMITS

    @property
    def remaining_elapsed_seconds(self) -> float:
        return 30.0

    async def reserve(self, *_args: object, **_kwargs: object) -> bool:
        raise AssertionError("scripted dispatch owns no llm-tools budget state")

    async def settle(self, *_args: object, **_kwargs: object) -> None:
        raise AssertionError("scripted dispatch owns no llm-tools budget state")


class _BudgetFactory:
    def create(self, plan: Any) -> BudgetState:
        assert plan.profile.run_limits == RUN_LIMITS
        return cast(BudgetState, _Budgets())


async def _run_thread(
    *,
    run_id: str,
    definition: AgentDefinition,
    checkpoints: InMemoryInputCheckpointPort,
    admission: InMemoryAdmissionPort,
    sessions: SessionCoordinator,
    dispatcher: ScriptedToolDispatchPort,
    plan: Any,
    context_source: StaticContextSource | None = None,
):
    return await run_thread(
        run_id=RunId(run_id),
        thread_id=ThreadId("thread-1"),
        owner_token=OwnerToken("owner-1"),
        definition=definition,
        checkpoints=checkpoints,
        admission=admission,
        sessions=sessions,
        context_source=context_source or StaticContextSource(_sections("canonical")),
        dispatcher=dispatcher,
        budget_factory=_BudgetFactory(),
    )


async def test_suspension_resolution_cold_bootstraps_from_host_evidence(
    tmp_path: Path,
) -> None:
    definition, plan = _definition(effect=ToolEffect.Write)
    resolution = (
        'host_ref="action-42" tool_id="test.observe" '
        'original_arguments={"value":"original"} resolution="succeeded" '
        'evidence={"receipt":"receipt-9","value":"resolved"}'
    )
    proposing = _claim(plan, name="proposal", text="perform the write")
    resolved = _claim(plan, name="resolution", text=resolution)
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(proposing), ClaimAcquired(resolved)))
    dispatcher = ScriptedToolDispatchPort(
        (DispatchSuspended(HostRef("action-42"), WaitingFor.system),)
    )
    runtime = _Runtime(
        [
            {
                "type": "call_tool",
                "tool_id": "test.observe",
                "arguments": {"value": "original"},
            },
            {"type": "say", "text": "resolved from durable evidence"},
        ],
        reject_next_resume=True,
    )
    provider = CodexProvider(
        cast(AgentRuntime, runtime),
        cwd_parent=tmp_path,
        cache_continuing=False,
    )
    sessions = SessionCoordinator(provider, InMemorySessionRefPort())
    admission = InMemoryAdmissionPort(max_live_slots=1)
    source = StaticContextSource(_sections("canonical action history"))
    try:
        first = await _run_thread(
            run_id="run-proposal",
            definition=definition,
            checkpoints=checkpoints,
            admission=admission,
            sessions=sessions,
            dispatcher=dispatcher,
            plan=plan,
            context_source=source,
        )
        second = await _run_thread(
            run_id="run-resolution",
            definition=definition,
            checkpoints=checkpoints,
            admission=admission,
            sessions=sessions,
            dispatcher=dispatcher,
            plan=plan,
            context_source=source,
        )
    finally:
        await provider.shutdown()

    assert first.type == "suspended"
    assert second.type == "completed"
    assert dispatcher.calls[0].validated_input == ToolInput(value="original")
    assert [record.conclusion for record in checkpoints.settlements] == [
        SuspensionConclusion(HostRef("action-42"), WaitingFor.system),
        ConversationConclusion("resolved from durable evidence"),
    ]
    assert len(source.bootstrap_calls) == 2
    assert len(runtime.opens) == 3
    assert isinstance(runtime.opens[1].open, ResumeSession)
    rendered_resolution = "\n".join(
        part.text for part in runtime.turns[1].input if isinstance(part, TextContent)
    )
    assert resolution in rendered_resolution
    assert admission.live_slots == 0


async def test_discarded_billed_once_read_can_dispatch_again(tmp_path: Path) -> None:
    definition, plan = _definition(
        mode=SessionMode.isolated,
        structured=True,
        effect=ToolEffect.Read,
        replay_policy=ReplayPolicy.BilledOnce,
    )
    runtime = _Runtime(
        [
            {
                "type": "call_tool",
                "tool_id": "test.observe",
                "arguments": {"value": "same logical read"},
            },
            {"type": "finish", "result": {"answer": "first"}},
            {
                "type": "call_tool",
                "tool_id": "test.observe",
                "arguments": {"value": "same logical read"},
            },
            {"type": "finish", "result": {"answer": "second"}},
        ]
    )
    provider = CodexProvider(cast(AgentRuntime, runtime), cwd_parent=tmp_path)
    dispatcher = ScriptedToolDispatchPort(
        (
            DispatchCompleted({"type": "Success", "value": {"value": "observed"}}),
            DispatchCompleted({"type": "Success", "value": {"value": "observed"}}),
        )
    )
    admission = InMemoryAdmissionPort()
    try:
        first = await run_one_shot(
            run_id=RunId("isolated-first"),
            definition=definition,
            inputs=(_input("read", "read the value"),),
            as_of=AS_OF,
            plan=plan,
            source_sections=_sections("canonical"),
            admission=admission,
            provider=provider,
            dispatcher=dispatcher,
            budget_factory=_BudgetFactory(),
        )
        second = await run_one_shot(
            run_id=RunId("isolated-second"),
            definition=definition,
            inputs=(_input("read", "read the value"),),
            as_of=AS_OF,
            plan=plan,
            source_sections=_sections("canonical"),
            admission=admission,
            provider=provider,
            dispatcher=dispatcher,
            budget_factory=_BudgetFactory(),
        )
    finally:
        await provider.shutdown()

    assert isinstance(first, OneShotCompleted)
    assert isinstance(second, OneShotCompleted)
    assert len(dispatcher.calls) == 2
    assert [call.validated_input for call in dispatcher.calls] == [
        ToolInput(value="same logical read"),
        ToolInput(value="same logical read"),
    ]
    assert [call.binding.replay_policy for call in dispatcher.calls] == [
        ReplayPolicy.BilledOnce,
        ReplayPolicy.BilledOnce,
    ]
    assert [call.lineage for call in dispatcher.calls] == [
        IsolatedDispatchLineage(RunId("isolated-first"), 1),
        IsolatedDispatchLineage(RunId("isolated-second"), 1),
    ]
    assert len(runtime.closed) == 2
    assert admission.live_slots == 0


async def test_poison_input_is_consumed_and_next_scan_finds_no_work(
    tmp_path: Path,
) -> None:
    definition, plan = _definition(limits=KernelLimits(max_protocol_repairs=0))
    poison = _claim(plan, name="poison", text="malformed model response")
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(poison), ClaimNoWork()))
    runtime = _Runtime([{"type": "say", "text": "", "extra": True}])
    provider = CodexProvider(cast(AgentRuntime, runtime), cwd_parent=tmp_path)
    sessions = SessionCoordinator(provider, InMemorySessionRefPort())
    admission = InMemoryAdmissionPort()
    dispatcher = ScriptedToolDispatchPort(())
    try:
        first = await _run_thread(
            run_id="run-poison",
            definition=definition,
            checkpoints=checkpoints,
            admission=admission,
            sessions=sessions,
            dispatcher=dispatcher,
            plan=plan,
        )
        second = await _run_thread(
            run_id="run-scan",
            definition=definition,
            checkpoints=checkpoints,
            admission=admission,
            sessions=sessions,
            dispatcher=dispatcher,
            plan=plan,
        )
    finally:
        await provider.shutdown()

    assert first.type is ThreadStopKind.protocol_error
    assert first.metrics.input_consumed is True
    assert second.type == "no_work"
    assert checkpoints.settlements[0].conclusion == StoppedConclusion(StopReason.protocol_error)
    assert checkpoints.release_reasons == []
    assert len(runtime.turns) == 1


async def test_orphan_recovery_keeps_capacity_charge_and_allows_attempt_two(
    tmp_path: Path,
) -> None:
    limits = KernelLimits(
        max_provider_turns=2,
        max_provider_input_tokens=10,
        max_provider_output_tokens=10,
    )
    definition, plan = _definition(limits=limits)
    admission = InMemoryAdmissionPort(
        max_turns=6,
        max_input_tokens=30,
        max_output_tokens=30,
    )
    orphan = await admission.reserve(
        AdmissionRequest(
            RunId("run-crashed"),
            ThreadId("thread-1"),
            1,
            2,
            10,
            10,
        )
    )
    assert isinstance(orphan, AdmissionGranted)
    assert admission.live_slots == 1
    assert await admission.recover_orphans() == (RunId("run-crashed"),)
    assert admission.live_slots == 0
    assert (
        admission.charged_turns,
        admission.charged_input_tokens,
        admission.charged_output_tokens,
    ) == (2, 10, 10)

    retry = _claim(
        plan,
        name="retry",
        text="canonical unresolved input after startup scan",
        attempt=2,
    )
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(retry),))
    runtime = _Runtime([{"type": "say", "text": "recovered"}])
    provider = CodexProvider(cast(AgentRuntime, runtime), cwd_parent=tmp_path)
    sessions = SessionCoordinator(provider, InMemorySessionRefPort())
    try:
        outcome = await _run_thread(
            run_id="run-retry",
            definition=definition,
            checkpoints=checkpoints,
            admission=admission,
            sessions=sessions,
            dispatcher=ScriptedToolDispatchPort(()),
            plan=plan,
        )
    finally:
        await provider.shutdown()

    assert outcome.type == "completed"
    assert checkpoints.settlements[0].conclusion == ConversationConclusion("recovered")
    assert admission.live_slots == 0
    assert admission.charged_turns == 3
    assert admission.charged_input_tokens == 20
    assert admission.charged_output_tokens == 20


async def test_finalization_race_preserves_answer_then_claims_follow_up(
    tmp_path: Path,
) -> None:
    definition, plan = _definition()
    original = _claim(plan, name="original", text="first request")
    follow_up_input = _input("follow-up", "ordinary follow-up")
    follow_up = InputClaim(
        ClaimId("claim-follow-up"),
        (follow_up_input,),
        Checkpoint("checkpoint-follow-up"),
        AS_OF,
        plan,
        1,
    )
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(original), ClaimAcquired(follow_up)))
    checkpoints.queue_poll(
        original.claim_id,
        NoNewInput(),
        AppendInputs(
            (follow_up_input,),
            Checkpoint("checkpoint-follow-up"),
            AS_OF,
        ),
    )
    checkpoints.settle_results.append(SettleMoreInput())
    runtime = _Runtime(
        [
            {"type": "say", "text": "first answer"},
            {"type": "say", "text": "follow-up answer"},
        ]
    )
    provider = CodexProvider(cast(AgentRuntime, runtime), cwd_parent=tmp_path)
    sessions = SessionCoordinator(provider, InMemorySessionRefPort())
    admission = InMemoryAdmissionPort()
    try:
        first = await _run_thread(
            run_id="run-original",
            definition=definition,
            checkpoints=checkpoints,
            admission=admission,
            sessions=sessions,
            dispatcher=ScriptedToolDispatchPort(()),
            plan=plan,
        )
        second = await _run_thread(
            run_id="run-follow-up",
            definition=definition,
            checkpoints=checkpoints,
            admission=admission,
            sessions=sessions,
            dispatcher=ScriptedToolDispatchPort(()),
            plan=plan,
        )
    finally:
        await provider.shutdown()

    assert first.type == "completed"
    assert second.type == "completed"
    assert [record.through_checkpoint for record in checkpoints.settlements] == [
        Checkpoint("checkpoint-original"),
        Checkpoint("checkpoint-follow-up"),
    ]
    assert [record.conclusion for record in checkpoints.settlements] == [
        ConversationConclusion("first answer"),
        ConversationConclusion("follow-up answer"),
    ]
    assert "ordinary follow-up" in "\n".join(
        part.text for part in runtime.turns[1].input if isinstance(part, TextContent)
    )
    assert admission.live_slots == 0


async def test_post_terminal_preemption_recovers_same_input_on_attempt_two(
    tmp_path: Path,
) -> None:
    definition, plan = _definition()
    first_claim = _claim(plan, name="attempt-1", text="logical input")
    retry_claim = _claim(
        plan,
        name="attempt-2",
        text="logical input",
        attempt=2,
    )
    checkpoints = InMemoryInputCheckpointPort(
        (ClaimAcquired(first_claim), ClaimAcquired(retry_claim))
    )
    checkpoints.queue_poll(
        first_claim.claim_id,
        NoNewInput(),
        Preempt("host requested recovery before settlement"),
    )
    runtime = _Runtime(
        [
            {"type": "say", "text": "speculative answer"},
            {"type": "say", "text": "recovered answer"},
        ]
    )
    provider = CodexProvider(
        cast(AgentRuntime, runtime),
        cwd_parent=tmp_path,
        cache_continuing=False,
    )
    references = InMemorySessionRefPort()
    sessions = SessionCoordinator(provider, references)
    admission = InMemoryAdmissionPort()
    source = StaticContextSource(_sections("canonical"))
    try:
        first = await _run_thread(
            run_id="run-attempt-1",
            definition=definition,
            checkpoints=checkpoints,
            admission=admission,
            sessions=sessions,
            dispatcher=ScriptedToolDispatchPort(()),
            plan=plan,
            context_source=source,
        )
        assert await references.load(ThreadId("thread-1"), definition.fingerprint) is None
        second = await _run_thread(
            run_id="run-attempt-2",
            definition=definition,
            checkpoints=checkpoints,
            admission=admission,
            sessions=sessions,
            dispatcher=ScriptedToolDispatchPort(()),
            plan=plan,
            context_source=source,
        )
    finally:
        await provider.shutdown()

    assert first.type is ThreadStopKind.preempted
    assert first.metrics.input_consumed is False
    assert second.type == "completed"
    assert checkpoints.release_reasons == [(first_claim.claim_id, "preempted by host policy")]
    assert [record.conclusion for record in checkpoints.settlements] == [
        ConversationConclusion("recovered answer")
    ]
    assert [claim.attempt_number for claim in (first_claim, retry_claim)] == [1, 2]
    assert len(source.bootstrap_calls) == 2
    assert all(not isinstance(request.open, ResumeSession) for request in runtime.opens)
    assert admission.live_slots == 0


async def test_appended_steering_settles_advanced_checkpoint_then_no_work(
    tmp_path: Path,
) -> None:
    definition, plan = _definition()
    claim = _claim(plan, name="base", text="base request")
    steering = _input("steering", "urgent steering")
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim), ClaimNoWork()))
    checkpoints.queue_poll(
        claim.claim_id,
        NoNewInput(),
        AppendInputs(
            (steering,),
            Checkpoint("checkpoint-steered"),
            AS_OF,
        ),
    )
    dispatcher = ScriptedToolDispatchPort(
        (DispatchCompleted({"type": "Success", "value": {"value": "seen"}}),)
    )
    runtime = _Runtime(
        [
            {
                "type": "call_tool",
                "tool_id": "test.observe",
                "arguments": {"value": "base"},
            },
            {"type": "say", "text": "steering handled"},
        ]
    )
    provider = CodexProvider(cast(AgentRuntime, runtime), cwd_parent=tmp_path)
    sessions = SessionCoordinator(provider, InMemorySessionRefPort())
    admission = InMemoryAdmissionPort()
    try:
        first = await _run_thread(
            run_id="run-steering",
            definition=definition,
            checkpoints=checkpoints,
            admission=admission,
            sessions=sessions,
            dispatcher=dispatcher,
            plan=plan,
        )
        second = await _run_thread(
            run_id="run-scan-after-steering",
            definition=definition,
            checkpoints=checkpoints,
            admission=admission,
            sessions=sessions,
            dispatcher=dispatcher,
            plan=plan,
        )
    finally:
        await provider.shutdown()

    assert first.type == "completed"
    assert second.type == "no_work"
    assert checkpoints.settlements[0].through_checkpoint == Checkpoint("checkpoint-steered")
    assert checkpoints.settlements[0].conclusion == ConversationConclusion("steering handled")
    assert dispatcher.calls == []
    visible_turn_text = [
        part.text for turn in runtime.turns for part in turn.input if isinstance(part, TextContent)
    ]
    assert sum("urgent steering" in text for text in visible_turn_text) == 1
    assert checkpoints.release_reasons == []
    assert admission.live_slots == 0


async def test_attempt_progression_stops_third_claim_before_admission_or_provider(
    tmp_path: Path,
) -> None:
    definition, plan = _definition(limits=KernelLimits(max_no_progress_attempts=2))
    logical_input = _input("logical", "same unresolved logical input")
    claims = tuple(
        InputClaim(
            ClaimId(f"claim-attempt-{attempt}"),
            (logical_input,),
            Checkpoint("checkpoint-logical"),
            AS_OF,
            plan,
            attempt,
        )
        for attempt in (1, 2, 3)
    )
    checkpoints = InMemoryInputCheckpointPort(tuple(ClaimAcquired(claim) for claim in claims))
    for claim in claims[:2]:
        checkpoints.queue_poll(
            claim.claim_id,
            NoNewInput(),
            Preempt("recoverable interruption before settlement"),
        )
    runtime = _Runtime(
        [
            {"type": "say", "text": "speculative attempt one"},
            {"type": "say", "text": "speculative attempt two"},
        ]
    )
    provider = CodexProvider(
        cast(AgentRuntime, runtime),
        cwd_parent=tmp_path,
        cache_continuing=False,
    )
    sessions = SessionCoordinator(provider, InMemorySessionRefPort())
    admission = InMemoryAdmissionPort()
    try:
        first = await _run_thread(
            run_id="run-attempt-1",
            definition=definition,
            checkpoints=checkpoints,
            admission=admission,
            sessions=sessions,
            dispatcher=ScriptedToolDispatchPort(()),
            plan=plan,
        )
        second = await _run_thread(
            run_id="run-attempt-2",
            definition=definition,
            checkpoints=checkpoints,
            admission=admission,
            sessions=sessions,
            dispatcher=ScriptedToolDispatchPort(()),
            plan=plan,
        )
        charged_before_ceiling = (
            admission.charged_turns,
            admission.charged_input_tokens,
            admission.charged_output_tokens,
        )
        provider_boundaries_before_ceiling = (len(runtime.opens), len(runtime.turns))
        third = await _run_thread(
            run_id="run-attempt-3",
            definition=definition,
            checkpoints=checkpoints,
            admission=admission,
            sessions=sessions,
            dispatcher=ScriptedToolDispatchPort(()),
            plan=plan,
        )
    finally:
        await provider.shutdown()

    assert [first.type, second.type, third.type] == [
        ThreadStopKind.preempted,
        ThreadStopKind.preempted,
        ThreadStopKind.provider_error,
    ]
    assert [claim.attempt_number for claim in claims] == [1, 2, 3]
    assert first.metrics.input_consumed is False
    assert second.metrics.input_consumed is False
    assert third.metrics.input_consumed is True
    assert third.metrics.provider_turns == 0
    assert (len(runtime.opens), len(runtime.turns)) == provider_boundaries_before_ceiling
    assert (
        admission.charged_turns,
        admission.charged_input_tokens,
        admission.charged_output_tokens,
    ) == charged_before_ceiling
    assert [record.conclusion for record in checkpoints.settlements] == [
        StoppedConclusion(StopReason.provider_error)
    ]
    assert [claim_id for claim_id, _reason in checkpoints.release_reasons] == [
        claims[0].claim_id,
        claims[1].claim_id,
    ]
    assert admission.live_slots == 0
