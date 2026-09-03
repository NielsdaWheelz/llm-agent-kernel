from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

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
    AgentSession,
    AgentSessionRef,
    AgentTerminal,
    CredentialRef,
    SessionUnavailable,
    TextContent,
    freeze_json_object,
)
from provider_runtime.types import CancelSignal

from llm_agent_kernel.coordination import (
    DiscardedSessionRef,
    SessionRefPort,
    SessionRefStateDefect,
    StaleSessionRef,
    StoredSessionRef,
)
from llm_agent_kernel.definitions import (
    AgentDefinition,
    AgentRole,
    ConversationalOutput,
    DefinitionId,
    ProviderConfiguration,
    ProviderUsage,
    SessionMode,
    ThreadId,
)
from llm_agent_kernel.provider import CodexProvider, ProviderSessionLease
from llm_agent_kernel.sessions import (
    ColdBootstrapUnavailable,
    SessionCoordinator,
    StaleSessionReference,
)


def _ref(native_session_id: str) -> AgentSessionRef:
    return AgentSessionRef(
        schema_version="agent-session-ref.v1",
        backend="codex",
        transport="sdk",
        native_session_id=native_session_id,
        profile_key="main",
        state_root_fingerprint="1" * 64,
        cwd_fingerprint="2" * 64,
    )


def _definition() -> AgentDefinition:
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
        session_mode=SessionMode.continuing,
        output_contract=ConversationalOutput(),
        maximum_profile=maximum,
        provider=ProviderConfiguration(
            auth=CredentialRef(kind="local_account", profile_key="main"),
            model="gpt-5",
        ),
    )


def _terminal(ref: AgentSessionRef) -> AgentTerminal:
    return AgentTerminal(
        status="succeeded",
        failure=None,
        final_text='{"type":"finish"}',
        session_ref=ref,
        structured_output=freeze_json_object({"type": "finish"}, context="test structured output"),
    )


class _MemoryRefs:
    """Process-local test double; deliberately not a durability implementation."""

    def __init__(self, journal: list[str]) -> None:
        self.journal = journal
        self.value: StoredSessionRef | None = None
        self.stale_compare = False
        self.stale_discard = False

    async def load(
        self,
        thread_id: ThreadId,
        definition_fingerprint: str,
    ) -> StoredSessionRef | None:
        del thread_id, definition_fingerprint
        self.journal.append("ref.load")
        return self.value

    async def compare_and_set(
        self,
        thread_id: ThreadId,
        definition_fingerprint: str,
        expected_generation: int | None,
        new_ref: AgentSessionRef,
    ) -> StoredSessionRef | StaleSessionRef:
        del thread_id, definition_fingerprint
        self.journal.append(f"ref.cas:{expected_generation}")
        if self.stale_compare:
            return StaleSessionRef()
        actual = self.value.generation if self.value is not None else None
        if actual != expected_generation:
            return StaleSessionRef()
        self.value = StoredSessionRef(
            ref=new_ref,
            generation=1 if actual is None else actual + 1,
        )
        return self.value

    async def discard(
        self,
        thread_id: ThreadId,
        definition_fingerprint: str,
        expected_generation: int | None,
    ) -> DiscardedSessionRef | StaleSessionRef:
        del thread_id, definition_fingerprint
        self.journal.append(f"ref.discard:{expected_generation}")
        if self.stale_discard:
            return StaleSessionRef()
        actual = self.value.generation if self.value is not None else None
        if actual != expected_generation:
            return StaleSessionRef()
        self.value = None
        return DiscardedSessionRef()


class _BrokenRefs(_MemoryRefs):
    def __init__(self, journal: list[str], operation: str) -> None:
        super().__init__(journal)
        self.operation = operation

    async def load(self, *args: Any, **kwargs: Any) -> Any:
        if self.operation == "load":
            return object()
        return await super().load(*args, **kwargs)

    async def compare_and_set(self, *args: Any, **kwargs: Any) -> Any:
        if self.operation == "cas":
            return object()
        if self.operation == "generation":
            ref = args[-1]
            return StoredSessionRef(ref, 2)
        return await super().compare_and_set(*args, **kwargs)

    async def discard(self, *args: Any, **kwargs: Any) -> Any:
        if self.operation == "discard":
            return object()
        return await super().discard(*args, **kwargs)


class _Provider:
    def __init__(self, journal: list[str]) -> None:
        self.journal = journal
        self.sequence = 0

    async def acquire_continuing(
        self,
        definition: AgentDefinition,
        saved_ref: AgentSessionRef | None,
    ) -> ProviderSessionLease:
        self.journal.append(
            "provider.acquire:" + (saved_ref.native_session_id if saved_ref is not None else "new")
        )
        self.sequence += 1
        ref = saved_ref if saved_ref is not None else _ref(f"new-{self.sequence}")
        return ProviderSessionLease(
            session=AgentSession(ref),
            cwd=Path("/not-a-real-test-cwd"),
            definition_fingerprint=definition.fingerprint,
            continuing=True,
            cold_bootstrap=saved_ref is None,
            fallback_used=False,
        )

    async def discard_reference(
        self,
        definition_fingerprint: str,
        ref: AgentSessionRef,
    ) -> None:
        del definition_fingerprint
        self.journal.append(f"provider.discard_ref:{ref.native_session_id}")

    async def discard(self, lease: ProviderSessionLease) -> None:
        self.journal.append(f"provider.discard:{lease.session.ref.native_session_id}")

    async def release(self, lease: ProviderSessionLease) -> None:
        self.journal.append(f"provider.release:{lease.session.ref.native_session_id}")

    async def run_observed_turn(
        self,
        lease: ProviderSessionLease,
        content: tuple[TextContent, ...],
        cancellation: CancelSignal,
        *,
        timeout_seconds: float | None = None,
    ) -> AgentTerminal:
        del content, cancellation
        self.journal.append(f"provider.turn:{timeout_seconds}")
        return _terminal(lease.session.ref)

    async def accumulated_usage(self, lease: ProviderSessionLease) -> ProviderUsage:
        del lease
        self.journal.append("provider.usage")
        return ProviderUsage(7, 3)


def _coordinator(
    provider: _Provider,
    refs: _MemoryRefs,
) -> SessionCoordinator:
    return SessionCoordinator(
        cast(CodexProvider, provider),
        cast(SessionRefPort, refs),
    )


async def test_successful_terminals_advance_ref_by_generation_cas() -> None:
    journal: list[str] = []
    refs = _MemoryRefs(journal)
    provider = _Provider(journal)
    coordinator = _coordinator(provider, refs)
    state = await coordinator.acquire_continuing(
        cast(ThreadId, ThreadId("thread")),
        _definition(),
    )

    state = await coordinator.store_terminal_ref(state, _terminal(state.lease.session.ref))
    assert state.expected_generation == 1
    state = await coordinator.store_terminal_ref(state, _terminal(state.lease.session.ref))

    assert state.expected_generation == 2
    assert journal == [
        "ref.load",
        "provider.acquire:new",
        "ref.cas:None",
        "ref.cas:1",
    ]
    assert state.fallback_available is False


async def test_coordinator_exposes_provider_turn_and_usage() -> None:
    journal: list[str] = []
    refs = _MemoryRefs(journal)
    provider = _Provider(journal)
    coordinator = _coordinator(provider, refs)
    state = await coordinator.acquire_continuing(
        cast(ThreadId, ThreadId("thread")),
        _definition(),
    )

    terminal = await coordinator.run_observed_turn(
        state,
        (TextContent("input"),),
        cast(CancelSignal, asyncio.Event()),
        timeout_seconds=4.0,
    )

    assert terminal.status == "succeeded"
    assert await coordinator.accumulated_usage(state) == ProviderUsage(7, 3)
    assert journal[-2:] == ["provider.turn:4.0", "provider.usage"]


async def test_stale_terminal_cas_discards_live_session_and_raises() -> None:
    journal: list[str] = []
    refs = _MemoryRefs(journal)
    provider = _Provider(journal)
    coordinator = _coordinator(provider, refs)
    state = await coordinator.acquire_continuing(
        cast(ThreadId, ThreadId("thread")),
        _definition(),
    )
    refs.stale_compare = True

    with pytest.raises(StaleSessionReference):
        await coordinator.store_terminal_ref(state, _terminal(state.lease.session.ref))

    assert journal[-2:] == ["ref.cas:None", "provider.discard:new-1"]


async def test_recovery_discards_speculative_ref_before_opening_provider() -> None:
    journal: list[str] = []
    refs = _MemoryRefs(journal)
    refs.value = StoredSessionRef(_ref("speculative"), 4)
    provider = _Provider(journal)
    coordinator = _coordinator(provider, refs)

    state = await coordinator.acquire_continuing(
        cast(ThreadId, ThreadId("thread")),
        _definition(),
        recovering=True,
    )

    assert state.cold_bootstrap is True
    assert state.expected_generation is None
    assert journal == [
        "ref.load",
        "ref.discard:4",
        "provider.discard_ref:speculative",
        "provider.acquire:new",
    ]


async def test_stale_recovery_discard_closes_cached_ref_and_performs_no_open() -> None:
    journal: list[str] = []
    refs = _MemoryRefs(journal)
    refs.value = StoredSessionRef(_ref("speculative"), 4)
    refs.stale_discard = True
    provider = _Provider(journal)
    coordinator = _coordinator(provider, refs)

    with pytest.raises(StaleSessionReference):
        await coordinator.acquire_continuing(
            cast(ThreadId, ThreadId("thread")),
            _definition(),
            recovering=True,
        )

    assert journal == [
        "ref.load",
        "ref.discard:4",
        "provider.discard_ref:speculative",
    ]


async def test_resume_failure_allows_one_cold_fallback_only() -> None:
    journal: list[str] = []
    refs = _MemoryRefs(journal)
    refs.value = StoredSessionRef(_ref("saved"), 2)
    provider = _Provider(journal)
    coordinator = _coordinator(provider, refs)
    state = await coordinator.acquire_continuing(
        cast(ThreadId, ThreadId("thread")),
        _definition(),
    )

    state = await coordinator.cold_fallback(
        state,
        SessionUnavailable("resume failed"),
    )

    assert state.cold_bootstrap is True
    assert state.fallback_available is False
    assert state.expected_generation is None
    assert journal[-3:] == [
        "ref.discard:2",
        "provider.discard:saved",
        "provider.acquire:new",
    ]
    with pytest.raises(ColdBootstrapUnavailable):
        await coordinator.cold_fallback(
            state,
            SessionUnavailable("failed again"),
        )


async def test_successful_terminal_disables_cold_fallback_before_step_action() -> None:
    journal: list[str] = []
    refs = _MemoryRefs(journal)
    refs.value = StoredSessionRef(_ref("saved"), 2)
    provider = _Provider(journal)
    coordinator = _coordinator(provider, refs)
    state = await coordinator.acquire_continuing(
        cast(ThreadId, ThreadId("thread")),
        _definition(),
    )
    state = await coordinator.store_terminal_ref(state, _terminal(state.lease.session.ref))

    with pytest.raises(ColdBootstrapUnavailable):
        await coordinator.cold_fallback(
            state,
            SessionUnavailable("failure after a successful terminal"),
        )


async def test_discard_before_replay_removes_advanced_ref_then_live_session() -> None:
    journal: list[str] = []
    refs = _MemoryRefs(journal)
    provider = _Provider(journal)
    coordinator = _coordinator(provider, refs)
    state = await coordinator.acquire_continuing(
        cast(ThreadId, ThreadId("thread")),
        _definition(),
    )
    state = await coordinator.store_terminal_ref(state, _terminal(state.lease.session.ref))

    await coordinator.discard_before_replay(state)

    assert refs.value is None
    assert journal[-2:] == ["ref.discard:1", "provider.discard:new-1"]


async def test_unknown_session_ref_results_fail_closed_before_semantic_action() -> None:
    definition = _definition()

    journal: list[str] = []
    provider = _Provider(journal)
    coordinator = _coordinator(provider, _BrokenRefs(journal, "load"))
    with pytest.raises(SessionRefStateDefect, match="load returned"):
        await coordinator.acquire_continuing(ThreadId("thread"), definition)
    assert not any(item.startswith("provider.acquire") for item in journal)

    for operation, match in (("cas", "CAS returned"), ("generation", "advance")):
        journal = []
        provider = _Provider(journal)
        coordinator = _coordinator(provider, _BrokenRefs(journal, operation))
        state = await coordinator.acquire_continuing(ThreadId("thread"), definition)
        with pytest.raises(SessionRefStateDefect, match=match):
            await coordinator.store_terminal_ref(state, _terminal(state.lease.session.ref))
        assert journal[-1] == "provider.discard:new-1"

    journal = []
    provider = _Provider(journal)
    refs = _BrokenRefs(journal, "discard")
    refs.value = StoredSessionRef(_ref("saved"), 1)
    coordinator = _coordinator(provider, refs)
    state = await coordinator.acquire_continuing(ThreadId("thread"), definition)
    with pytest.raises(SessionRefStateDefect, match="discard returned"):
        await coordinator.discard_before_replay(state)
    assert journal[-1] == "provider.discard:saved"
