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

import pytest
from llm_tools import (
    CapabilityProfile,
    FrozenToolPlan,
    HostTable,
    ProfileId,
    PromptSections,
    RunLimits,
    ToolCatalog,
    ToolPlan,
)
from provider_runtime.agent_runtime import (
    AgentQuotaExhausted,
    AgentRuntime,
    AgentRuntimeConfig,
    CredentialRef,
    TextContent,
    TurnNotStarted,
)

from llm_agent_kernel.cancellation import CancellationToken
from llm_agent_kernel.definitions import (
    AgentDefinition,
    AgentRole,
    ConversationalOutput,
    DefinitionId,
    ProviderConfiguration,
    SessionMode,
)
from llm_agent_kernel.protocol import validate_model_step
from llm_agent_kernel.provider import CodexProvider

pytestmark = pytest.mark.live


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.fail(f"live qualification requires {name}", pytrace=False)
    return value


def _definition(profile_key: str) -> AgentDefinition:
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
        SessionMode.continuing,
        ConversationalOutput(),
        maximum,
        ProviderConfiguration(
            CredentialRef("local_account", profile_key),
            os.environ.get("LLM_AGENT_KERNEL_MODEL", "gpt-5"),
        ),
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
                    "Without invoking native tools or requesting permission, return exactly "
                    '{"type":"say","text":"pong"} under the supplied schema.'
                ),
            ),
            CancellationToken(),
            timeout_seconds=600.0,
        )
        assert first.status == "succeeded"
        validate_model_step(first.structured_output, definition.output_contract, _empty_plan())
        await provider.release(lease)

        continued = await provider.acquire_continuing(definition, first.session_ref)
        second = await provider.run_observed_turn(
            continued,
            (TextContent('Return exactly {"type":"finish"}.'),),
            CancellationToken(),
            timeout_seconds=600.0,
        )
        assert second.status == "succeeded"
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
                        '{"type":"say","text":"cancel probe"}.'
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
            (TextContent('Return exactly {"type":"finish"}.'),),
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
