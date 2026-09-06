"""Host-owned coordination values and asynchronous ports."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol

from llm_tools import BudgetState, FrozenToolPlan, PromptSections, ToolBinding
from provider_runtime.agent_runtime import AgentSessionRef

from .cancellation import CancellationToken
from .definitions import (
    AgentDefinition,
    Checkpoint,
    DispatchResult,
    HostConclusion,
    HostInput,
    InputClaim,
    OwnerToken,
    ProviderUsage,
    RunId,
    ThreadId,
    ToolDispatchLineage,
)


@dataclass(frozen=True, slots=True)
class ClaimNoWork:
    type: Literal["no_work"] = field(default="no_work", init=False)


@dataclass(frozen=True, slots=True)
class ClaimBusy:
    type: Literal["busy"] = field(default="busy", init=False)


@dataclass(frozen=True, slots=True)
class ClaimDeferred:
    until: datetime
    type: Literal["deferred"] = field(default="deferred", init=False)

    def __post_init__(self) -> None:
        _require_aware(self.until, "claim deferral")


@dataclass(frozen=True, slots=True)
class ClaimAcquired:
    claim: InputClaim
    type: Literal["claim"] = field(default="claim", init=False)


type ClaimResult = ClaimNoWork | ClaimBusy | ClaimDeferred | ClaimAcquired


class CheckpointStateDefect(RuntimeError):
    """The host checkpoint state is corrupt or conflicts with canonical work."""


@dataclass(frozen=True, slots=True)
class NoNewInput:
    type: Literal["none"] = field(default="none", init=False)


@dataclass(frozen=True, slots=True)
class AppendInputs:
    inputs: tuple[HostInput, ...]
    new_checkpoint: Checkpoint
    new_as_of: datetime
    type: Literal["append"] = field(default="append", init=False)

    def __post_init__(self) -> None:
        if type(self.inputs) is not tuple or not self.inputs:
            raise ValueError("an appended input batch must not be empty")
        if any(not isinstance(item, HostInput) for item in self.inputs):
            raise TypeError("appended inputs must be HostInput values")
        if not isinstance(self.new_checkpoint, Checkpoint):
            raise TypeError("appended input checkpoint must be Checkpoint")
        _require_aware(self.new_as_of, "appended input as_of")


@dataclass(frozen=True, slots=True)
class Preempt:
    reason: str
    type: Literal["preempt"] = field(default="preempt", init=False)

    def __post_init__(self) -> None:
        if type(self.reason) is not str or not self.reason:
            raise ValueError("preemption reason must not be empty")


type PollResult = NoNewInput | AppendInputs | Preempt


@dataclass(frozen=True, slots=True)
class SettleIdle:
    type: Literal["idle"] = field(default="idle", init=False)


@dataclass(frozen=True, slots=True)
class SettleMoreInput:
    type: Literal["more_input"] = field(default="more_input", init=False)


type SettleResult = SettleIdle | SettleMoreInput


@dataclass(frozen=True, slots=True)
class Released:
    type: Literal["released"] = field(default="released", init=False)


@dataclass(frozen=True, slots=True)
class AlreadyReleased:
    type: Literal["already_released"] = field(default="already_released", init=False)


type ReleaseResult = Released | AlreadyReleased


@dataclass(frozen=True, slots=True)
class Parked:
    type: Literal["parked"] = field(default="parked", init=False)


@dataclass(frozen=True, slots=True)
class AlreadyParked:
    type: Literal["already_parked"] = field(default="already_parked", init=False)


type ParkResult = Parked | AlreadyParked


class InputCheckpointPort(Protocol):
    async def claim(self, thread_id: ThreadId, owner_token: OwnerToken) -> ClaimResult: ...

    async def poll(self, claim: InputClaim, through_checkpoint: Checkpoint) -> PollResult: ...

    async def settle(
        self,
        claim: InputClaim,
        through_checkpoint: Checkpoint,
        conclusion: HostConclusion,
    ) -> SettleResult: ...

    async def release(self, claim: InputClaim, reason: str) -> ReleaseResult: ...

    async def park(self, claim: InputClaim, reason: str) -> ParkResult: ...


class AdmissionStateDefect(RuntimeError):
    """The host's admission journal is missing, corrupt, or inconsistent."""


@dataclass(frozen=True, slots=True)
class AdmissionToken:
    run_id: RunId
    window_id: str
    root_epoch_id: str
    reserved_turns: int
    reserved_input_tokens: int
    reserved_output_tokens: int
    owns_live_slot: bool
    state: Literal["reserved"] = field(default="reserved", init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, RunId):
            raise TypeError("admission token run id must be RunId")
        if type(self.window_id) is not str or not self.window_id:
            raise ValueError("admission window id must not be empty")
        if type(self.root_epoch_id) is not str or not self.root_epoch_id:
            raise ValueError("admission root epoch id must not be empty")
        reservations = (
            self.reserved_turns,
            self.reserved_input_tokens,
            self.reserved_output_tokens,
        )
        if any(type(value) is not int or value <= 0 for value in reservations):
            raise ValueError("admission reservations must be positive integers")
        if type(self.owns_live_slot) is not bool:
            raise TypeError("owns_live_slot must be bool")


@dataclass(frozen=True, slots=True)
class AdmissionRequest:
    run_id: RunId
    thread_id: ThreadId | None
    attempt_number: int | None
    maximum_turns: int
    maximum_input_tokens: int
    maximum_output_tokens: int
    parent: AdmissionToken | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, RunId):
            raise TypeError("admission request run id must be RunId")
        if self.thread_id is None:
            if self.attempt_number is not None:
                raise ValueError("an isolated admission has no retry attempt number")
        else:
            if not isinstance(self.thread_id, ThreadId):
                raise TypeError("admission thread id must be ThreadId")
            if type(self.attempt_number) is not int or self.attempt_number <= 0:
                raise ValueError("a thread admission requires a positive attempt number")
            if self.parent is not None:
                raise ValueError("a thread admission cannot share a parent slot")
        reservations = (
            self.maximum_turns,
            self.maximum_input_tokens,
            self.maximum_output_tokens,
        )
        if any(type(value) is not int or value <= 0 for value in reservations):
            raise ValueError("admission maxima must be positive integers")
        if self.parent is not None and not isinstance(self.parent, AdmissionToken):
            raise TypeError("parent admission must be an AdmissionToken")


@dataclass(frozen=True, slots=True)
class AdmissionGranted:
    token: AdmissionToken
    type: Literal["granted"] = field(default="granted", init=False)


@dataclass(frozen=True, slots=True)
class AdmissionDeferred:
    until: datetime
    type: Literal["deferred"] = field(default="deferred", init=False)

    def __post_init__(self) -> None:
        _require_aware(self.until, "admission deferral")


@dataclass(frozen=True, slots=True)
class AdmissionRejected:
    reason: str
    type: Literal["rejected"] = field(default="rejected", init=False)

    def __post_init__(self) -> None:
        if type(self.reason) is not str or not self.reason:
            raise ValueError("admission rejection reason must not be empty")


type AdmissionResult = AdmissionGranted | AdmissionDeferred | AdmissionRejected


@dataclass(frozen=True, slots=True)
class AdmissionUsage:
    provider_turns: int
    usage: ProviderUsage
    duration_seconds: float

    def __post_init__(self) -> None:
        if type(self.provider_turns) is not int or self.provider_turns < 0:
            raise ValueError("provider turns must be a non-negative integer")
        if not isinstance(self.usage, ProviderUsage):
            raise TypeError("admission usage must be ProviderUsage")
        if type(self.duration_seconds) not in (int, float):
            raise TypeError("admission duration must be numeric")
        if not math.isfinite(self.duration_seconds) or self.duration_seconds < 0:
            raise ValueError("admission duration must be finite and non-negative")


class AdmissionPort(Protocol):
    async def reserve(self, request: AdmissionRequest) -> AdmissionResult: ...

    async def settle(self, token: AdmissionToken, usage: AdmissionUsage) -> None: ...

    async def recover_orphans(self) -> tuple[RunId, ...]:
        """Release orphaned live slots while retaining their rolling capacity charge."""
        ...


class SessionRefStateDefect(RuntimeError):
    """The host's generation-CAS state is missing, corrupt, or inconsistent."""


@dataclass(frozen=True, slots=True)
class StoredSessionRef:
    ref: AgentSessionRef
    generation: int

    def __post_init__(self) -> None:
        if not isinstance(self.ref, AgentSessionRef):
            raise TypeError("stored session ref must be AgentSessionRef")
        if type(self.generation) is not int or self.generation <= 0:
            raise ValueError("session ref generation must be a positive integer")


@dataclass(frozen=True, slots=True)
class StaleSessionRef:
    type: Literal["stale"] = field(default="stale", init=False)


@dataclass(frozen=True, slots=True)
class DiscardedSessionRef:
    type: Literal["discarded"] = field(default="discarded", init=False)


type StoreSessionRefResult = StoredSessionRef | StaleSessionRef
type DiscardSessionRefResult = DiscardedSessionRef | StaleSessionRef


class SessionRefPort(Protocol):
    async def load(
        self, thread_id: ThreadId, definition_fingerprint: str
    ) -> StoredSessionRef | None: ...

    async def compare_and_set(
        self,
        thread_id: ThreadId,
        definition_fingerprint: str,
        expected_generation: int | None,
        new_ref: AgentSessionRef,
    ) -> StoreSessionRefResult: ...

    async def discard(
        self,
        thread_id: ThreadId,
        definition_fingerprint: str,
        expected_generation: int | None,
    ) -> DiscardSessionRefResult: ...


class ContextSourcePort(Protocol):
    async def bootstrap(self, definition: AgentDefinition, claim: InputClaim) -> PromptSections: ...

    async def continuation(
        self,
        definition: AgentDefinition,
        claim: InputClaim,
        inputs: tuple[HostInput, ...],
        through_checkpoint: Checkpoint,
    ) -> PromptSections: ...


class ContextSourceDefect(RuntimeError):
    """Canonical host context cannot be projected safely."""


class ToolBudgetFactoryPort(Protocol):
    def create(self, plan: FrozenToolPlan) -> BudgetState:
        """Create one fresh tool budget from the already validated run plan."""
        ...


class ToolDispatchPort(Protocol):
    """Host dispatch; isolated lineages supply the exact llm-tools position."""

    async def dispatch(
        self,
        *,
        binding: ToolBinding[Any, Any, Any],
        validated_input: object,
        plan: FrozenToolPlan,
        budgets: BudgetState,
        cancellation: CancellationToken,
        lineage: ToolDispatchLineage,
    ) -> DispatchResult: ...


class ToolDispatchDefect(RuntimeError):
    """A host dispatch invariant failed outside the model-visible result envelope."""


def _require_aware(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


__all__ = [
    "AdmissionDeferred",
    "AdmissionGranted",
    "AdmissionPort",
    "AdmissionRejected",
    "AdmissionRequest",
    "AdmissionResult",
    "AdmissionStateDefect",
    "AdmissionToken",
    "AdmissionUsage",
    "AlreadyParked",
    "AlreadyReleased",
    "AppendInputs",
    "ClaimAcquired",
    "ClaimBusy",
    "ClaimDeferred",
    "ClaimNoWork",
    "ClaimResult",
    "CheckpointStateDefect",
    "ContextSourceDefect",
    "ContextSourcePort",
    "DiscardSessionRefResult",
    "DiscardedSessionRef",
    "InputCheckpointPort",
    "NoNewInput",
    "ParkResult",
    "Parked",
    "PollResult",
    "Preempt",
    "ReleaseResult",
    "Released",
    "SessionRefPort",
    "SessionRefStateDefect",
    "SettleIdle",
    "SettleMoreInput",
    "SettleResult",
    "StaleSessionRef",
    "StoreSessionRefResult",
    "StoredSessionRef",
    "ToolBudgetFactoryPort",
    "ToolDispatchPort",
    "ToolDispatchDefect",
]
