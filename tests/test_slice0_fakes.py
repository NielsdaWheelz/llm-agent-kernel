from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from llm_agent_kernel.cancellation import CancellationToken
from llm_agent_kernel.definitions import (
    RunId,
)
from llm_agent_kernel.events import (
    EventAttribute,
    EventKind,
    KernelEvent,
    emit_event,
)
from llm_agent_kernel.fakes import RecordingEventSink


async def test_cancellation_token_matches_provider_and_tool_shapes() -> None:
    token = CancellationToken()
    waiter = asyncio.create_task(token.wait())

    assert not token.cancelled
    assert not token.is_set()
    token.cancel()
    await waiter
    assert token.cancelled
    assert token.is_set()


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
