"""Paid opt-in qualification of the exact shared Codex stream boundary.

Run only with a private provider-runtime state root, the externally supervised
App Server socket, its host-owned setgid cognition parent, and a local-account
profile:

    LLM_AGENT_KERNEL_LIVE=1 \
    LLM_AGENT_KERNEL_STATE_ROOT=/absolute/private/root \
    LLM_AGENT_KERNEL_CODEX_SOCKET=/absolute/codex.sock \
    LLM_AGENT_KERNEL_COGNITION_CWD_PARENT=/absolute/setgid/parent \
    LLM_AGENT_KERNEL_PROFILE=personal \
    LLM_AGENT_KERNEL_MODEL=gpt-5.6-terra \
    LLM_AGENT_KERNEL_REASONING=low \
    uv run pytest -m live tests/live/test_codex_qualification.py
"""

from __future__ import annotations

import os
import stat
from datetime import UTC, datetime
from pathlib import Path

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
    RunBudgetState,
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
    AgentRuntime,
    AgentRuntimeConfig,
    CredentialRef,
    TextContent,
    TurnRequest,
)
from pydantic import BaseModel, ConfigDict

from llm_agent_kernel.context import bootstrap_context
from llm_agent_kernel.decisions import TransientModelDecisions
from llm_agent_kernel.definitions import (
    AgentDefinition,
    AgentRole,
    BatchAsOfMode,
    DefinitionId,
    DispatchCompleted,
    HostInput,
    InitialReadCall,
    InputId,
    InputProjectionPolicy,
    InputProjectionRequest,
    OneShotCompleted,
    OwnerPermit,
    OwnerToken,
    ProviderConfiguration,
    RunId,
    SessionMode,
    StructuredOutput,
)
from llm_agent_kernel.fakes import ScriptedToolDispatchPort
from llm_agent_kernel.kernel import run_one_shot
from llm_agent_kernel.provider import CodexProvider

pytestmark = pytest.mark.live


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.fail(f"live qualification requires {name}", pytrace=False)
    return value


def _live_runtime_config(profile_key: str) -> tuple[AgentRuntimeConfig, Path]:
    state_root = Path(_required_environment("LLM_AGENT_KERNEL_STATE_ROOT"))
    socket_path = Path(_required_environment("LLM_AGENT_KERNEL_CODEX_SOCKET"))
    cwd_parent = Path(_required_environment("LLM_AGENT_KERNEL_COGNITION_CWD_PARENT"))
    if not state_root.is_absolute() or not state_root.is_dir():
        pytest.fail("LLM_AGENT_KERNEL_STATE_ROOT must be an existing absolute directory")
    if not socket_path.is_absolute() or not socket_path.is_socket():
        pytest.fail("LLM_AGENT_KERNEL_CODEX_SOCKET must be an existing absolute Unix socket")
    if (
        not cwd_parent.is_absolute()
        or not cwd_parent.is_dir()
        or not cwd_parent.stat().st_mode & stat.S_ISGID
    ):
        pytest.fail(
            "LLM_AGENT_KERNEL_COGNITION_CWD_PARENT must be an existing absolute setgid directory"
        )
    return (
        AgentRuntimeConfig(
            state_root_base=state_root,
            codex_endpoints={profile_key: socket_path},
        ),
        cwd_parent,
    )


def _shared_provider(runtime: AgentRuntime, cwd_parent: Path) -> CodexProvider:
    return CodexProvider(
        runtime,
        cwd_parent=cwd_parent,
        share_cwd_with_group=True,
    )


class _ObservingAgentRuntime(AgentRuntime):
    def __init__(self, config: AgentRuntimeConfig) -> None:
        super().__init__(config)
        self.observed_requests: list[TurnRequest] = []

    def prepare_turn(self, session, request, *, attempt_id, input_id, controls):
        self.observed_requests.append(request)
        return super().prepare_turn(
            session,
            request,
            attempt_id=attempt_id,
            input_id=input_id,
            controls=controls,
        )


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


class _LiveBudgetFactory:
    def create(self, plan: FrozenToolPlan) -> BudgetState:
        return RunBudgetState(plan.profile.run_limits)


class _LiveOwner:
    async def require_current(self, permit: OwnerPermit) -> None:
        assert permit.owner_token == OwnerToken("live-probe")


def _permit() -> OwnerPermit:
    return OwnerPermit("live-probe", OwnerToken("live-probe"), "live-inference", None)


async def _must_not_execute(value: object, context: object) -> object:
    raise AssertionError(f"live schema qualification dispatched: {value!r}, {context!r}")


async def _provider_configuration(profile_key: str) -> ProviderConfiguration:
    auth = CredentialRef("local_account", profile_key)
    model_key = _required_environment("LLM_AGENT_KERNEL_MODEL")
    reasoning = _required_environment("LLM_AGENT_KERNEL_REASONING")
    config, _cwd_parent = _live_runtime_config(profile_key)
    async with AgentRuntime(config) as runtime:
        catalog = await runtime.model_catalog("codex", auth)
    rows = [row for row in catalog.models if row.key == model_key]
    if len(rows) != 1 or reasoning not in {item.key for item in rows[0].reasoning}:
        pytest.fail("live model and reasoning must select one exact catalog option", pytrace=False)
    return ProviderConfiguration(
        auth=auth,
        model_key=model_key,
        reasoning=reasoning,
        agent_definition_revision=catalog.definition_revision,
        row_fingerprint=rows[0].row_fingerprint,
    )


async def _definition(
    profile_key: str,
    *,
    output_contract: StructuredOutput | None = None,
    session_mode: SessionMode = SessionMode.isolated,
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
        output_contract or StructuredOutput("live_result", LiveStructuredResult),
        maximum,
        await _provider_configuration(profile_key),
        "live-qualification-v1",
        input_projection_policy=input_projection_policy or InputProjectionPolicy(),
    )


async def _initial_read_definition(profile_key: str) -> tuple[AgentDefinition, FrozenToolPlan]:
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
        await _provider_configuration(profile_key),
        "live-initial-read-v1",
    )
    return definition, plan


def _live_input(input_id: str, text: str, minute: int) -> HostInput:
    return HostInput(
        InputId(input_id),
        PromptSections(
            (
                PromptSection(
                    PromptSectionKind("human_text"),
                    (),
                    PromptText(text),
                ),
            )
        ),
        datetime(2026, 9, 7, 9, minute, tzinfo=UTC),
    )


async def test_live_structured_nested_optional_output() -> None:
    if _required_environment("LLM_AGENT_KERNEL_LIVE") != "1":
        pytest.fail("LLM_AGENT_KERNEL_LIVE must equal 1", pytrace=False)
    profile_key = _required_environment("LLM_AGENT_KERNEL_PROFILE")
    runtime_config, cwd_parent = _live_runtime_config(profile_key)
    contract = StructuredOutput("live_structured_result", LiveStructuredResult)
    definition = await _definition(
        profile_key,
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
    runtime = _ObservingAgentRuntime(runtime_config)
    provider = _shared_provider(runtime, cwd_parent)
    try:
        outcome = await run_one_shot(
            run_id=RunId("live-structured"),
            definition=definition,
            inputs=(
                _live_input(
                    "live-structured",
                    "Without tools, finish with answer pong, count null, nested.label qualified, nested.note null, and reason null.",
                    0,
                ),
            ),
            as_of=datetime(2026, 9, 6, 9, 1, tzinfo=UTC),
            plan=plan,
            source_sections=PromptSections(()),
            owner=_LiveOwner(),
            permit=_permit(),
            decisions=TransientModelDecisions(),
            provider=provider,
            dispatcher=ScriptedToolDispatchPort(()),
            budget_factory=_LiveBudgetFactory(),
            input_projection=InputProjectionRequest(render_batch_as_of=True),
        )
        assert isinstance(outcome, OneShotCompleted)
        assert outcome.result == {
            "answer": "pong",
            "count": None,
            "nested": {"label": "qualified", "note": None},
        }
        assert runtime.observed_requests

    finally:
        await provider.shutdown()
        await runtime.close()


async def test_live_one_shot_uses_initial_read_before_first_provider_turn() -> None:
    if _required_environment("LLM_AGENT_KERNEL_LIVE") != "1":
        pytest.fail("LLM_AGENT_KERNEL_LIVE must equal 1", pytrace=False)
    profile_key = _required_environment("LLM_AGENT_KERNEL_PROFILE")
    runtime_config, cwd_parent = _live_runtime_config(profile_key)
    definition, plan = await _initial_read_definition(profile_key)
    known_value = "kernel-initial-read-qualified"
    runtime = _ObservingAgentRuntime(runtime_config)
    provider = _shared_provider(runtime, cwd_parent)
    dispatcher = ScriptedToolDispatchPort(
        (DispatchCompleted({"type": "Success", "value": {"echoed": known_value}}),)
    )
    try:
        outcome = await run_one_shot(
            decisions=TransientModelDecisions(),
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
            owner=_LiveOwner(),
            permit=_permit(),
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


def _empty_plan(definition: AgentDefinition) -> FrozenToolPlan:
    return ToolPlan(definition.maximum_profile.id, HostTable()).freeze(
        ToolCatalog.compose(()),
        definition.maximum_profile,
    )
