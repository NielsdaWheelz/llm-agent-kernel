"""Deterministic process-local test doubles.

These fakes are not durable and make no crash-recovery claim. Production hosts
must persist canonical input and settlement, session-reference generations,
write effect/recorder state, and rolling admission state.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from llm_tools import BudgetState, FrozenToolPlan, PromptSections, ToolBinding
from provider_runtime.agent_runtime import AgentSessionRef

from .cancellation import CancellationToken
from .coordination import (
    AdmissionGranted,
    AdmissionPort,
    AdmissionRejected,
    AdmissionRequest,
    AdmissionResult,
    AdmissionStateDefect,
    AdmissionToken,
    AdmissionUsage,
    AlreadyParked,
    AlreadyReleased,
    CheckpointStateDefect,
    ClaimAcquired,
    ClaimBusy,
    ClaimNoWork,
    ClaimResult,
    ContextSourcePort,
    DiscardedSessionRef,
    DiscardSessionRefResult,
    InputCheckpointPort,
    NoNewInput,
    Parked,
    ParkResult,
    PollResult,
    Released,
    ReleaseResult,
    SessionRefPort,
    SettleIdle,
    SettleResult,
    StaleSessionRef,
    StoredSessionRef,
    StoreSessionRefResult,
    ToolDispatchPort,
)
from .definitions import (
    AgentDefinition,
    Checkpoint,
    ClaimId,
    DispatchResult,
    HostConclusion,
    HostInput,
    InputClaim,
    OwnerToken,
    RunId,
    ThreadId,
    ToolDispatchLineage,
)
from .events import EventSink, KernelEvent


@dataclass(frozen=True, slots=True)
class SettlementRecord:
    claim: InputClaim
    through_checkpoint: Checkpoint
    conclusion: HostConclusion


class InMemoryInputCheckpointPort(InputCheckpointPort):
    """Scriptable, non-durable checkpoint fake; restart loses every fact."""

    def __init__(self, claims: Iterable[ClaimResult] = ()) -> None:
        self.claims = deque(claims)
        self.polls: dict[ClaimId, deque[PollResult]] = {}
        self.settle_results: deque[SettleResult] = deque()
        self.settlements: list[SettlementRecord] = []
        self.release_reasons: list[tuple[ClaimId, str]] = []
        self.park_reasons: list[tuple[ClaimId, str]] = []
        self._active: dict[ThreadId, InputClaim] = {}
        self._settled: dict[ClaimId, tuple[Checkpoint, HostConclusion, SettleResult]] = {}
        self._released: set[ClaimId] = set()
        self._parked: set[ClaimId] = set()
        self._lock = asyncio.Lock()

    def queue_poll(self, claim_id: ClaimId, *results: PollResult) -> None:
        self.polls.setdefault(claim_id, deque()).extend(results)

    async def claim(self, thread_id: ThreadId, owner_token: OwnerToken) -> ClaimResult:
        if not isinstance(thread_id, ThreadId) or not isinstance(owner_token, OwnerToken):
            raise TypeError("claim requires ThreadId and OwnerToken")
        async with self._lock:
            if thread_id in self._active:
                return ClaimBusy()
            result = self.claims.popleft() if self.claims else ClaimNoWork()
            if isinstance(result, ClaimAcquired):
                self._active[thread_id] = result.claim
            return result

    async def poll(self, claim: InputClaim, through_checkpoint: Checkpoint) -> PollResult:
        del through_checkpoint
        async with self._lock:
            scripted = self.polls.get(claim.claim_id)
            if scripted:
                return scripted.popleft()
            return NoNewInput()

    async def settle(
        self,
        claim: InputClaim,
        through_checkpoint: Checkpoint,
        conclusion: HostConclusion,
    ) -> SettleResult:
        async with self._lock:
            if claim.claim_id in self._released or claim.claim_id in self._parked:
                raise CheckpointStateDefect("cannot settle a released or parked claim")
            prior = self._settled.get(claim.claim_id)
            if prior is not None:
                if prior[:2] != (through_checkpoint, conclusion):
                    raise CheckpointStateDefect(
                        "settlement conflicts with the prior in-memory value"
                    )
                return prior[2]
            result = self.settle_results.popleft() if self.settle_results else SettleIdle()
            self._settled[claim.claim_id] = (through_checkpoint, conclusion, result)
            self.settlements.append(SettlementRecord(claim, through_checkpoint, conclusion))
            self._drop_active(claim.claim_id)
            return result

    async def release(self, claim: InputClaim, reason: str) -> ReleaseResult:
        async with self._lock:
            if (
                claim.claim_id in self._released
                or claim.claim_id in self._settled
                or claim.claim_id in self._parked
            ):
                return AlreadyReleased()
            self._released.add(claim.claim_id)
            self.release_reasons.append((claim.claim_id, reason))
            self._drop_active(claim.claim_id)
            return Released()

    async def park(self, claim: InputClaim, reason: str) -> ParkResult:
        async with self._lock:
            if claim.claim_id in self._parked:
                return AlreadyParked()
            if claim.claim_id in self._settled or claim.claim_id in self._released:
                raise CheckpointStateDefect("cannot park a settled or released claim")
            self._parked.add(claim.claim_id)
            self.park_reasons.append((claim.claim_id, reason))
            self._drop_active(claim.claim_id)
            return Parked()

    def _drop_active(self, claim_id: ClaimId) -> None:
        for thread_id, claim in tuple(self._active.items()):
            if claim.claim_id == claim_id:
                del self._active[thread_id]


class InMemorySessionRefPort(SessionRefPort):
    """Non-durable generation-CAS fake; process loss discards every reference."""

    def __init__(self) -> None:
        self._values: dict[tuple[ThreadId, str], StoredSessionRef] = {}
        self._lock = asyncio.Lock()

    async def load(
        self, thread_id: ThreadId, definition_fingerprint: str
    ) -> StoredSessionRef | None:
        async with self._lock:
            return self._values.get((thread_id, definition_fingerprint))

    async def compare_and_set(
        self,
        thread_id: ThreadId,
        definition_fingerprint: str,
        expected_generation: int | None,
        new_ref: AgentSessionRef,
    ) -> StoreSessionRefResult:
        key = (thread_id, definition_fingerprint)
        async with self._lock:
            current = self._values.get(key)
            current_generation = current.generation if current is not None else None
            if current_generation != expected_generation:
                return StaleSessionRef()
            stored = StoredSessionRef(
                ref=new_ref,
                generation=1 if current is None else current.generation + 1,
            )
            self._values[key] = stored
            return stored

    async def discard(
        self,
        thread_id: ThreadId,
        definition_fingerprint: str,
        expected_generation: int | None,
    ) -> DiscardSessionRefResult:
        key = (thread_id, definition_fingerprint)
        async with self._lock:
            current = self._values.get(key)
            current_generation = current.generation if current is not None else None
            if current_generation != expected_generation:
                return StaleSessionRef()
            self._values.pop(key, None)
            return DiscardedSessionRef()


@dataclass(slots=True)
class _AdmissionReservation:
    token: AdmissionToken
    parent_run_id: RunId | None
    own_turns: int
    own_input_tokens: int
    own_output_tokens: int
    child_turns: int = 0
    child_input_tokens: int = 0
    child_output_tokens: int = 0
    child_actual_turns: int = 0
    child_actual_input_tokens: int = 0
    child_actual_output_tokens: int = 0


class InMemoryAdmissionPort(AdmissionPort):
    """Non-durable rolling-admission fake with conservative orphan charging."""

    def __init__(
        self,
        *,
        max_turns: int = 1_000,
        max_input_tokens: int = 10_000_000,
        max_output_tokens: int = 10_000_000,
        max_live_slots: int = 1,
        max_no_progress_attempts: int = 3,
        provider_input_token_overshoot: int = 0,
        provider_output_token_overshoot: int = 0,
        child_turn_allowance: int = 0,
        child_input_token_allowance: int = 0,
        child_output_token_allowance: int = 0,
        window_id: str = "test-window",
    ) -> None:
        values = (
            max_turns,
            max_input_tokens,
            max_output_tokens,
            max_live_slots,
            max_no_progress_attempts,
        )
        if any(type(value) is not int or value <= 0 for value in values):
            raise ValueError("in-memory admission ceilings must be positive integers")
        allowances = (
            provider_input_token_overshoot,
            provider_output_token_overshoot,
            child_turn_allowance,
            child_input_token_allowance,
            child_output_token_allowance,
        )
        if any(type(value) is not int or value < 0 for value in allowances):
            raise ValueError("in-memory admission allowances must be non-negative integers")
        if not window_id:
            raise ValueError("in-memory admission window id must not be empty")
        self.max_turns = max_turns
        self.max_input_tokens = max_input_tokens
        self.max_output_tokens = max_output_tokens
        self.max_live_slots = max_live_slots
        self.max_no_progress_attempts = max_no_progress_attempts
        self.provider_input_token_overshoot = provider_input_token_overshoot
        self.provider_output_token_overshoot = provider_output_token_overshoot
        self.child_turn_allowance = child_turn_allowance
        self.child_input_token_allowance = child_input_token_allowance
        self.child_output_token_allowance = child_output_token_allowance
        self.window_id = window_id
        self.charged_turns = 0
        self.charged_input_tokens = 0
        self.charged_output_tokens = 0
        self.live_slots = 0
        self._sequence = 0
        self._active: dict[RunId, _AdmissionReservation] = {}
        self._lock = asyncio.Lock()

    async def reserve(self, request: AdmissionRequest) -> AdmissionResult:
        async with self._lock:
            if request.run_id in self._active:
                raise AdmissionStateDefect("run already has an active admission")
            if (
                request.attempt_number is not None
                and request.attempt_number > self.max_no_progress_attempts
            ):
                return AdmissionRejected("no_progress_attempt_ceiling")
            if request.parent is not None:
                return self._reserve_child(request)
            if self.live_slots >= self.max_live_slots:
                return AdmissionRejected("concurrency_limit")
            if (
                self.charged_turns + request.maximum_turns + self.child_turn_allowance
                > self.max_turns
                or self.charged_input_tokens
                + request.maximum_input_tokens
                + self.provider_input_token_overshoot
                + self.child_input_token_allowance
                > self.max_input_tokens
                or self.charged_output_tokens
                + request.maximum_output_tokens
                + self.provider_output_token_overshoot
                + self.child_output_token_allowance
                > self.max_output_tokens
            ):
                return AdmissionRejected("rolling_capacity")
            self._sequence += 1
            token = AdmissionToken(
                run_id=request.run_id,
                window_id=self.window_id,
                root_epoch_id=f"epoch-{self._sequence}",
                reserved_turns=request.maximum_turns + self.child_turn_allowance,
                reserved_input_tokens=request.maximum_input_tokens
                + self.provider_input_token_overshoot
                + self.child_input_token_allowance,
                reserved_output_tokens=request.maximum_output_tokens
                + self.provider_output_token_overshoot
                + self.child_output_token_allowance,
                owns_live_slot=True,
            )
            self._active[request.run_id] = _AdmissionReservation(
                token,
                None,
                request.maximum_turns,
                request.maximum_input_tokens + self.provider_input_token_overshoot,
                request.maximum_output_tokens + self.provider_output_token_overshoot,
            )
            self.charged_turns += token.reserved_turns
            self.charged_input_tokens += token.reserved_input_tokens
            self.charged_output_tokens += token.reserved_output_tokens
            self.live_slots += 1
            return AdmissionGranted(token)

    def _reserve_child(self, request: AdmissionRequest) -> AdmissionResult:
        assert request.parent is not None
        parent = self._active.get(request.parent.run_id)
        if parent is None or parent.token != request.parent or not parent.token.owns_live_slot:
            raise AdmissionStateDefect("child admission parent is not active")
        if (
            parent.own_turns
            + parent.child_actual_turns
            + parent.child_turns
            + request.maximum_turns
            > parent.token.reserved_turns
            or parent.own_input_tokens
            + parent.child_actual_input_tokens
            + parent.child_input_tokens
            + request.maximum_input_tokens
            + self.provider_input_token_overshoot
            > parent.token.reserved_input_tokens
            or parent.own_output_tokens
            + parent.child_actual_output_tokens
            + parent.child_output_tokens
            + request.maximum_output_tokens
            + self.provider_output_token_overshoot
            > parent.token.reserved_output_tokens
        ):
            return AdmissionRejected("parent_capacity")
        token = AdmissionToken(
            run_id=request.run_id,
            window_id=parent.token.window_id,
            root_epoch_id=parent.token.root_epoch_id,
            reserved_turns=request.maximum_turns,
            reserved_input_tokens=request.maximum_input_tokens
            + self.provider_input_token_overshoot,
            reserved_output_tokens=request.maximum_output_tokens
            + self.provider_output_token_overshoot,
            owns_live_slot=False,
        )
        parent.child_turns += token.reserved_turns
        parent.child_input_tokens += token.reserved_input_tokens
        parent.child_output_tokens += token.reserved_output_tokens
        self._active[request.run_id] = _AdmissionReservation(
            token,
            request.parent.run_id,
            request.maximum_turns,
            request.maximum_input_tokens,
            request.maximum_output_tokens,
        )
        return AdmissionGranted(token)

    async def settle(self, token: AdmissionToken, usage: AdmissionUsage) -> None:
        async with self._lock:
            reservation = self._active.get(token.run_id)
            if reservation is None or reservation.token != token:
                raise AdmissionStateDefect("admission settlement does not match an active token")
            if reservation.parent_run_id is not None:
                parent = self._active.get(reservation.parent_run_id)
                if parent is None:
                    raise AdmissionStateDefect("child admission lost its active parent")
                child_input_tokens = (
                    token.reserved_input_tokens
                    if usage.usage.input_tokens is None
                    else usage.usage.input_tokens
                )
                child_output_tokens = (
                    token.reserved_output_tokens
                    if usage.usage.output_tokens is None
                    else usage.usage.output_tokens
                )
                if (
                    usage.provider_turns > token.reserved_turns
                    or child_input_tokens > token.reserved_input_tokens
                    or child_output_tokens > token.reserved_output_tokens
                ):
                    raise AdmissionStateDefect("child usage exceeds its reservation")
                parent.child_turns -= token.reserved_turns
                parent.child_input_tokens -= token.reserved_input_tokens
                parent.child_output_tokens -= token.reserved_output_tokens
                parent.child_actual_turns += usage.provider_turns
                parent.child_actual_input_tokens += child_input_tokens
                parent.child_actual_output_tokens += child_output_tokens
                del self._active[token.run_id]
                return
            if any(item.parent_run_id == token.run_id for item in self._active.values()):
                raise AdmissionStateDefect("root admission cannot settle while a child is active")
            provider_turns = usage.provider_turns + reservation.child_actual_turns
            input_tokens = token.reserved_input_tokens
            if usage.usage.input_tokens is not None:
                input_tokens = usage.usage.input_tokens + reservation.child_actual_input_tokens
            output_tokens = token.reserved_output_tokens
            if usage.usage.output_tokens is not None:
                output_tokens = usage.usage.output_tokens + reservation.child_actual_output_tokens
            if (
                provider_turns > token.reserved_turns
                or input_tokens > token.reserved_input_tokens
                or output_tokens > token.reserved_output_tokens
            ):
                raise AdmissionStateDefect("actual usage exceeds its reservation")
            self.charged_turns -= token.reserved_turns - provider_turns
            self.charged_input_tokens -= token.reserved_input_tokens - input_tokens
            self.charged_output_tokens -= token.reserved_output_tokens - output_tokens
            self.live_slots -= 1
            del self._active[token.run_id]

    async def recover_orphans(self) -> tuple[RunId, ...]:
        async with self._lock:
            roots = tuple(
                run_id
                for run_id, reservation in self._active.items()
                if reservation.parent_run_id is None
            )
            self._active.clear()
            self.live_slots = 0
            return roots


class StaticContextSource(ContextSourcePort):
    """Non-durable context fake returning caller-owned typed sections."""

    def __init__(
        self,
        bootstrap_sections: PromptSections,
        continuation_sections: PromptSections | None = None,
    ) -> None:
        self.bootstrap_sections = bootstrap_sections
        self.continuation_sections = continuation_sections or PromptSections(())
        self.bootstrap_calls: list[tuple[AgentDefinition, InputClaim]] = []
        self.continuation_calls: list[
            tuple[AgentDefinition, InputClaim, tuple[HostInput, ...], Checkpoint]
        ] = []

    async def bootstrap(self, definition: AgentDefinition, claim: InputClaim) -> PromptSections:
        self.bootstrap_calls.append((definition, claim))
        return self.bootstrap_sections

    async def continuation(
        self,
        definition: AgentDefinition,
        claim: InputClaim,
        inputs: tuple[HostInput, ...],
        through_checkpoint: Checkpoint,
    ) -> PromptSections:
        self.continuation_calls.append((definition, claim, inputs, through_checkpoint))
        return self.continuation_sections


@dataclass(frozen=True, slots=True)
class DispatchRecord:
    binding: ToolBinding[Any, Any, Any]
    validated_input: object
    plan: FrozenToolPlan
    budgets: BudgetState
    cancellation: CancellationToken
    lineage: ToolDispatchLineage


class ScriptedToolDispatchPort(ToolDispatchPort):
    """Non-durable dispatcher fake that executes no application tool."""

    def __init__(self, results: Iterable[DispatchResult]) -> None:
        self.results = deque(results)
        self.calls: list[DispatchRecord] = []

    async def dispatch(
        self,
        *,
        binding: ToolBinding[Any, Any, Any],
        validated_input: object,
        plan: FrozenToolPlan,
        budgets: BudgetState,
        cancellation: CancellationToken,
        lineage: ToolDispatchLineage,
    ) -> DispatchResult:
        self.calls.append(
            DispatchRecord(binding, validated_input, plan, budgets, cancellation, lineage)
        )
        if not self.results:
            raise AssertionError("scripted dispatcher has no remaining result")
        return self.results.popleft()


class RecordingEventSink(EventSink):
    """Process-local metadata recorder for tests."""

    def __init__(self, *, fail: bool = False) -> None:
        self.events: list[KernelEvent] = []
        self.fail = fail

    def emit(self, event: KernelEvent) -> None:
        if self.fail:
            raise RuntimeError("scripted event-sink failure")
        self.events.append(event)


__all__ = [
    "DispatchRecord",
    "InMemoryAdmissionPort",
    "InMemoryInputCheckpointPort",
    "InMemorySessionRefPort",
    "RecordingEventSink",
    "ScriptedToolDispatchPort",
    "SettlementRecord",
    "StaticContextSource",
]
