"""Durable paid-model decisions, separate from host action/effect records."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from llm_tools import canonical_json_bytes
from provider_runtime.agent_runtime import AgentTerminal

from .definitions import Checkpoint, InputId, ThreadId


class ModelDecisionDefect(RuntimeError):
    """Recorded model authority, request identity, or completion disagrees."""


class ModelDecisionUncertain(ModelDecisionDefect):
    """A paid model dispatch was armed without a durable terminal result."""


@dataclass(frozen=True, slots=True)
class ModelDecisionScope:
    thread_id: ThreadId
    first_input_id: InputId

    def __post_init__(self) -> None:
        if not isinstance(self.thread_id, ThreadId) or not isinstance(self.first_input_id, InputId):
            raise ValueError("thread decision scope requires typed original identities")


@dataclass(frozen=True, slots=True)
class IsolatedDecisionScope:
    """Host-stable operation identity, retained across retry and process restart."""

    operation_id: str

    def __post_init__(self) -> None:
        if type(self.operation_id) is not str or not self.operation_id.strip():
            raise ValueError("isolated decision operation identity is required")


type DecisionScope = ModelDecisionScope | IsolatedDecisionScope


@dataclass(frozen=True, slots=True)
class ModelDecisionRequest:
    """Frozen original inputs and both canonical and actually submitted context.

    Canonical content includes bootstrap material and earlier accepted model
    decisions/tool observations, so recovery does not require native history.
    Submitted content records the exact delta passed to the provider. Neither
    claim_id nor the attempt's run_id is a stable decision identity.
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
    decision_id: str = field(init=False)
    request_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.scope, ModelDecisionScope | IsolatedDecisionScope):
            raise ValueError("model decision scope is required")
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
        if isinstance(self.scope, ModelDecisionScope):
            if (
                not self.input_ids
                or self.input_ids[0] != self.scope.first_input_id
                or not isinstance(self.through_checkpoint, Checkpoint)
            ):
                raise ValueError("thread decision requires original input and checkpoint")
        elif self.through_checkpoint is not None:
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
            "scope": (
                {
                    "thread_id": str(self.scope.thread_id),
                    "first_input_id": str(self.scope.first_input_id),
                }
                if isinstance(self.scope, ModelDecisionScope)
                else {"operation_id": self.scope.operation_id}
            ),
            "ordinal": self.ordinal,
        }
        object.__setattr__(self, "decision_id", _digest(identity))
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


type ModelDecisionRecord = ModelDecisionArmed | ModelDecisionCompleted


class ModelDecisionJournal(Protocol):
    async def latest(self, scope: DecisionScope) -> ModelDecisionRecord | None:
        """Return original durable truth, after host action recovery has priority.

        Host claim selection MUST restore the record's exact original input IDs,
        checkpoint, and as_of before returning a claim. It MUST consult this
        journal before spending retry attempts or treating input as poison.
        """
        ...

    async def arm(self, request: ModelDecisionRequest) -> None:
        """Atomically store original request and uncertainty under current claim.

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

    async def release_undispatched(self, request: ModelDecisionRequest) -> None:
        """Remove only a record the kernel armed but never submitted to the provider.

        The caller must observe cancellation after arm and before provider-method
        entry. No exception after provider entry, including TurnNotStarted, is
        such proof. This is not general uncertainty reconciliation.
        """
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


__all__ = [
    "DecisionScope",
    "DurableIsolatedDecisions",
    "IsolatedDecisionScope",
    "IsolatedModelDecisions",
    "ModelDecisionArmed",
    "ModelDecisionCompleted",
    "ModelDecisionDefect",
    "ModelDecisionJournal",
    "ModelDecisionRecord",
    "ModelDecisionRequest",
    "ModelDecisionScope",
    "ModelDecisionUncertain",
    "TransientModelDecisions",
]
