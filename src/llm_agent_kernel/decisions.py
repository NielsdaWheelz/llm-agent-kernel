"""Durable paid-model decisions, separate from host action/effect records."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from llm_tools import canonical_json_bytes
from provider_runtime.agent_runtime import (
    AgentAttempt,
    AgentNotSubmitted,
    AgentTerminal,
    NativeTerminalEvidence,
)

from .definitions import Checkpoint, InputId


class ModelDecisionDefect(RuntimeError):
    """Recorded model authority, request identity, or completion disagrees."""


class ModelDecisionUncertain(ModelDecisionDefect):
    """A paid model dispatch was armed without a durable terminal result."""


@dataclass(frozen=True, slots=True)
class IsolatedDecisionScope:
    """Host-stable operation identity, retained across retry and process restart."""

    operation_id: str

    def __post_init__(self) -> None:
        if type(self.operation_id) is not str or not self.operation_id.strip():
            raise ValueError("isolated decision operation identity is required")


type DecisionScope = IsolatedDecisionScope


@dataclass(frozen=True, slots=True)
class ModelDecisionRequest:
    """Frozen original inputs and both canonical and actually submitted context.

    Canonical content includes bootstrap material and earlier accepted model
    decisions/tool observations, so recovery does not require native history.
    Submitted content records the exact delta passed to the provider. The
    host's operation identity, not a process-local run ID, identifies recovery.
    """

    scope: DecisionScope
    ordinal: int
    definition_fingerprint: str
    plan_revision: str
    input_ids: tuple[InputId, ...]
    through_checkpoint: Checkpoint | None
    as_of: datetime
    model_step_ordinal_before: int
    protocol_repairs: int
    canonical_content: tuple[str, ...] = field(repr=False)
    submitted_content: tuple[str, ...] = field(repr=False)
    provider_attempt: AgentAttempt
    decision_id: str = field(init=False)
    request_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.scope, IsolatedDecisionScope):
            raise ValueError("isolated model decision scope is required")
        if type(self.ordinal) is not int or self.ordinal < 1:
            raise ValueError("model decision ordinal must be positive")
        if (
            not isinstance(self.definition_fingerprint, str)
            or len(self.definition_fingerprint) != 64
            or any(value not in "0123456789abcdef" for value in self.definition_fingerprint)
        ):
            raise ValueError("model decision definition fingerprint must be SHA-256")
        if not isinstance(self.plan_revision, str) or not self.plan_revision:
            raise ValueError("model decision plan revision is required")
        if not isinstance(self.input_ids, tuple) or len(set(self.input_ids)) != len(self.input_ids):
            raise ValueError("model decision requires its original ordered unique input IDs")
        if self.through_checkpoint is not None:
            raise ValueError("isolated decisions have no thread checkpoint")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("model decision as_of must be timezone-aware")
        for value in (self.model_step_ordinal_before, self.protocol_repairs):
            if type(value) is not int or value < 0:
                raise ValueError("model decision counters must be nonnegative")
        if self.model_step_ordinal_before + self.protocol_repairs > self.ordinal - 1:
            raise ValueError("model decision counters exceed preceding decisions")
        for content in (self.canonical_content, self.submitted_content):
            if (
                not isinstance(content, tuple)
                or not content
                or any(type(item) is not str for item in content)
            ):
                raise ValueError("model decision context must be a nonempty text tuple")
        identity = {
            "protocol": "llm-agent-kernel-model-decision-v1",
            "scope": {"operation_id": self.scope.operation_id},
            "ordinal": self.ordinal,
        }
        object.__setattr__(self, "decision_id", _digest(identity))
        if (
            not isinstance(self.provider_attempt, AgentAttempt)
            or self.provider_attempt.attempt_id != self.decision_id
        ):
            raise ValueError("model decision requires its exact prepared provider attempt")
        object.__setattr__(
            self,
            "request_fingerprint",
            _digest(
                {
                    **identity,
                    "definition_fingerprint": self.definition_fingerprint,
                    "plan_revision": self.plan_revision,
                    "input_ids": [str(value) for value in self.input_ids],
                    "through_checkpoint": None
                    if self.through_checkpoint is None
                    else str(self.through_checkpoint),
                    "as_of": self.as_of.isoformat(),
                    "model_step_ordinal_before": self.model_step_ordinal_before,
                    "protocol_repairs": self.protocol_repairs,
                    "canonical_content": list(self.canonical_content),
                    "submitted_content": list(self.submitted_content),
                    "provider_request_digest": self.provider_attempt.request_digest,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class ModelDecisionArmed:
    request: ModelDecisionRequest


@dataclass(frozen=True, slots=True)
class ModelDecisionCompleted:
    request: ModelDecisionRequest
    terminal: AgentTerminal = field(repr=False)

    def __post_init__(self) -> None:
        evidence = self.terminal.evidence
        if (
            not isinstance(evidence, NativeTerminalEvidence)
            or evidence.attempt != self.request.provider_attempt
        ):
            raise ModelDecisionDefect(
                "completed model decision requires original native terminal evidence"
            )


@dataclass(frozen=True, slots=True)
class ModelDecisionNotSubmitted:
    request: ModelDecisionRequest
    evidence: AgentNotSubmitted

    def __post_init__(self) -> None:
        if self.evidence.attempt != self.request.provider_attempt:
            raise ModelDecisionDefect("non-submission proof changed its prepared attempt")


type ModelDecisionRecord = ModelDecisionArmed | ModelDecisionCompleted | ModelDecisionNotSubmitted


class ModelDecisionJournal(Protocol):
    async def latest(self, scope: DecisionScope) -> ModelDecisionRecord | None:
        """Return original durable truth, after host action recovery has priority.

        The host restores the original input IDs and as_of before attempting
        recovery. An armed record without native truth blocks redispatch.
        """
        ...

    async def arm(self, request: ModelDecisionRequest) -> None:
        """Atomically store original request and uncertainty under current owner.

        A duplicate or changed identity is a defect, not permission to redispatch.
        The call returns only after the record is durable.
        """
        ...

    async def complete(
        self, request: ModelDecisionRequest, terminal: AgentTerminal
    ) -> ModelDecisionCompleted:
        """Commit the exact normalized provider terminal before any effect.

        This result is original provider evidence, never reconstructed success.
        A successful completion cannot change either request or terminal.
        """
        ...

    async def not_submitted(
        self, request: ModelDecisionRequest, evidence: AgentNotSubmitted
    ) -> None:
        """Preserve authoritative positive non-submission beside original arm truth."""
        ...


@dataclass(frozen=True, slots=True)
class DurableIsolatedDecisions:
    scope: IsolatedDecisionScope
    journal: ModelDecisionJournal

    def __post_init__(self) -> None:
        if not isinstance(self.scope, IsolatedDecisionScope):
            raise TypeError("durable isolated decisions require a stable isolated scope")


@dataclass(frozen=True, slots=True)
class TransientModelDecisions:
    """Explicitly disposable inference: no recovery or paid-decision replay claim."""


type IsolatedModelDecisions = DurableIsolatedDecisions | TransientModelDecisions


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def model_decision_id(scope: DecisionScope, ordinal: int) -> str:
    """Stable identity used to prepare exact provider bytes before durable arm."""
    return _digest(
        {
            "protocol": "llm-agent-kernel-model-decision-v1",
            "scope": {"operation_id": scope.operation_id},
            "ordinal": ordinal,
        }
    )


__all__ = [
    "DecisionScope",
    "DurableIsolatedDecisions",
    "IsolatedDecisionScope",
    "IsolatedModelDecisions",
    "ModelDecisionArmed",
    "ModelDecisionCompleted",
    "ModelDecisionNotSubmitted",
    "ModelDecisionDefect",
    "ModelDecisionJournal",
    "ModelDecisionRecord",
    "ModelDecisionRequest",
    "ModelDecisionUncertain",
    "TransientModelDecisions",
    "model_decision_id",
]
