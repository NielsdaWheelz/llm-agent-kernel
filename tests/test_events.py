from __future__ import annotations

from llm_agent_kernel.definitions import RunId
from llm_agent_kernel.events import (
    DiagnosticKind,
    DiagnosticRecord,
    DiagnosticTranscript,
    RedactedText,
    emit_diagnostic,
)


class _FailingSink:
    def emit(self, record: DiagnosticRecord) -> None:
        del record
        raise RuntimeError("sink unavailable")


def test_diagnostic_redactor_and_sink_failures_are_nonfatal() -> None:
    run_id = RunId("run-1")

    def fail_redaction(_text: str) -> RedactedText:
        raise RuntimeError("redactor unavailable")

    emit_diagnostic(
        DiagnosticTranscript(_FailingSink(), fail_redaction),
        run_id,
        DiagnosticKind.provider_input,
        "private",
    )
    emit_diagnostic(
        DiagnosticTranscript(_FailingSink(), lambda _text: RedactedText("safe")),
        run_id,
        DiagnosticKind.provider_input,
        "private",
    )
