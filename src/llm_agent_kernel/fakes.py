"""Deterministic process-local test doubles.

These fakes are not durable and make no crash-recovery claim. Production hosts
persist original provider decisions, canonical input and effect/recorder state.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from llm_tools import BudgetState, FrozenToolPlan, ToolBinding
from provider_runtime.agent_runtime import AgentNotSubmitted, AgentTerminal

from .cancellation import CancellationToken
from .coordination import ToolDispatchPort
from .decisions import (
    DecisionScope,
    ModelDecisionArmed,
    ModelDecisionCompleted,
    ModelDecisionDefect,
    ModelDecisionJournal,
    ModelDecisionRecord,
    ModelDecisionRequest,
)
from .definitions import (
    DispatchResult,
    ToolDispatchLineage,
)
from .events import EventSink, KernelEvent


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


class InMemoryModelDecisionJournal(ModelDecisionJournal):
    """Process-local contract fake; retain the instance to simulate a restart."""

    def __init__(self) -> None:
        self.records: dict[DecisionScope, list[ModelDecisionRecord]] = {}

    async def latest(self, scope: DecisionScope) -> ModelDecisionRecord | None:
        records = self.records.get(scope, [])
        return records[-1] if records else None

    async def arm(self, request: ModelDecisionRequest) -> None:
        records = self.records.setdefault(request.scope, [])
        expected = 1 if not records else records[-1].request.ordinal + 1
        if request.ordinal != expected or (records and isinstance(records[-1], ModelDecisionArmed)):
            raise ModelDecisionDefect("decision is already armed or its ordinal disagrees")
        records.append(ModelDecisionArmed(request))

    async def complete(
        self, request: ModelDecisionRequest, terminal: AgentTerminal
    ) -> ModelDecisionCompleted:
        records = self.records.get(request.scope, [])
        if not records or records[-1] != ModelDecisionArmed(request):
            raise ModelDecisionDefect("completion does not match the armed decision")
        result = ModelDecisionCompleted(request, terminal)
        records[-1] = result
        return result

    async def not_submitted(
        self, request: ModelDecisionRequest, evidence: AgentNotSubmitted
    ) -> None:
        records = self.records.get(request.scope, [])
        if not records or records[-1] != ModelDecisionArmed(request):
            raise ModelDecisionDefect("non-submission does not match the armed decision")
        from .decisions import ModelDecisionNotSubmitted

        records[-1] = ModelDecisionNotSubmitted(request, evidence)


__all__ = [
    "DispatchRecord",
    "InMemoryModelDecisionJournal",
    "RecordingEventSink",
    "ScriptedToolDispatchPort",
]
