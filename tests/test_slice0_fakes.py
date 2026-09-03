from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from provider_runtime.agent_runtime import AgentSessionRef

from llm_agent_kernel.cancellation import CancellationToken
from llm_agent_kernel.coordination import (
    AdmissionGranted,
    AdmissionRejected,
    AdmissionRequest,
    AdmissionUsage,
    ClaimNoWork,
    DiscardedSessionRef,
    StaleSessionRef,
    StoredSessionRef,
)
from llm_agent_kernel.definitions import (
    OwnerToken,
    ProviderUsage,
    RunId,
    ThreadId,
)
from llm_agent_kernel.events import (
    EventAttribute,
    EventKind,
    KernelEvent,
    emit_event,
)
from llm_agent_kernel.fakes import (
    InMemoryAdmissionPort,
    InMemoryInputCheckpointPort,
    InMemorySessionRefPort,
    RecordingEventSink,
)


def _ref(native_id: str) -> AgentSessionRef:
    return AgentSessionRef(
        schema_version="agent-session-ref.v1",
        backend="codex",
        transport="sdk",
        native_session_id=native_id,
        profile_key="personal",
        state_root_fingerprint="a" * 64,
        cwd_fingerprint="b" * 64,
    )


async def test_cancellation_token_matches_provider_and_tool_shapes() -> None:
    token = CancellationToken()
    waiter = asyncio.create_task(token.wait())

    assert not token.cancelled
    assert not token.is_set()
    token.cancel()
    await waiter
    assert token.cancelled
    assert token.is_set()


async def test_session_ref_fake_enforces_generation_cas() -> None:
    port = InMemorySessionRefPort()
    thread_id = ThreadId("thread-1")
    first = await port.compare_and_set(thread_id, "fingerprint", None, _ref("session-1"))
    assert isinstance(first, StoredSessionRef)
    assert first.generation == 1

    assert isinstance(
        await port.discard(thread_id, "fingerprint", None),
        StaleSessionRef,
    )
    stale = await port.compare_and_set(thread_id, "fingerprint", None, _ref("session-2"))
    assert isinstance(stale, StaleSessionRef)
    second = await port.compare_and_set(
        thread_id, "fingerprint", first.generation, _ref("session-2")
    )
    assert isinstance(second, StoredSessionRef)
    assert second.generation == 2
    discarded = await port.discard(thread_id, "fingerprint", second.generation)
    assert isinstance(discarded, DiscardedSessionRef)
    assert await port.load(thread_id, "fingerprint") is None


async def test_admission_clean_exit_refunds_unused_capacity() -> None:
    port = InMemoryAdmissionPort(max_turns=10, max_input_tokens=100, max_output_tokens=100)
    decision = await port.reserve(
        AdmissionRequest(RunId("run-1"), ThreadId("thread-1"), 1, 8, 80, 80)
    )
    assert isinstance(decision, AdmissionGranted)
    assert port.live_slots == 1

    await port.settle(decision.token, AdmissionUsage(2, ProviderUsage(10, 5), 1.0))

    assert port.live_slots == 0
    assert port.charged_turns == 2
    assert port.charged_input_tokens == 10
    assert port.charged_output_tokens == 5


async def test_admission_orphan_recovery_retains_capacity_charge() -> None:
    port = InMemoryAdmissionPort(max_turns=10, max_input_tokens=100, max_output_tokens=100)
    decision = await port.reserve(
        AdmissionRequest(RunId("run-1"), ThreadId("thread-1"), 1, 8, 80, 80)
    )
    assert isinstance(decision, AdmissionGranted)

    assert await port.recover_orphans() == (RunId("run-1"),)
    assert port.live_slots == 0
    assert port.charged_turns == 8
    assert port.charged_input_tokens == 80
    assert port.charged_output_tokens == 80


async def test_serial_child_shares_root_slot_and_charges_parent_reservation() -> None:
    port = InMemoryAdmissionPort(
        max_turns=10,
        max_input_tokens=100,
        max_output_tokens=100,
        child_turn_allowance=2,
        child_input_token_allowance=20,
        child_output_token_allowance=20,
    )
    root = await port.reserve(AdmissionRequest(RunId("root"), ThreadId("thread-1"), 1, 8, 80, 80))
    assert isinstance(root, AdmissionGranted)
    child = await port.reserve(
        AdmissionRequest(RunId("child"), None, None, 2, 20, 20, parent=root.token)
    )
    assert isinstance(child, AdmissionGranted)
    assert child.token.owns_live_slot is False
    assert port.live_slots == 1

    await port.settle(child.token, AdmissionUsage(1, ProviderUsage(8, 4), 1.0))
    await port.settle(root.token, AdmissionUsage(2, ProviderUsage(10, 5), 2.0))

    assert port.live_slots == 0
    assert port.charged_turns == 3
    assert port.charged_input_tokens == 18
    assert port.charged_output_tokens == 9


async def test_admission_rejects_attempt_beyond_durable_ceiling_without_reservation() -> None:
    port = InMemoryAdmissionPort(max_no_progress_attempts=3)

    decision = await port.reserve(
        AdmissionRequest(RunId("run-4"), ThreadId("thread-1"), 4, 8, 100, 100)
    )

    assert isinstance(decision, AdmissionRejected)
    assert port.live_slots == 0
    assert port.charged_turns == 0


async def test_empty_checkpoint_fake_does_not_invent_work() -> None:
    port = InMemoryInputCheckpointPort()
    assert isinstance(
        await port.claim(ThreadId("thread-1"), OwnerToken("owner")),
        ClaimNoWork,
    )
    assert len(port.claims) == 0


def test_default_events_reject_private_fields_and_sink_failure_is_nonfatal() -> None:
    with pytest.raises(ValueError, match="private payload"):
        EventAttribute("prompt", "private")
    with pytest.raises(ValueError, match="byte limit"):
        EventAttribute("status", "x" * 1_025)
    with pytest.raises(ValueError, match="range"):
        EventAttribute("count", 2**63)
    event = KernelEvent(
        RunId("run-1"),
        EventKind.outcome,
        datetime.now(UTC),
        (EventAttribute("outcome", "completed"),),
    )
    sink = RecordingEventSink(fail=True)

    emit_event(sink, event)

    assert sink.events == []
