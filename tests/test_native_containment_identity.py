"""Temporary exact provider policy identity proof; no provider inference."""

from dataclasses import replace

import pytest
from provider_runtime.agent_runtime import (
    CODEX_CONTAINMENT_CATALOG_REVISION,
    CODEX_CONTAINMENT_VERSION,
    TextAgentOutput,
)

from llm_agent_kernel import NativeDefinition, definitions, native_contract
from test_slice0_contracts import _definition


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("CODEX_CONTAINMENT_CATALOG_REVISION", CODEX_CONTAINMENT_CATALOG_REVISION),
        ("CODEX_CONTAINMENT_VERSION", CODEX_CONTAINMENT_VERSION),
    ),
)
def test_policy_revision_rotates_both_protocols(monkeypatch, field, value):
    isolated = _definition()
    native = NativeDefinition(
        isolated.provider,
        isolated.role,
        TextAgentOutput(),
        isolated.maximum_profile,
        "controlled-policy-proof",
    )
    monkeypatch.setattr(definitions, field, value + ":changed", raising=False)
    monkeypatch.setattr(native_contract, field, value + ":changed", raising=False)
    assert replace(isolated).fingerprint != isolated.fingerprint
    assert replace(native).fingerprint != native.fingerprint
