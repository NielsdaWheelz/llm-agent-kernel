"""Ordered model children over host-owned durable decisions and tool effects.

Payloads retain their native types. This module owns execution order, not provider
lowering, tool execution, domain storage, or the meaning of a native terminal.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol

from provider_runtime.types import CancelSignal


class GenerationDefect(RuntimeError):
    """A driver, durable lifecycle, or tool result violated its closed contract."""


@dataclass(frozen=True, slots=True)
class GenerationTurn[Request]:
    ordinal: int
    request: Request = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.ordinal) is not int or self.ordinal < 1:
            raise ValueError("generation turn ordinal must be positive")


@dataclass(frozen=True, slots=True)
class GenerationToolCall[Call]:
    call_id: str
    payload: Call = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.call_id, str) or not self.call_id.strip():
            raise ValueError("generation tool call id must not be blank")


@dataclass(frozen=True, slots=True)
class GenerationToolResult[Result]:
    call_id: str
    payload: Result = field(repr=False)


@dataclass(frozen=True, slots=True)
class GenerationContinuation[State, Call]:
    """Exact ordered decision; the host owns canonical bytes and durable identity.

    A starting continuation MUST have been reopened and validated by the host.
    Its tools execute through the same host recorder as their original attempt.
    """

    source_ordinal: int
    payload: State = field(repr=False)
    calls: tuple[GenerationToolCall[Call], ...]

    def __post_init__(self) -> None:
        if type(self.source_ordinal) is not int or self.source_ordinal < 1:
            raise ValueError("continuation source ordinal must be positive")
        if not isinstance(self.calls, tuple) or not self.calls:
            raise ValueError("continuation requires a nonempty tuple of tool calls")
        ids = tuple(call.call_id for call in self.calls)
        if len(set(ids)) != len(ids):
            raise ValueError("continuation tool call ids must be unique")


@dataclass(frozen=True, slots=True)
class GenerationObservation[Event]:
    sequence: int
    value: Event = field(repr=False)


@dataclass(frozen=True, slots=True)
class GenerationProposal[Call, Event]:
    sequence: int
    call: GenerationToolCall[Call]
    value: Event = field(repr=False)


@dataclass(frozen=True, slots=True)
class GenerationTerminal[Terminal, State, Call]:
    sequence: int
    value: Terminal = field(repr=False)
    continuation: GenerationContinuation[State, Call] | None = field(default=None, repr=False)


type GenerationFrame[Event, Terminal, State, Call] = (
    GenerationObservation[Event]
    | GenerationProposal[Call, Event]
    | GenerationTerminal[Terminal, State, Call]
)


@dataclass(frozen=True, slots=True)
class GenerationCompleted[Terminal]:
    terminal: Terminal = field(repr=False)
    last_ordinal: int
    cleanup_diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GenerationStopped[Terminal]:
    reason: Literal["cancelled", "turn_limit"]
    last_terminal: Terminal | None = field(repr=False)
    last_ordinal: int
    cleanup_diagnostics: tuple[str, ...] = ()


class GenerationDriver[Request, Event, Terminal, State, Call, Result](Protocol):
    def stream(
        self,
        turn: GenerationTurn[Request],
        *,
        arm: Callable[[], Awaitable[None]],
        cancellation: CancelSignal,
    ) -> AsyncGenerator[GenerationFrame[Event, Terminal, State, Call], None]:
        """Await arm exactly once after admission, before native model dispatch.

        Preserve native cancellation and close owned resources when this stream
        is closed. Validate native child identity before projecting any event.
        """
        ...

    def successor(
        self,
        continuation: GenerationContinuation[State, Call],
        results: tuple[GenerationToolResult[Result], ...],
    ) -> GenerationTurn[Request]:
        """Pure lowering of the exact reopened decision and ordered results."""
        ...


class GenerationLifecycle[Request, Terminal, State, Call](Protocol):
    async def arm(self, turn: GenerationTurn[Request]) -> None:
        """Durably record dispatch uncertainty under the current host claim."""
        ...

    async def record_terminal(
        self,
        turn: GenerationTurn[Request],
        terminal: GenerationTerminal[Terminal, State, Call],
    ) -> None:
        """Commit original sealed native truth before product work or cleanup.

        An identical replay is idempotent; changed evidence is a defect. This
        transaction owns no product decoder and cannot span external I/O.
        """
        ...

    async def resolve_terminal(
        self,
        turn: GenerationTurn[Request],
        terminal: GenerationTerminal[Terminal, State, Call],
    ) -> GenerationTerminal[Terminal, State, Call]:
        """Resolve the already committed terminal through local product work.

        The host may project its terminal and drop continuation, but may not
        substitute continuation or terminal identity. No database transaction
        may remain open across provider or tool I/O.
        """
        ...

    async def open(self, continuation: GenerationContinuation[State, Call]) -> None:
        """Reopen and verify the committed canonical decision before next lowering.

        Any canonical-byte or claim mismatch raises; the original payload is
        used only after the host verifies equality against its durable store.
        """
        ...


class GenerationTools[Call, Result](Protocol):
    async def execute(
        self,
        source_ordinal: int,
        call: GenerationToolCall[Call],
    ) -> GenerationToolResult[Result]:
        """Use existing authority, stable effect identity, and recorder semantics."""
        ...


class GenerationObserver[Event, Terminal](Protocol):
    async def observe(self, event: Event | Terminal) -> None:
        """Acknowledge the event before any dependent work may proceed."""
        ...


async def run_generation[Request, Event, Terminal, State, Call, Result](
    *,
    start: GenerationTurn[Request] | GenerationContinuation[State, Call],
    driver: GenerationDriver[Request, Event, Terminal, State, Call, Result],
    lifecycle: GenerationLifecycle[Request, Terminal, State, Call],
    tools: GenerationTools[Call, Result],
    observer: GenerationObserver[Event, Terminal],
    cancellation: CancelSignal,
    max_turns: int | None,
) -> GenerationCompleted[Terminal] | GenerationStopped[Terminal]:
    """Execute bounded native children without taking over their native protocol.

    A Completed value means the host accepted a final child, not that the native
    model succeeded. A Stopped value is never a synthetic provider terminal;
    the application must persist and publish that separate orchestration outcome.
    Task cancellation and boundary failures propagate without automatic retries.
    """
    if max_turns is not None and (type(max_turns) is not int or max_turns < 1):
        raise ValueError("generation maximum turns must be positive")
    if not isinstance(start, GenerationTurn | GenerationContinuation):
        raise GenerationDefect("generation start has an unknown closed type")
    if isinstance(start, GenerationTurn) and start.ordinal != 1:
        raise GenerationDefect("a later generation turn must start from its committed continuation")

    last_terminal: Terminal | None = None
    cleanup_diagnostics: tuple[str, ...] = ()
    last_ordinal = start.source_ordinal if isinstance(start, GenerationContinuation) else 0
    current = start
    while True:
        if cancellation.is_set():
            return GenerationStopped("cancelled", last_terminal, last_ordinal, cleanup_diagnostics)
        if isinstance(current, GenerationContinuation):
            if max_turns is not None and current.source_ordinal >= max_turns:
                return GenerationStopped(
                    "turn_limit", last_terminal, last_ordinal, cleanup_diagnostics
                )
            results: list[GenerationToolResult[Result]] = []
            for call in current.calls:
                if cancellation.is_set():
                    return GenerationStopped(
                        "cancelled", last_terminal, last_ordinal, cleanup_diagnostics
                    )
                result = await tools.execute(current.source_ordinal, call)
                if not isinstance(result, GenerationToolResult) or result.call_id != call.call_id:
                    raise GenerationDefect("generation tool result differs from its call identity")
                results.append(result)
            if cancellation.is_set():
                return GenerationStopped(
                    "cancelled", last_terminal, last_ordinal, cleanup_diagnostics
                )
            await lifecycle.open(current)
            if cancellation.is_set():
                return GenerationStopped(
                    "cancelled", last_terminal, last_ordinal, cleanup_diagnostics
                )
            turn = driver.successor(current, tuple(results))
            if not isinstance(turn, GenerationTurn) or turn.ordinal != current.source_ordinal + 1:
                raise GenerationDefect("generation successor is not the next ordered turn")
        else:
            turn = current
        if cancellation.is_set():
            return GenerationStopped("cancelled", last_terminal, last_ordinal, cleanup_diagnostics)
        try:
            terminal, proposals, diagnostics = await _consume_turn(
                turn=turn,
                driver=driver,
                lifecycle=lifecycle,
                observer=observer,
                cancellation=cancellation,
            )
        except _CancelledBeforeDispatch:
            return GenerationStopped("cancelled", last_terminal, last_ordinal, cleanup_diagnostics)
        cleanup_diagnostics += diagnostics
        completed = await lifecycle.resolve_terminal(turn, terminal)
        if not isinstance(completed, GenerationTerminal) or completed.sequence != terminal.sequence:
            raise GenerationDefect("generation lifecycle changed terminal identity")
        if completed.continuation is not None and completed.continuation != terminal.continuation:
            raise GenerationDefect("generation lifecycle substituted the committed continuation")
        last_terminal = completed.value
        last_ordinal = turn.ordinal
        for proposal in proposals:
            await observer.observe(proposal.value)
        await observer.observe(completed.value)
        if completed.continuation is None:
            return GenerationCompleted(completed.value, last_ordinal, cleanup_diagnostics)
        current = completed.continuation


class _CancelledBeforeDispatch(Exception):
    """Cancellation observed before durable model dispatch was armed."""


async def _consume_turn[Request, Event, Terminal, State, Call, Result](
    *,
    turn: GenerationTurn[Request],
    driver: GenerationDriver[Request, Event, Terminal, State, Call, Result],
    lifecycle: GenerationLifecycle[Request, Terminal, State, Call],
    observer: GenerationObserver[Event, Terminal],
    cancellation: CancelSignal,
) -> tuple[
    GenerationTerminal[Terminal, State, Call],
    tuple[GenerationProposal[Call, Event], ...],
    tuple[str, ...],
]:
    armed = False
    arm_started = False

    async def arm() -> None:
        nonlocal armed, arm_started
        if arm_started:
            raise GenerationDefect("generation driver invoked dispatch arming twice")
        arm_started = True
        if cancellation.is_set():
            raise _CancelledBeforeDispatch
        await lifecycle.arm(turn)
        armed = True

    terminal: GenerationTerminal[Terminal, State, Call] | None = None
    recorded = False
    diagnostics: tuple[str, ...] = ()
    proposals: list[GenerationProposal[Call, Event]] = []
    sequence = -1
    stream = driver.stream(turn, arm=arm, cancellation=cancellation)
    primary_error: BaseException | None = None
    try:
        async for frame in stream:
            if not armed:
                raise GenerationDefect("generation evidence arrived before durable dispatch arming")
            if not isinstance(
                frame, GenerationObservation | GenerationProposal | GenerationTerminal
            ):
                raise GenerationDefect("generation stream emitted an unknown event type")
            if type(frame.sequence) is not int or frame.sequence <= sequence:
                raise GenerationDefect("generation event sequence is not strictly increasing")
            sequence = frame.sequence
            if isinstance(frame, GenerationObservation):
                await observer.observe(frame.value)
            elif isinstance(frame, GenerationProposal):
                proposals.append(frame)
            else:
                terminal = frame
                await lifecycle.record_terminal(turn, terminal)
                recorded = True
                break
    except BaseException as error:
        primary_error = error
        raise
    finally:
        try:
            await stream.aclose()
        except Exception as error:
            if primary_error is not None:
                primary_error.add_note(
                    f"{type(error).__name__}: generation stream cleanup also failed"
                )
            elif not recorded:
                raise
            else:
                diagnostics = (
                    f"{type(error).__name__}: stream cleanup failed after native terminal",
                )
    if terminal is None:
        raise GenerationDefect("generation stream ended without terminal truth")
    continuation = terminal.continuation
    if continuation is None:
        if proposals:
            raise GenerationDefect("generation terminal omitted its proposed tool continuation")
    elif continuation.source_ordinal != turn.ordinal or continuation.calls != tuple(
        proposal.call for proposal in proposals
    ):
        raise GenerationDefect("generation continuation differs from its ordered tool proposals")
    return terminal, tuple(proposals), diagnostics


__all__ = [
    "GenerationCompleted",
    "GenerationContinuation",
    "GenerationDefect",
    "GenerationDriver",
    "GenerationFrame",
    "GenerationLifecycle",
    "GenerationObservation",
    "GenerationObserver",
    "GenerationProposal",
    "GenerationStopped",
    "GenerationTerminal",
    "GenerationToolCall",
    "GenerationToolResult",
    "GenerationTools",
    "GenerationTurn",
    "run_generation",
]
