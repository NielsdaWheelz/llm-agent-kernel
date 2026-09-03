from __future__ import annotations

from typing import Any, cast

import pytest
from llm_tools import (
    Available,
    CapabilityProfile,
    HostTable,
    NoDeclaredError,
    PolicyEpoch,
    ProfileId,
    PromptDocument,
    ReplayPolicy,
    RunLimits,
    ToolBinding,
    ToolCatalog,
    ToolEffect,
    ToolFamily,
    ToolGrant,
    ToolId,
    ToolLimits,
    ToolPlan,
    ToolSpec,
)
from provider_runtime.agent_runtime import freeze_json_object
from pydantic import BaseModel, ConfigDict

from llm_agent_kernel.definitions import (
    ConversationalOutput,
    FinishStep,
    SayStep,
    StructuredOutput,
)
from llm_agent_kernel.protocol import (
    ProtocolValidationError,
    model_step_schema,
    validate_model_step,
)
from llm_agent_kernel.tools import ValidatedToolCall


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int


class Success(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: bool


class StructuredResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str


async def _must_not_run(value: object, context: object) -> object:
    raise AssertionError(f"pure validation dispatched: {value!r}, {context!r}")


def _plan():
    spec = ToolSpec(
        id=ToolId("test.count"),
        summary="Count a value",
        documentation=PromptDocument("Count one validated value."),
        input_type=Input,
        success_type=Success,
        error_type=NoDeclaredError,
        effect=ToolEffect.Read,
        limits=ToolLimits(1_024, 1_024, 1, 2.0),
    )
    binding = ToolBinding(
        spec=spec,
        execute=Available(_must_not_run),
        replay_policy=ReplayPolicy.ReDispatchable,
        implementation_revision="test-count-v1",
        policy_epoch=PolicyEpoch("v1"),
        policy_inputs={},
    )
    catalog = ToolCatalog.compose((ToolFamily("test", (spec,), (binding,)),))
    profile = CapabilityProfile(
        ProfileId("test"),
        (ToolGrant(spec.id, None),),
        RunLimits(3, 3, 8_192, 8_192, 1, 10.0),
    ).freeze(catalog)
    return ToolPlan(profile.id, HostTable()).freeze(catalog, profile), binding


def test_conversational_schema_is_one_closed_three_variant_value() -> None:
    schema = model_step_schema(ConversationalOutput())
    discriminator = cast(dict[str, Any], schema["discriminator"])
    definitions = cast(dict[str, dict[str, Any]], schema["$defs"])

    assert set(discriminator["mapping"]) == {"say", "call_tool", "finish"}
    assert all(
        value["additionalProperties"] is False
        for value in definitions.values()
        if value.get("type") == "object"
    )


def test_structured_schema_forbids_say_and_requires_the_exact_closed_result() -> None:
    schema = model_step_schema(StructuredOutput("answer", StructuredResult))
    discriminator = cast(dict[str, Any], schema["discriminator"])
    definitions = cast(dict[str, dict[str, Any]], schema["$defs"])

    assert set(discriminator["mapping"]) == {"call_tool", "finish"}
    result_schema = definitions["StructuredResult"]
    assert result_schema["additionalProperties"] is False
    assert definitions["StructuredFinishStep"]["required"] == ["type", "result"]


@pytest.mark.parametrize(
    "value",
    [
        {"type": "say", "text": ""},
        {"type": "say", "text": "   "},
        {"type": "say", "text": "hello", "result": {}},
        {"type": "finish", "result": {}},
        {"type": "call_tool", "tool_id": "test.count", "arguments": {}, "call_id": "x"},
        {"type": "call_tool", "tool_id": "Test.Count", "arguments": {"count": 1}},
        {"type": "say", "text": "hello", "tool_id": "test.count", "arguments": {}},
        {"type": "progress", "text": "working"},
        [
            {"type": "call_tool", "tool_id": "test.count", "arguments": {"count": 1}},
            {"type": "call_tool", "tool_id": "test.count", "arguments": {"count": 2}},
        ],
        '{"type":"say","text":"hello"} trailing prose',
    ],
)
def test_conversational_validation_rejects_empty_mixed_unknown_and_extra_values(
    value: object,
) -> None:
    plan, _binding = _plan()

    with pytest.raises(ProtocolValidationError):
        validate_model_step(value, ConversationalOutput(), plan)


@pytest.mark.parametrize(
    "forbidden_field",
    ["call_id", "effect_id", "preview", "authority", "approval", "credentials", "delivery"],
)
def test_call_tool_forbids_model_authored_host_authority_metadata(
    forbidden_field: str,
) -> None:
    plan, _binding = _plan()
    value = {
        "type": "call_tool",
        "tool_id": "test.count",
        "arguments": {"count": 1},
        forbidden_field: "model supplied",
    }

    with pytest.raises(ProtocolValidationError):
        validate_model_step(value, ConversationalOutput(), plan)


def test_conversational_validation_returns_public_atomic_steps() -> None:
    plan, _binding = _plan()

    say = validate_model_step(
        freeze_json_object({"type": "say", "text": "Ready."}),
        ConversationalOutput(),
        plan,
    )
    finish = validate_model_step(
        freeze_json_object({"type": "finish", "reason": "No visible answer needed."}),
        ConversationalOutput(),
        plan,
    )

    assert say == SayStep("Ready.")
    assert finish == FinishStep(reason="No visible answer needed.")


def test_structured_validation_forbids_say_and_strictly_validates_result() -> None:
    plan, _binding = _plan()
    contract = StructuredOutput("answer", StructuredResult)

    with pytest.raises(ProtocolValidationError):
        validate_model_step(
            freeze_json_object({"type": "say", "text": "not allowed"}),
            contract,
            plan,
        )
    with pytest.raises(ProtocolValidationError):
        validate_model_step(
            freeze_json_object({"type": "finish", "result": {"answer": 7}}),
            contract,
            plan,
        )
    with pytest.raises(ProtocolValidationError):
        validate_model_step(
            freeze_json_object({"type": "finish", "result": {"answer": "yes", "extra": True}}),
            contract,
            plan,
        )

    assert validate_model_step(
        freeze_json_object({"type": "finish", "result": {"answer": "yes"}}),
        contract,
        plan,
    ) == FinishStep(result={"answer": "yes"})


def test_call_tool_resolves_exact_binding_and_purely_decodes_owned_input() -> None:
    plan, binding = _plan()

    validated = validate_model_step(
        freeze_json_object(
            {"type": "call_tool", "tool_id": "test.count", "arguments": {"count": 3}}
        ),
        ConversationalOutput(),
        plan,
    )

    assert isinstance(validated, ValidatedToolCall)
    assert validated.binding is binding
    assert validated.arguments == Input(count=3)
    assert validated.step.tool_id == ToolId("test.count")


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"count": "3"},
        {"count": 3, "extra": True},
    ],
)
def test_invalid_tool_input_is_one_protocol_failure_before_dispatch(
    arguments: dict[str, Any],
) -> None:
    plan, _binding = _plan()

    with pytest.raises(ProtocolValidationError):
        validate_model_step(
            freeze_json_object(
                {"type": "call_tool", "tool_id": "test.count", "arguments": arguments}
            ),
            ConversationalOutput(),
            plan,
        )
