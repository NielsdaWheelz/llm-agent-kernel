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
from pathlib import Path
from typing import cast

import pytest
from llm_tools import (
    Available,
    CapabilityProfile,
    FrozenToolPlan,
    HostTable,
    NoDeclaredError,
    PolicyEpoch,
    ProfileId,
    PromptDocument,
    PromptSections,
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
    AgentQuotaExhausted,
    AgentRuntime,
    AgentRuntimeConfig,
    CredentialRef,
    TextContent,
    TurnNotStarted,
)
from pydantic import BaseModel, ConfigDict

from llm_agent_kernel.cancellation import CancellationToken
from llm_agent_kernel.definitions import (
    AgentDefinition,
    AgentRole,
    ConversationalOutput,
    DefinitionId,
    FinishStep,
    OutputContract,
    ProviderConfiguration,
    SessionMode,
    StructuredOutput,
)
from llm_agent_kernel.protocol import validate_provider_step
from llm_agent_kernel.provider import CodexProvider
from llm_agent_kernel.tools import ValidatedToolCall

pytestmark = pytest.mark.live


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.fail(f"live qualification requires {name}", pytrace=False)
    return value


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


async def _must_not_execute(value: object, context: object) -> object:
    raise AssertionError(f"live schema qualification dispatched: {value!r}, {context!r}")


def _definition(
    profile_key: str,
    *,
    output_contract: OutputContract | None = None,
    session_mode: SessionMode = SessionMode.continuing,
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
    )


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
        await provider.release(lease)

        continued = await provider.acquire_continuing(definition, first.session_ref)
        second = await provider.run_observed_turn(
            continued,
            (TextContent("Respond through the finish branch with no internal reason."),),
            CancellationToken(),
            timeout_seconds=600.0,
        )
        assert second.status == "succeeded"
        validate_provider_step(second.structured_output, definition.output_contract, _empty_plan())
        assert second.session_ref.native_session_id == first.session_ref.native_session_id
        await provider.release(continued)

        cancelled = await provider.acquire_continuing(definition, second.session_ref)
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


async def test_live_structured_nested_optional_output() -> None:
    if _required_environment("LLM_AGENT_KERNEL_LIVE") != "1":
        pytest.fail("LLM_AGENT_KERNEL_LIVE must equal 1", pytrace=False)
    state_root = Path(_required_environment("LLM_AGENT_KERNEL_STATE_ROOT"))
    contract = StructuredOutput("live_structured_result", LiveStructuredResult)
    definition = _definition(
        _required_environment("LLM_AGENT_KERNEL_PROFILE"),
        output_contract=contract,
        session_mode=SessionMode.isolated,
    )
    runtime = AgentRuntime(AgentRuntimeConfig(state_root_base=state_root))
    provider = CodexProvider(runtime, cwd_parent=state_root, cache_continuing=False)
    try:
        lease = await provider.open_isolated(definition)
        terminal = await provider.run_observed_turn(
            lease,
            (
                TextContent(
                    "Respond through the finish branch. Set answer to pong, count to null, "
                    "nested.label to qualified, nested.note to null, and reason to null."
                ),
            ),
            CancellationToken(),
            timeout_seconds=600.0,
        )
        assert terminal.status == "succeeded"
        step = validate_provider_step(terminal.structured_output, contract, _empty_plan())
        assert isinstance(step, FinishStep)
        assert step.result == {
            "answer": "pong",
            "count": None,
            "nested": {"label": "qualified", "note": None},
        }
        await provider.close(lease)
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


def _empty_plan() -> FrozenToolPlan:
    definition = _definition(_required_environment("LLM_AGENT_KERNEL_PROFILE"))
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
