from __future__ import annotations

import json
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
from pydantic import AnyUrl, BaseModel, ConfigDict, Field

from llm_agent_kernel.definitions import (
    ConversationalOutput,
    FinishStep,
    SayStep,
    StructuredOutput,
)
from llm_agent_kernel.protocol import (
    ProtocolValidationError,
    model_step_schema,
    provider_wire_schema,
    validate_model_step,
    validate_provider_step,
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


class NestedResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str
    note: str | None = None


class OptionalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    count: int | None = None
    nested: NestedResult


class EmptyResult(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MapResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: dict[str, int]


class UnsupportedKeywordResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(json_schema_extra={"not": {"type": "string"}})


class UnsupportedFormatResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: AnyUrl


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


def _empty_plan():
    catalog = ToolCatalog.compose(())
    profile = CapabilityProfile(
        ProfileId("empty"),
        (),
        RunLimits(1, 1, 1_024, 1_024, 1, 10.0),
    ).freeze(catalog)
    return ToolPlan(profile.id, HostTable()).freeze(catalog, profile)


def _assert_codex_strict_subset(schema: dict[str, object]) -> None:
    assert schema["type"] == "object"
    assert "anyOf" not in schema
    assert "oneOf" not in schema

    def walk(node: object) -> None:
        if isinstance(node, dict):
            assert not isinstance(node.get("additionalProperties"), dict)
            schema_type = node.get("type")
            types = schema_type if isinstance(schema_type, list) else [schema_type]
            if "object" in types or "properties" in node:
                properties = cast(dict[str, object], node["properties"])
                assert node["additionalProperties"] is False
                assert node["required"] == list(properties)
            assert not set(node).intersection(
                {"allOf", "dependentRequired", "dependentSchemas", "if", "then", "else", "not"}
            )
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(schema)


def test_conversational_provider_schema_is_one_closed_required_object() -> None:
    schema = provider_wire_schema(ConversationalOutput())
    properties = cast(dict[str, dict[str, Any]], schema["properties"])

    _assert_codex_strict_subset(schema)
    assert model_step_schema(ConversationalOutput()) == schema
    assert properties["type"]["enum"] == ["say", "call_tool", "finish"]
    assert properties["say"]["anyOf"][1] == {"type": "null"}
    call_payload = properties["call_tool"]["anyOf"][0]
    assert call_payload["properties"]["arguments"]["type"] == "string"


def test_structured_provider_schema_requires_optional_and_nested_fields() -> None:
    contract = StructuredOutput("answer", OptionalResult)
    schema = provider_wire_schema(contract)
    properties = cast(dict[str, dict[str, Any]], schema["properties"])
    definitions = cast(dict[str, dict[str, Any]], schema["$defs"])

    _assert_codex_strict_subset(schema)
    assert properties["type"]["enum"] == ["call_tool", "finish"]
    assert properties["say"] == {"type": "null"}
    assert definitions["NestedResult"]["required"] == ["value", "note"]
    assert definitions["NestedResult"]["properties"]["note"]["anyOf"][1] == {"type": "null"}
    finish = properties["finish"]["anyOf"][0]
    result = finish["properties"]["result"]
    assert result["required"] == ["answer", "count", "nested"]
    assert "default" not in json.dumps(schema)


def test_empty_structured_result_is_explicitly_closed_and_required() -> None:
    schema = provider_wire_schema(StructuredOutput("empty", EmptyResult))
    finish = cast(dict[str, Any], cast(dict[str, Any], schema["properties"])["finish"])
    result = finish["anyOf"][0]["properties"]["result"]

    _assert_codex_strict_subset(schema)
    assert result["properties"] == {}
    assert result["required"] == []
    assert result["additionalProperties"] is False


def test_unrepresentable_result_contracts_fail_during_construction() -> None:
    with pytest.raises(ValueError, match="closed"):
        StructuredOutput("map", MapResult)
    with pytest.raises(ValueError, match="unsupported keyword.*not"):
        StructuredOutput("unsupported", UnsupportedKeywordResult)
    with pytest.raises(ValueError, match="unsupported format.*uri"):
        StructuredOutput("unsupported-format", UnsupportedFormatResult)


def test_provider_schema_and_compilation_are_deterministic() -> None:
    first = StructuredOutput("answer", OptionalResult)
    second = StructuredOutput("answer", OptionalResult)

    assert first.schema == second.schema
    assert first.wire_schema == second.wire_schema
    assert provider_wire_schema(first) == provider_wire_schema(second)


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


def test_provider_envelope_decodes_conversation_and_tool_arguments_to_logical_steps() -> None:
    plan, binding = _plan()
    say_value = freeze_json_object(
        {
            "type": "say",
            "say": {"text": "Ready."},
            "call_tool": None,
            "finish": None,
        }
    )
    call_value = freeze_json_object(
        {
            "type": "call_tool",
            "say": None,
            "call_tool": {
                "tool_id": "test.count",
                "arguments": '{"count":3}',
            },
            "finish": None,
        }
    )
    finish_value = freeze_json_object(
        {
            "type": "finish",
            "say": None,
            "call_tool": None,
            "finish": {"reason": None},
        }
    )

    assert validate_provider_step(say_value, ConversationalOutput(), plan) == SayStep("Ready.")
    validated = validate_provider_step(call_value, ConversationalOutput(), plan)
    assert isinstance(validated, ValidatedToolCall)
    assert validated.binding is binding
    assert validated.arguments == Input(count=3)
    assert validate_provider_step(finish_value, ConversationalOutput(), plan) == FinishStep()


def test_provider_tool_envelope_is_rejected_against_an_empty_plan() -> None:
    value = freeze_json_object(
        {
            "type": "call_tool",
            "say": None,
            "call_tool": {"tool_id": "test.count", "arguments": '{"count":3}'},
            "finish": None,
        }
    )

    with pytest.raises(ProtocolValidationError, match="invalid tool call"):
        validate_provider_step(value, ConversationalOutput(), _empty_plan())


def test_provider_envelope_decodes_structured_nested_optional_result() -> None:
    plan, _binding = _plan()
    contract = StructuredOutput("answer", OptionalResult)
    value = freeze_json_object(
        {
            "type": "finish",
            "say": None,
            "call_tool": None,
            "finish": {
                "reason": None,
                "result": {
                    "answer": "yes",
                    "count": None,
                    "nested": {"value": "nested", "note": None},
                },
            },
        }
    )

    assert validate_provider_step(value, contract, plan) == FinishStep(
        result={
            "answer": "yes",
            "count": None,
            "nested": {"value": "nested", "note": None},
        }
    )


@pytest.mark.parametrize(
    "value",
    [
        {
            "type": "say",
            "say": {"text": "hello"},
            "call_tool": {"tool_id": "test.count", "arguments": '{"count":1}'},
            "finish": None,
        },
        {
            "type": "call_tool",
            "say": None,
            "call_tool": {"tool_id": "test.count", "arguments": "[]"},
            "finish": None,
        },
        {
            "type": "call_tool",
            "say": None,
            "call_tool": {"tool_id": "test.count", "arguments": '{"count":1,"count":2}'},
            "finish": None,
        },
        {
            "type": "call_tool",
            "say": None,
            "call_tool": {"tool_id": "test.count", "arguments": '{"count":NaN}'},
            "finish": None,
        },
        {
            "type": "finish",
            "say": None,
            "call_tool": None,
            "finish": {"reason": None, "extra": True},
        },
        {
            "type": "progress",
            "say": None,
            "call_tool": None,
            "finish": None,
        },
        {"type": "say", "say": {"text": "old shape"}},
    ],
)
def test_provider_envelope_rejects_malformed_branches_and_argument_strings(
    value: dict[str, object],
) -> None:
    plan, _binding = _plan()

    with pytest.raises(ProtocolValidationError):
        validate_provider_step(freeze_json_object(value), ConversationalOutput(), plan)


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
