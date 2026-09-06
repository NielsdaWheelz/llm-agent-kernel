"""Paid opt-in qualification of the exact contained Codex stream boundary.

Run only with an existing private provider-runtime state root and local-account
profile:

    LLM_AGENT_KERNEL_LIVE=1 \
    LLM_AGENT_KERNEL_STATE_ROOT=/absolute/private/root \
    LLM_AGENT_KERNEL_PROFILE=profile \
    uv run pytest -m live tests/live/test_codex_qualification.py
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from llm_tools import (
    Available,
    BudgetState,
    CapabilityProfile,
    FrozenToolPlan,
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
    AgentQuotaExhausted,
    AgentRuntime,
    AgentRuntimeConfig,
    AgentSession,
    AgentText,
    ApprovalHandler,
    CredentialRef,
    TextContent,
    TurnNotStarted,
    TurnRequest,
)
from provider_runtime.types import Absent, CancelSignal, Present
from pydantic import BaseModel, ConfigDict

from llm_agent_kernel.cancellation import CancellationToken
from llm_agent_kernel.context import bootstrap_context
from llm_agent_kernel.definitions import (
    AgentDefinition,
    AgentRole,
    BatchAsOfMode,
    ConversationalOutput,
    DefinitionId,
    DispatchCompleted,
    FinishStep,
    HostInput,
    InitialReadCall,
    InputId,
    InputProjectionPolicy,
    InputProjectionRequest,
    OneShotCompleted,
    OutputContract,
    ProviderConfiguration,
    ProviderUsage,
    RunId,
    SessionMode,
    StructuredOutput,
)
from llm_agent_kernel.fakes import InMemoryAdmissionPort, ScriptedToolDispatchPort
from llm_agent_kernel.kernel import run_one_shot
from llm_agent_kernel.protocol import validate_provider_step
from llm_agent_kernel.provider import CodexProvider
from llm_agent_kernel.tools import ValidatedToolCall

pytestmark = pytest.mark.live


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.fail(f"live qualification requires {name}", pytrace=False)
    return value


class _ObservingAgentRuntime(AgentRuntime):
    """Live-only witness proving the kernel ignores streamed assistant text."""

    def __init__(self, config: AgentRuntimeConfig) -> None:
        super().__init__(config)
        self.observed_text: list[str] = []
        self.observed_requests: list[TurnRequest] = []

    async def stream_turn(
        self,
        session: AgentSession,
        request: TurnRequest,
        *,
        approvals: ApprovalHandler | None = None,
        cancel: CancelSignal | None = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        self.observed_requests.append(request)
        async for event in super().stream_turn(
            session,
            request,
            approvals=approvals,
            cancel=cancel,
        ):
            if isinstance(event, AgentText):
                self.observed_text.append(event.text)
            yield event


class LiveNestedResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    note: str | None = None


class LiveStructuredResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    count: int | None = None
    nested: LiveNestedResult


class LiveToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str


class LiveToolSuccess(BaseModel):
    model_config = ConfigDict(extra="forbid")

    echoed: str


class _LiveBudgets:
    def __init__(self, limits: RunLimits) -> None:
        self.limits = limits

    @property
    def remaining_elapsed_seconds(self) -> float:
        return self.limits.max_elapsed_seconds

    async def reserve(self, *_args: object, **_kwargs: object) -> bool:
        raise AssertionError("scripted live dispatcher must not reserve directly")

    async def settle(self, *_args: object, **_kwargs: object) -> None:
        raise AssertionError("scripted live dispatcher must not settle directly")


class _LiveBudgetFactory:
    def create(self, plan: FrozenToolPlan) -> BudgetState:
        return cast(BudgetState, _LiveBudgets(plan.profile.run_limits))


async def _must_not_execute(value: object, context: object) -> object:
    raise AssertionError(f"live schema qualification dispatched: {value!r}, {context!r}")


def _definition(
    profile_key: str,
    *,
    output_contract: OutputContract | None = None,
    session_mode: SessionMode = SessionMode.continuing,
    input_projection_policy: InputProjectionPolicy | None = None,
) -> AgentDefinition:
    empty_catalog = ToolCatalog.compose(())
    maximum = CapabilityProfile(
        ProfileId("live-empty"),
        (),
        RunLimits(1, 1, 4_096, 4_096, 1, 600.0),
    ).freeze(empty_catalog)
    return AgentDefinition(
        DefinitionId("live-codex"),
        AgentRole("probe", PromptSections(())),
        PromptSections(()),
        session_mode,
        output_contract or ConversationalOutput(),
        maximum,
        ProviderConfiguration(
            CredentialRef("local_account", profile_key),
            os.environ.get("LLM_AGENT_KERNEL_MODEL", "gpt-5"),
        ),
        "live-qualification-v1",
        input_projection_policy=input_projection_policy or InputProjectionPolicy(),
    )


def _initial_read_definition(profile_key: str) -> tuple[AgentDefinition, FrozenToolPlan]:
    spec = ToolSpec(
        id=ToolId("live.initial_read"),
        summary="Return one qualified initial observation",
        documentation=PromptDocument("Read one known qualification value."),
        input_type=LiveToolInput,
        success_type=LiveToolSuccess,
        error_type=NoDeclaredError,
        effect=ToolEffect.Read,
        limits=ToolLimits(4_096, 4_096, 1, 30.0),
    )
    binding = ToolBinding(
        spec=spec,
        execute=Available(_must_not_execute),
        replay_policy=ReplayPolicy.ReDispatchable,
        implementation_revision="live-initial-read-v1",
        policy_epoch=PolicyEpoch("v1"),
        policy_inputs={},
    )
    catalog = ToolCatalog.compose((ToolFamily("live", (spec,), (binding,)),))
    maximum = CapabilityProfile(
        ProfileId("live-initial-read"),
        (ToolGrant(spec.id, None),),
        RunLimits(2, 2, 8_192, 8_192, 1, 600.0),
    ).freeze(catalog)
    plan = ToolPlan(maximum.id, HostTable()).freeze(catalog, maximum)
    definition = AgentDefinition(
        DefinitionId("live-initial-read"),
        AgentRole("probe", PromptSections(())),
        PromptSections(()),
        SessionMode.isolated,
        StructuredOutput("live_initial_read_result", LiveStructuredResult),
        maximum,
        ProviderConfiguration(
            CredentialRef("local_account", profile_key),
            os.environ.get("LLM_AGENT_KERNEL_MODEL", "gpt-5"),
        ),
        "live-initial-read-v1",
    )
    return definition, plan


async def test_live_codex_stream_continuation_and_cancellation() -> None:
    if _required_environment("LLM_AGENT_KERNEL_LIVE") != "1":
        pytest.fail("LLM_AGENT_KERNEL_LIVE must equal 1", pytrace=False)
    state_root = Path(_required_environment("LLM_AGENT_KERNEL_STATE_ROOT"))
    if not state_root.is_absolute() or not state_root.is_dir():
        pytest.fail("LLM_AGENT_KERNEL_STATE_ROOT must be an existing absolute directory")
    definition = _definition(_required_environment("LLM_AGENT_KERNEL_PROFILE"))
    runtime = AgentRuntime(AgentRuntimeConfig(state_root_base=state_root))
    provider = CodexProvider(runtime, cwd_parent=state_root, cache_continuing=False)
    try:
        lease = await provider.acquire_continuing(definition, None)
        first = await provider.run_observed_turn(
            lease,
            (
                TextContent(
                    "Without invoking native tools or requesting permission, respond through "
                    "the say branch with the text pong."
                ),
            ),
            CancellationToken(),
            timeout_seconds=600.0,
        )
        assert first.status == "succeeded"
        validate_provider_step(first.structured_output, definition.output_contract, _empty_plan())
        assert isinstance(first.usage, Present)
        assert await provider.accumulated_usage(lease) == ProviderUsage(
            first.usage.value.input_tokens,
            first.usage.value.output_tokens,
        )

        second = await provider.run_observed_turn(
            lease,
            (TextContent("Respond through the say branch with the text pong again."),),
            CancellationToken(),
            timeout_seconds=600.0,
        )
        assert second.status == "succeeded"
        validate_provider_step(second.structured_output, definition.output_contract, _empty_plan())
        assert isinstance(second.usage, Present)
        assert await provider.accumulated_usage(lease) == ProviderUsage(
            first.usage.value.input_tokens + second.usage.value.input_tokens,
            first.usage.value.output_tokens + second.usage.value.output_tokens,
        )
        await provider.release(lease)

        continued = await provider.acquire_continuing(definition, second.session_ref)
        resumed = await provider.run_observed_turn(
            continued,
            (TextContent("Respond through the finish branch with no internal reason."),),
            CancellationToken(),
            timeout_seconds=600.0,
        )
        assert resumed.status == "succeeded"
        validate_provider_step(resumed.structured_output, definition.output_contract, _empty_plan())
        assert resumed.session_ref.native_session_id == first.session_ref.native_session_id
        if isinstance(resumed.usage, Present):
            assert await provider.accumulated_usage(continued) == ProviderUsage(
                resumed.usage.value.input_tokens,
                resumed.usage.value.output_tokens,
            )
        else:
            assert isinstance(resumed.usage, Absent)
            assert await provider.accumulated_usage(continued) == ProviderUsage()
        await provider.release(continued)

        cancelled = await provider.acquire_continuing(definition, resumed.session_ref)
        cancellation = CancellationToken()
        cancellation.cancel()
        with pytest.raises(TurnNotStarted, match="cancel"):
            await provider.run_observed_turn(
                cancelled,
                (TextContent("This turn must not start."),),
                cancellation,
            )
    finally:
        await provider.shutdown()
        await runtime.close()


async def test_live_in_flight_cancellation() -> None:
    if os.environ.get("LLM_AGENT_KERNEL_LIVE_IN_FLIGHT_CANCEL") != "1":
        pytest.skip("set LLM_AGENT_KERNEL_LIVE_IN_FLIGHT_CANCEL=1 for the paid cancellation probe")
    state_root = Path(_required_environment("LLM_AGENT_KERNEL_STATE_ROOT"))
    definition = _definition(_required_environment("LLM_AGENT_KERNEL_PROFILE"))
    runtime = AgentRuntime(AgentRuntimeConfig(state_root_base=state_root))
    provider = CodexProvider(runtime, cwd_parent=state_root, cache_continuing=False)
    cancellation = CancellationToken()
    try:
        lease = await provider.acquire_continuing(definition, None)
        asyncio.get_running_loop().call_later(0.05, cancellation.cancel)
        try:
            terminal = await provider.run_observed_turn(
                lease,
                (
                    TextContent(
                        "Reason carefully for several seconds, then return exactly "
                        "through the say branch with the text cancel probe."
                    ),
                ),
                cancellation,
                timeout_seconds=600.0,
            )
        except TurnNotStarted as error:
            assert error.reason == "cancelled"
        else:
            assert terminal.status == "cancelled"
    finally:
        await provider.shutdown()
        await runtime.close()


async def test_live_structured_nested_optional_output_and_commentary_selection() -> None:
    if _required_environment("LLM_AGENT_KERNEL_LIVE") != "1":
        pytest.fail("LLM_AGENT_KERNEL_LIVE must equal 1", pytrace=False)
    state_root = Path(_required_environment("LLM_AGENT_KERNEL_STATE_ROOT"))
    contract = StructuredOutput("live_structured_result", LiveStructuredResult)
    definition = _definition(
        _required_environment("LLM_AGENT_KERNEL_PROFILE"),
        output_contract=contract,
        session_mode=SessionMode.isolated,
        input_projection_policy=InputProjectionPolicy(
            render_source_timestamps=False,
            batch_as_of=BatchAsOfMode.on_request,
        ),
    )
    plan = _empty_plan(definition)
    projection = bootstrap_context(
        definition,
        (
            HostInput(
                InputId("live-projection-input"),
                PromptSections(
                    (
                        PromptSection(
                            PromptSectionKind("human_text"),
                            (),
                            PromptText(
                                "Without invoking tools, first send a brief progress update on "
                                "the commentary channel. Then respond through the finish branch. "
                                "Set answer to pong, count to null, nested.label to qualified, "
                                "nested.note to null, and reason to null."
                            ),
                        ),
                    )
                ),
                datetime(2026, 9, 6, 9, 0, tzinfo=UTC),
            ),
        ),
        datetime(2026, 9, 6, 9, 1, tzinfo=UTC),
        plan,
        PromptSections(()),
        input_projection=InputProjectionRequest(render_batch_as_of=True),
    )
    assert 'input_id="live-projection-input"' in projection.rendered
    assert 'as_of="2026-09-06T09:01:00+00:00"' in projection.rendered
    assert "source_timestamp=" not in projection.rendered
    runtime = _ObservingAgentRuntime(AgentRuntimeConfig(state_root_base=state_root))
    provider = CodexProvider(runtime, cwd_parent=state_root, cache_continuing=False)
    try:
        lease = await provider.open_isolated(definition)
        terminal = await provider.run_observed_turn(
            lease,
            (TextContent(projection.rendered),),
            CancellationToken(),
            timeout_seconds=600.0,
        )
        assert terminal.status == "succeeded"
        step = validate_provider_step(terminal.structured_output, contract, plan)
        assert isinstance(step, FinishStep)
        assert step.result == {
            "answer": "pong",
            "count": None,
            "nested": {"label": "qualified", "note": None},
        }
        observed_text = "".join(runtime.observed_text)
        assert terminal.final_text in observed_text
        assert observed_text != terminal.final_text, (
            "the dual-phase qualification did not observe commentary before the final answer"
        )
        await provider.close(lease)
    finally:
        await provider.shutdown()
        await runtime.close()


async def test_live_one_shot_uses_initial_read_before_first_provider_turn() -> None:
    if _required_environment("LLM_AGENT_KERNEL_LIVE") != "1":
        pytest.fail("LLM_AGENT_KERNEL_LIVE must equal 1", pytrace=False)
    state_root = Path(_required_environment("LLM_AGENT_KERNEL_STATE_ROOT"))
    definition, plan = _initial_read_definition(_required_environment("LLM_AGENT_KERNEL_PROFILE"))
    known_value = "kernel-initial-read-qualified"
    runtime = _ObservingAgentRuntime(AgentRuntimeConfig(state_root_base=state_root))
    provider = CodexProvider(runtime, cwd_parent=state_root, cache_continuing=False)
    dispatcher = ScriptedToolDispatchPort(
        (DispatchCompleted({"type": "Success", "value": {"echoed": known_value}}),)
    )
    try:
        outcome = await run_one_shot(
            run_id=RunId("live-initial-read"),
            definition=definition,
            inputs=(
                HostInput(
                    InputId("live-initial-read-input"),
                    PromptSections(
                        (
                            PromptSection(
                                PromptSectionKind("human_text"),
                                (),
                                PromptText(
                                    "Use the completed initial Read observation. Respond through "
                                    "finish with answer equal to its echoed value, count null, "
                                    "nested.label qualified, nested.note null, and reason null."
                                ),
                            ),
                        )
                    ),
                    datetime(2026, 9, 6, 10, 0, tzinfo=UTC),
                ),
            ),
            as_of=datetime(2026, 9, 6, 10, 1, tzinfo=UTC),
            plan=plan,
            source_sections=PromptSections(()),
            admission=InMemoryAdmissionPort(),
            provider=provider,
            dispatcher=dispatcher,
            budget_factory=_LiveBudgetFactory(),
            initial_read=InitialReadCall(
                ToolId("live.initial_read"),
                {"text": "qualification lookup"},
            ),
        )
        assert isinstance(outcome, OneShotCompleted)
        assert outcome.result == {
            "answer": known_value,
            "count": None,
            "nested": {"label": "qualified", "note": None},
        }
        assert len(dispatcher.calls) == 1
        assert len(runtime.observed_requests) == 1
        first_input = "\n".join(
            part.text
            for part in runtime.observed_requests[0].input
            if isinstance(part, TextContent)
        )
        assert 'origin="initial_read"' in first_input
        assert known_value in first_input
    finally:
        await provider.shutdown()
        await runtime.close()


async def test_live_json_encoded_tool_arguments() -> None:
    if _required_environment("LLM_AGENT_KERNEL_LIVE") != "1":
        pytest.fail("LLM_AGENT_KERNEL_LIVE must equal 1", pytrace=False)
    state_root = Path(_required_environment("LLM_AGENT_KERNEL_STATE_ROOT"))
    definition = _definition(_required_environment("LLM_AGENT_KERNEL_PROFILE"))
    runtime = AgentRuntime(AgentRuntimeConfig(state_root_base=state_root))
    provider = CodexProvider(runtime, cwd_parent=state_root, cache_continuing=False)
    try:
        lease = await provider.acquire_continuing(definition, None)
        terminal = await provider.run_observed_turn(
            lease,
            (
                TextContent(
                    "Respond through the call_tool branch for live.echo. Encode the strict JSON "
                    "object with text set to pong in the arguments string."
                ),
            ),
            CancellationToken(),
            timeout_seconds=600.0,
        )
        assert terminal.status == "succeeded"
        step = validate_provider_step(
            terminal.structured_output, definition.output_contract, _tool_plan()
        )
        assert isinstance(step, ValidatedToolCall)
        assert step.step.tool_id == ToolId("live.echo")
        assert step.arguments == LiveToolInput(text="pong")
        await provider.release(lease)
    finally:
        await provider.shutdown()
        await runtime.close()


async def test_live_quota_exhaustion() -> None:
    if os.environ.get("LLM_AGENT_KERNEL_EXPECT_QUOTA") != "1":
        pytest.skip("set LLM_AGENT_KERNEL_EXPECT_QUOTA=1 with an exhausted qualification account")
    state_root = Path(_required_environment("LLM_AGENT_KERNEL_STATE_ROOT"))
    definition = _definition(_required_environment("LLM_AGENT_KERNEL_PROFILE"))
    runtime = AgentRuntime(AgentRuntimeConfig(state_root_base=state_root))
    provider = CodexProvider(runtime, cwd_parent=state_root, cache_continuing=False)
    try:
        lease = await provider.acquire_continuing(definition, None)
        terminal = await provider.run_observed_turn(
            lease,
            (TextContent("Respond through the finish branch with no internal reason."),),
            CancellationToken(),
            timeout_seconds=600.0,
        )
        assert terminal.status == "failed"
        assert isinstance(terminal.failure, AgentQuotaExhausted)
    finally:
        await provider.shutdown()
        await runtime.close()


def _empty_plan(definition: AgentDefinition | None = None) -> FrozenToolPlan:
    definition = definition or _definition(_required_environment("LLM_AGENT_KERNEL_PROFILE"))
    return ToolPlan(definition.maximum_profile.id, HostTable()).freeze(
        ToolCatalog.compose(()),
        definition.maximum_profile,
    )


def _tool_plan() -> FrozenToolPlan:
    spec = ToolSpec(
        id=ToolId("live.echo"),
        summary="Validate one live argument envelope",
        documentation=PromptDocument("Echo one text value."),
        input_type=LiveToolInput,
        success_type=LiveToolSuccess,
        error_type=NoDeclaredError,
        effect=ToolEffect.Pure,
        limits=ToolLimits(4_096, 4_096, 1, 30.0),
    )
    binding = ToolBinding(
        spec=spec,
        execute=Available(_must_not_execute),
        replay_policy=ReplayPolicy.ReDispatchable,
        implementation_revision="live-echo-v1",
        policy_epoch=PolicyEpoch("v1"),
        policy_inputs={},
    )
    catalog = ToolCatalog.compose((ToolFamily("live", (spec,), (binding,)),))
    profile = CapabilityProfile(
        ProfileId("live-tool"),
        (ToolGrant(spec.id, None),),
        RunLimits(1, 1, 4_096, 4_096, 1, 600.0),
    ).freeze(catalog)
    return cast(
        FrozenToolPlan,
        ToolPlan(profile.id, HostTable()).freeze(catalog, profile),
    )
