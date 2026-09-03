"""Bounded, payload-free observability contracts."""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from .definitions import RunId

_ATTRIBUTE_NAME = re.compile(r"[a-z][a-z0-9_]*\Z")
_MAX_ATTRIBUTE_NAME_BYTES = 64
_MAX_ATTRIBUTE_TEXT_BYTES = 1_024
_MAX_ATTRIBUTES = 32
_MAX_RUN_ID_BYTES = 256
_MAX_INTEGER = 2**63 - 1
_PRIVATE_NAME_PARTS = frozenset(
    {
        "argument",
        "arguments",
        "content",
        "credential",
        "credentials",
        "memory",
        "payload",
        "prompt",
        "prompts",
        "result",
        "results",
        "session_ref",
        "text",
    }
)


class EventKind(StrEnum):
    claim = "claim"
    admission = "admission"
    provider_turn = "provider_turn"
    validation = "validation"
    tool_dispatch = "tool_dispatch"
    suspension = "suspension"
    settlement = "settlement"
    usage = "usage"
    cancellation = "cancellation"
    outcome = "outcome"


type EventValue = None | bool | int | float | str


@dataclass(frozen=True, slots=True)
class EventAttribute:
    name: str
    value: EventValue

    def __post_init__(self) -> None:
        if (
            type(self.name) is not str
            or len(self.name.encode("utf-8")) > _MAX_ATTRIBUTE_NAME_BYTES
            or _ATTRIBUTE_NAME.fullmatch(self.name) is None
        ):
            raise ValueError("event attribute name is invalid")
        parts = set(self.name.split("_"))
        if self.name == "session_ref" or parts.intersection(_PRIVATE_NAME_PARTS):
            raise ValueError("private payload fields are forbidden in default events")
        if type(self.value) not in (type(None), bool, int, float, str):
            raise TypeError("event attributes must be scalar metadata")
        if type(self.value) is str and len(self.value.encode("utf-8")) > _MAX_ATTRIBUTE_TEXT_BYTES:
            raise ValueError("event text metadata exceeds its byte limit")
        if type(self.value) is int and abs(self.value) > _MAX_INTEGER:
            raise ValueError("event integer metadata exceeds its range")
        if isinstance(self.value, float) and not math.isfinite(self.value):
            raise ValueError("event numeric metadata must be finite")


@dataclass(frozen=True, slots=True)
class KernelEvent:
    run_id: RunId
    kind: EventKind
    occurred_at: datetime
    attributes: tuple[EventAttribute, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, RunId):
            raise TypeError("kernel event run id must be RunId")
        if len(self.run_id.encode("utf-8")) > _MAX_RUN_ID_BYTES:
            raise ValueError("kernel event run id exceeds its byte limit")
        if not isinstance(self.kind, EventKind):
            raise TypeError("kernel event kind must be EventKind")
        if (
            not isinstance(self.occurred_at, datetime)
            or self.occurred_at.tzinfo is None
            or self.occurred_at.utcoffset() is None
        ):
            raise ValueError("kernel event time must be timezone-aware")
        if type(self.attributes) is not tuple or any(
            not isinstance(attribute, EventAttribute) for attribute in self.attributes
        ):
            raise TypeError("kernel event attributes must be a tuple of EventAttribute")
        if len(self.attributes) > _MAX_ATTRIBUTES:
            raise ValueError("kernel event has too many attributes")
        names = tuple(attribute.name for attribute in self.attributes)
        if len(names) != len(set(names)):
            raise ValueError("kernel event attribute names must be unique")


class EventSink(Protocol):
    """Best-effort metadata sink whose implementation must return promptly."""

    def emit(self, event: KernelEvent) -> None: ...


class DiagnosticKind(StrEnum):
    provider_input = "provider_input"
    provider_terminal = "provider_terminal"


class RedactedText(str):
    """Text a caller-provided redactor explicitly marked safe to retain."""


@dataclass(frozen=True, slots=True)
class DiagnosticRecord:
    run_id: RunId
    kind: DiagnosticKind
    content: RedactedText

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, RunId):
            raise TypeError("diagnostic record run id must be RunId")
        if not isinstance(self.kind, DiagnosticKind):
            raise TypeError("diagnostic record kind must be DiagnosticKind")
        if not isinstance(self.content, RedactedText):
            raise TypeError("diagnostic content must be explicitly redacted")


class DiagnosticSink(Protocol):
    def emit(self, record: DiagnosticRecord) -> None: ...


@dataclass(frozen=True, slots=True)
class DiagnosticTranscript:
    """Explicit opt-in boundary for caller-redacted private transcript material."""

    sink: DiagnosticSink
    redact: Callable[[str], RedactedText]

    def __post_init__(self) -> None:
        if not callable(self.redact):
            raise TypeError("diagnostic redactor must be callable")


def emit_event(sink: EventSink | None, event: KernelEvent) -> None:
    """Emit non-canonical telemetry; sink failure cannot fail host work."""

    if sink is None:
        return
    try:
        sink.emit(event)
    except Exception:
        pass


def emit_diagnostic(
    transcript: DiagnosticTranscript | None,
    run_id: RunId,
    kind: DiagnosticKind,
    private_content: str,
) -> None:
    """Redact before a best-effort diagnostic value crosses the sink boundary."""

    if transcript is None:
        return
    try:
        redacted = transcript.redact(private_content)
        if not isinstance(redacted, RedactedText):
            raise TypeError("diagnostic redactor must return RedactedText")
        transcript.sink.emit(DiagnosticRecord(run_id, kind, redacted))
    except Exception:
        pass


__all__ = [
    "EventAttribute",
    "DiagnosticKind",
    "DiagnosticRecord",
    "DiagnosticSink",
    "DiagnosticTranscript",
    "EventKind",
    "EventSink",
    "EventValue",
    "KernelEvent",
    "RedactedText",
    "emit_diagnostic",
    "emit_event",
]
