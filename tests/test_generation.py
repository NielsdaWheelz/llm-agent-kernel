"""Portable child orchestration, with no provider or durable-store impersonation."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass, field, replace

import pytest
from provider_runtime.types import CancelSignal

from llm_agent_kernel import CancellationToken
from llm_agent_kernel.generation import (
    GenerationCompleted,
    GenerationContinuation,
    GenerationDefect,
    GenerationObservation,
    GenerationProposal,
    GenerationStopped,
    GenerationTerminal,
    GenerationToolCall,
    GenerationToolResult,
    GenerationTurn,
    run_generation,
)

type Continuation = GenerationContinuation[str, str]
type Terminal = GenerationTerminal[str, str, str]
type Frame = GenerationObservation[str] | GenerationProposal[str, str] | Terminal


@dataclass
class Fixture:
    frames: dict[int, tuple[Frame, ...]]
    timeline: list[str] = field(default_factory=list)
    cancellation: CancellationToken = field(default_factory=CancellationToken)
    fail_commit: bool = False
    cancel_after_tool: bool = False
    cancel_after_observation: bool = False
    result_mismatch: bool = False
    fail_observation: bool = False
    drop_continuation: bool = False

    async def stream(
        self,
        turn: GenerationTurn[str],
        *,
        arm: Callable[[], Awaitable[None]],
        cancellation: CancelSignal,
    ) -> AsyncGenerator[Frame, None]:
        assert cancellation is self.cancellation
        await arm()
        self.timeline.append(f"provider:{turn.ordinal}")
        for frame in self.frames[turn.ordinal]:
            yield frame
        self.timeline.append(f"stream_closed:{turn.ordinal}")

    def successor(
        self,
        continuation: Continuation,
        results: tuple[GenerationToolResult[str], ...],
    ) -> GenerationTurn[str]:
        self.timeline.append("successor:" + ",".join(result.call_id for result in results))
        return GenerationTurn(continuation.source_ordinal + 1, "successor request")

    async def arm(self, turn: GenerationTurn[str]) -> None:
        self.timeline.append(f"arm:{turn.ordinal}")

    async def complete(self, turn: GenerationTurn[str], terminal: Terminal) -> Terminal:
        self.timeline.append(f"commit:{turn.ordinal}")
        if self.fail_commit:
            raise RuntimeError("durable commit failed")
        if self.drop_continuation:
            return replace(terminal, value="host stopped", continuation=None)
        return terminal

    async def open(self, continuation: Continuation) -> None:
        self.timeline.append(f"open:{continuation.source_ordinal}")

    async def execute(
        self, source_ordinal: int, call: GenerationToolCall[str]
    ) -> GenerationToolResult[str]:
        self.timeline.append(f"tool:{source_ordinal}:{call.call_id}")
        if self.cancel_after_tool:
            self.cancellation.cancel()
        return GenerationToolResult("wrong" if self.result_mismatch else call.call_id, "result")

    async def observe(self, event: str) -> None:
        self.timeline.append(f"observe:{event}")
        if self.fail_observation:
            raise RuntimeError("observer acknowledgment failed")
        if self.cancel_after_observation:
            self.cancellation.cancel()

    async def run(
        self, *, max_turns: int = 3, start: GenerationTurn[str] | Continuation | None = None
    ):
        return await run_generation(
            start=start or GenerationTurn(1, "initial request"),
            driver=self,
            lifecycle=self,
            tools=self,
            observer=self,
            cancellation=self.cancellation,
            max_turns=max_turns,
        )


def tool_turn(*call_ids: str) -> tuple[Frame, ...]:
    calls = tuple(GenerationToolCall(call_id, f"arguments:{call_id}") for call_id in call_ids)
    proposals = tuple(
        GenerationProposal(index, call, f"proposal:{call.call_id}")
        for index, call in enumerate(calls)
    )
    continuation = GenerationContinuation(1, "durably sealed canonical bytes", calls)
    return (*proposals, GenerationTerminal(len(calls), "needs tools", continuation))


@pytest.mark.asyncio
async def test_terminal_commit_and_acknowledgment_precede_ordered_tools_and_successor() -> None:
    fixture = Fixture({1: tool_turn("a", "b"), 2: (GenerationTerminal(0, "answer"),)})
    result = await fixture.run()
    assert result == GenerationCompleted("answer", 2)
    assert fixture.timeline == [
        "arm:1",
        "provider:1",
        "stream_closed:1",
        "commit:1",
        "observe:proposal:a",
        "observe:proposal:b",
        "observe:needs tools",
        "tool:1:a",
        "tool:1:b",
        "open:1",
        "successor:a,b",
        "arm:2",
        "provider:2",
        "stream_closed:2",
        "commit:2",
        "observe:answer",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "late", [GenerationObservation(2, "late"), GenerationTerminal(2, "second")]
)
async def test_any_event_after_terminal_prevents_commit_acknowledgment_and_tools(
    late: Frame,
) -> None:
    fixture = Fixture({1: (*tool_turn("a"), late)})
    with pytest.raises(GenerationDefect, match="after terminal"):
        await fixture.run()
    assert not any(
        value.startswith(("commit", "observe", "tool", "open")) for value in fixture.timeline
    )


@pytest.mark.asyncio
async def test_commit_failure_prevents_tool_publication_and_dispatch() -> None:
    fixture = Fixture({1: tool_turn("a")}, fail_commit=True)
    with pytest.raises(RuntimeError, match="durable commit"):
        await fixture.run()
    assert fixture.timeline == ["arm:1", "provider:1", "stream_closed:1", "commit:1"]


@pytest.mark.asyncio
async def test_observer_failure_prevents_dependent_tools() -> None:
    fixture = Fixture({1: tool_turn("a")}, fail_observation=True)
    with pytest.raises(RuntimeError, match="acknowledgment"):
        await fixture.run()
    assert not any(value.startswith(("tool", "open", "successor")) for value in fixture.timeline)


@pytest.mark.asyncio
async def test_cancellation_between_serial_tools_never_dispatches_the_next_tool() -> None:
    fixture = Fixture({1: tool_turn("a", "b")}, cancel_after_tool=True)
    result = await fixture.run()
    assert result == GenerationStopped("cancelled", "needs tools", 1)
    assert "tool:1:a" in fixture.timeline
    assert "tool:1:b" not in fixture.timeline
    assert "open:1" not in fixture.timeline


@pytest.mark.asyncio
async def test_cancellation_after_acknowledgment_prevents_all_tools() -> None:
    fixture = Fixture({1: tool_turn("a")}, cancel_after_observation=True)
    result = await fixture.run()
    assert result == GenerationStopped("cancelled", "needs tools", 1)
    assert not any(value.startswith("tool") for value in fixture.timeline)


@pytest.mark.asyncio
async def test_exhaustion_is_stopped_with_last_accepted_terminal_not_success() -> None:
    fixture = Fixture({1: tool_turn("a")})
    result = await fixture.run(max_turns=1)
    assert result == GenerationStopped("turn_limit", "needs tools", 1)
    assert not any(value.startswith(("tool", "open", "successor")) for value in fixture.timeline)


@pytest.mark.asyncio
async def test_pre_cancelled_run_does_no_io_and_has_no_accepted_terminal() -> None:
    fixture = Fixture({})
    fixture.cancellation.cancel()
    assert await fixture.run() == GenerationStopped("cancelled", None, 0)
    assert fixture.timeline == []


@pytest.mark.asyncio
async def test_resume_reexecutes_tools_via_host_recorder_and_never_repeats_source_provider() -> (
    None
):
    fixture = Fixture({2: (GenerationTerminal(0, "answer"),)})
    continuation = GenerationContinuation(
        1, "verified durable decision", (GenerationToolCall("a", "args"),)
    )
    assert await fixture.run(start=continuation) == GenerationCompleted("answer", 2)
    assert fixture.timeline[:4] == ["tool:1:a", "open:1", "successor:a", "arm:2"]
    assert "provider:1" not in fixture.timeline


@pytest.mark.asyncio
async def test_tool_result_call_identity_cannot_be_substituted() -> None:
    fixture = Fixture({1: tool_turn("a")}, result_mismatch=True)
    with pytest.raises(GenerationDefect, match="tool result"):
        await fixture.run()
    assert "open:1" not in fixture.timeline


@pytest.mark.asyncio
async def test_host_may_drop_a_continuation_at_durable_terminal_resolution() -> None:
    fixture = Fixture({1: tool_turn("a")}, drop_continuation=True)
    assert await fixture.run() == GenerationCompleted("host stopped", 1)
    assert not any(value.startswith("tool") for value in fixture.timeline)


@pytest.mark.asyncio
@pytest.mark.parametrize("sequence", [-1, True, 0])
async def test_nonmonotonic_events_never_commit_terminal(sequence: int) -> None:
    fixture = Fixture(
        {1: (GenerationObservation(0, "progress"), GenerationTerminal(sequence, "answer"))}
    )
    with pytest.raises(GenerationDefect, match="sequence"):
        await fixture.run()
    assert "observe:progress" in fixture.timeline
    assert "commit:1" not in fixture.timeline


@pytest.mark.asyncio
async def test_mismatched_continuation_arguments_fail_before_commit_or_dispatch() -> None:
    continuation = GenerationContinuation(1, "state", (GenerationToolCall("a", "substituted"),))
    fixture = Fixture(
        {
            1: (
                GenerationProposal(0, GenerationToolCall("a", "original"), "proposal"),
                GenerationTerminal(1, "needs tools", continuation),
            )
        }
    )
    with pytest.raises(GenerationDefect, match="ordered tool proposals"):
        await fixture.run()
    assert "commit:1" not in fixture.timeline


@pytest.mark.asyncio
async def test_missing_terminal_is_not_ordinary_completion() -> None:
    fixture = Fixture({1: ()})
    with pytest.raises(GenerationDefect, match="without terminal"):
        await fixture.run()
    assert "commit:1" not in fixture.timeline


@pytest.mark.asyncio
async def test_proposals_without_continuation_are_not_dispatched() -> None:
    fixture = Fixture(
        {
            1: (
                GenerationProposal(0, GenerationToolCall("a", "args"), "proposal"),
                GenerationTerminal(1, "answer"),
            )
        }
    )
    with pytest.raises(GenerationDefect, match="omitted"):
        await fixture.run()
    assert not any(value.startswith(("commit", "observe", "tool")) for value in fixture.timeline)


@pytest.mark.asyncio
async def test_late_stream_failure_cannot_publish_or_commit_a_terminal() -> None:
    class LateFailure(Fixture):
        async def stream(self, turn, *, arm, cancellation):
            await arm()
            yield GenerationTerminal(0, "answer")
            raise RuntimeError("late provider protocol defect")

    fixture = LateFailure({})
    with pytest.raises(RuntimeError, match="late provider"):
        await fixture.run()
    assert fixture.timeline == ["arm:1"]


@pytest.mark.asyncio
async def test_evidence_before_dispatch_arming_is_rejected_and_stream_is_closed() -> None:
    class Unarmed(Fixture):
        async def stream(self, turn, *, arm, cancellation):
            try:
                yield GenerationTerminal(0, "answer")
            finally:
                self.timeline.append("closed")

    fixture = Unarmed({})
    with pytest.raises(GenerationDefect, match="before durable"):
        await fixture.run()
    assert fixture.timeline == ["closed"]


@pytest.mark.asyncio
async def test_duplicate_arm_cannot_repeat_durable_admission() -> None:
    class DuplicateArm(Fixture):
        async def stream(self, turn, *, arm, cancellation):
            await arm()
            await arm()
            yield GenerationTerminal(0, "answer")

    fixture = DuplicateArm({})
    with pytest.raises(GenerationDefect, match="arming twice"):
        await fixture.run()
    assert fixture.timeline == ["arm:1"]


@pytest.mark.asyncio
async def test_cancellation_during_admission_prevents_arming_or_dispatch() -> None:
    class CancelDuringAdmission(Fixture):
        async def stream(self, turn, *, arm, cancellation):
            self.cancellation.cancel()
            await arm()
            self.timeline.append("provider dispatched")
            yield GenerationTerminal(0, "answer")

    fixture = CancelDuringAdmission({})
    assert await fixture.run() == GenerationStopped("cancelled", None, 0)
    assert fixture.timeline == []


@pytest.mark.asyncio
async def test_host_continuation_substitution_prevents_observation_and_tools() -> None:
    class Substitution(Fixture):
        async def complete(self, turn, terminal):
            assert terminal.continuation is not None
            return replace(
                terminal, continuation=replace(terminal.continuation, payload="other decision")
            )

    fixture = Substitution({1: tool_turn("a")})
    with pytest.raises(GenerationDefect, match="substituted"):
        await fixture.run()
    assert not any(value.startswith(("observe", "tool")) for value in fixture.timeline)


@pytest.mark.asyncio
async def test_open_failure_preserves_tool_receipts_without_successor_dispatch() -> None:
    class OpenFailure(Fixture):
        async def open(self, continuation):
            raise RuntimeError("durable decision changed")

    fixture = OpenFailure({1: tool_turn("a")})
    with pytest.raises(RuntimeError, match="durable decision changed"):
        await fixture.run()
    assert "tool:1:a" in fixture.timeline
    assert not any(value.startswith("successor") for value in fixture.timeline)


@pytest.mark.asyncio
async def test_cancellation_during_open_prevents_successor_lowering() -> None:
    class CancelOnOpen(Fixture):
        async def open(self, continuation):
            self.cancellation.cancel()

    fixture = CancelOnOpen({1: tool_turn("a")})
    assert await fixture.run() == GenerationStopped("cancelled", "needs tools", 1)
    assert not any(value.startswith("successor") for value in fixture.timeline)


@pytest.mark.asyncio
async def test_resumed_turn_limit_does_not_reset_the_budget_or_repeat_effects() -> None:
    fixture = Fixture({})
    continuation = GenerationContinuation(3, "durable decision", (GenerationToolCall("a", "args"),))
    assert await fixture.run(start=continuation, max_turns=3) == GenerationStopped(
        "turn_limit", None, 3
    )
    assert fixture.timeline == []


@pytest.mark.asyncio
async def test_task_cancellation_closes_stream_and_never_fabricates_terminal_truth() -> None:
    started = asyncio.Event()

    class Waiting(Fixture):
        async def stream(self, turn, *, arm, cancellation):
            await arm()
            try:
                started.set()
                await asyncio.Future()
                yield GenerationTerminal(0, "unreachable")
            finally:
                self.timeline.append("closed")

    fixture = Waiting({})
    task = asyncio.create_task(fixture.run())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert fixture.timeline == ["arm:1", "closed"]


@pytest.mark.asyncio
async def test_tool_failure_never_retries_or_dispatches_later_calls() -> None:
    class ToolFailure(Fixture):
        async def execute(self, source_ordinal, call):
            self.timeline.append(f"attempt:{call.call_id}")
            raise RuntimeError("effect outcome requires host reconciliation")

    fixture = ToolFailure({1: tool_turn("a", "b")})
    with pytest.raises(RuntimeError, match="reconciliation"):
        await fixture.run()
    assert [value for value in fixture.timeline if value.startswith("attempt")] == ["attempt:a"]
    assert not any(value.startswith(("open", "successor")) for value in fixture.timeline)


@pytest.mark.asyncio
async def test_skipped_successor_turn_is_rejected_before_new_dispatch() -> None:
    class SkippedTurn(Fixture):
        def successor(self, continuation, results):
            return GenerationTurn(3, "wrong successor")

    fixture = SkippedTurn({1: tool_turn("a")})
    with pytest.raises(GenerationDefect, match="next ordered turn"):
        await fixture.run()
    assert "arm:3" not in fixture.timeline


@pytest.mark.parametrize("max_turns", [0, -1, True, 1.5])
@pytest.mark.asyncio
async def test_invalid_turn_limit_is_rejected_before_io(max_turns) -> None:
    fixture = Fixture({})
    with pytest.raises(ValueError, match="maximum turns"):
        await fixture.run(max_turns=max_turns)
    assert fixture.timeline == []
