"""Host-owned coordination values and asynchronous ports."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol

from llm_tools import BudgetState, FrozenToolPlan, ToolBinding

from .cancellation import CancellationToken
from .definitions import (
    Checkpoint,
    DispatchResult,
    HostInput,
    OwnerPermit,
    ToolDispatchLineage,
)


class OwnerPort(Protocol):
    async def require_current(self, permit: OwnerPermit) -> None:
        """Prove live host authority; stale ownership raises before dependent I/O."""
        ...


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


class ContextSourceDefect(RuntimeError):
    """Canonical host context cannot be projected safely."""


class ToolBudgetFactoryPort(Protocol):
    def create(self, plan: FrozenToolPlan) -> BudgetState:
        """Create one fresh tool budget from the already validated run plan."""
        ...


class ToolDispatchPort(Protocol):
    """Host dispatch; isolated lineages supply the exact llm-tools position.

    Before a recoverable Write, the host MUST durably accept the exact original
    tool decision: lineage (including definition fingerprint), frozen plan and
    binding revisions, validated arguments, and stable action/effect identity.
    Recovery uses that immutable record, never a regenerated model choice.
    Existing host policy/approval gates run before acceptance; this port does
    not authorize a Write merely because the model proposed it. In particular,
    storing a provider session reference is not durable decision acceptance.
    """

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
    "OwnerPort",
    "AppendInputs",
    "ContextSourceDefect",
    "NoNewInput",
    "PollResult",
    "Preempt",
    "ToolBudgetFactoryPort",
    "ToolDispatchPort",
    "ToolDispatchDefect",
]
