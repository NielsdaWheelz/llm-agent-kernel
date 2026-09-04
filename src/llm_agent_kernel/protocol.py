"""Closed model-step grammar and independent semantic validation."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated, Any, Literal, cast

from llm_tools import FrozenToolPlan, ToolId
from provider_runtime.agent_runtime import thaw_json_value
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    create_model,
    field_validator,
)

from .definitions import (
    CallToolStep,
    ConversationalOutput,
    FinishStep,
    OutputContract,
    SayStep,
    StructuredOutput,
)
from .tools import ToolProposalError, ValidatedToolCall, validate_tool_call

type _JsonValue = None | bool | int | float | str | list[_JsonValue] | dict[str, _JsonValue]
MODEL_STEP_OUTPUT_NAME = "llm_agent_kernel_step"


def _canonical_tool_id(value: str) -> str:
    try:
        return ToolId(value)
    except ValueError as exc:
        raise ValueError("tool_id must be canonical") from exc


_CanonicalToolId = Annotated[str, AfterValidator(_canonical_tool_id)]


class _ClosedStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)


class _SayStep(_ClosedStep):
    type: Literal["say"]
    text: str = Field(min_length=1)

    @field_validator("text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("say text must not be blank")
        return value


class _CallToolStep(_ClosedStep):
    type: Literal["call_tool"]
    tool_id: _CanonicalToolId
    arguments: dict[str, _JsonValue]


class _ConversationalFinishStep(_ClosedStep):
    type: Literal["finish"]
    reason: str | None = None

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("finish reason must not be blank")
        return value


class _StructuredFinishStep(_ConversationalFinishStep):
    type: Literal["finish"]


class ProtocolValidationError(ValueError):
    """A complete model value violates the grammar or output contract."""


type ValidatedStep = SayStep | ValidatedToolCall | FinishStep


def provider_wire_schema(output_contract: OutputContract) -> dict[str, object]:
    """Return the Codex-compatible envelope schema for one output contract."""

    say_payload: dict[str, object] = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
        "additionalProperties": False,
    }
    call_tool_payload: dict[str, object] = {
        "type": "object",
        "properties": {
            "tool_id": {"type": "string"},
            "arguments": {
                "type": "string",
                "description": "A strict JSON object encoded as a string.",
            },
        },
        "required": ["tool_id", "arguments"],
        "additionalProperties": False,
    }
    finish_properties: dict[str, object] = {
        "reason": {"type": ["string", "null"]},
    }
    definitions: dict[str, object] | None = None
    if isinstance(output_contract, StructuredOutput):
        result_schema = cast(dict[str, object], thaw_json_value(output_contract.wire_schema))
        raw_definitions = result_schema.pop("$defs", None)
        if raw_definitions is not None:
            definitions = cast(dict[str, object], raw_definitions)
        finish_properties["result"] = result_schema
    elif not isinstance(output_contract, ConversationalOutput):
        raise TypeError("unsupported output contract")
    finish_payload: dict[str, object] = {
        "type": "object",
        "properties": finish_properties,
        "required": list(finish_properties),
        "additionalProperties": False,
    }

    variants = ["call_tool", "finish"]
    say_schema: dict[str, object] = {"type": "null"}
    if isinstance(output_contract, ConversationalOutput):
        variants.insert(0, "say")
        say_schema = {"anyOf": [say_payload, {"type": "null"}]}
    schema: dict[str, object] = {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": variants},
            "say": say_schema,
            "call_tool": {"anyOf": [call_tool_payload, {"type": "null"}]},
            "finish": {"anyOf": [finish_payload, {"type": "null"}]},
        },
        "required": ["type", "say", "call_tool", "finish"],
        "additionalProperties": False,
    }
    if definitions is not None:
        schema["$defs"] = definitions
    _audit_provider_wire_schema(schema)
    return schema


def model_step_schema(output_contract: OutputContract) -> dict[str, object]:
    """Backward-compatible name for :func:`provider_wire_schema`."""

    return provider_wire_schema(output_contract)


def validate_provider_step(
    value: object,
    output_contract: OutputContract,
    plan: FrozenToolPlan,
) -> ValidatedStep:
    """Decode the provider wire envelope, then validate the logical model step."""

    logical_value = _decode_provider_step(value, output_contract)
    return validate_model_step(logical_value, output_contract, plan)


def validate_model_step(
    value: object,
    output_contract: OutputContract,
    plan: FrozenToolPlan,
) -> ValidatedStep:
    """Validate a whole step before returning text or a dispatchable proposal."""

    try:
        step = _step_adapter(output_contract).validate_python(
            thaw_json_value(value),
            strict=True,
        )
    except ValidationError:
        raise ProtocolValidationError("model step violates the closed output contract") from None

    if isinstance(step, _CallToolStep):
        public_step = CallToolStep(ToolId(step.tool_id), dict(step.arguments))
        try:
            return validate_tool_call(public_step, plan)
        except ToolProposalError:
            raise ProtocolValidationError("model step proposes an invalid tool call") from None
    if isinstance(step, _SayStep):
        return SayStep(step.text)
    if isinstance(output_contract, ConversationalOutput):
        return FinishStep(reason=step.reason)
    assert isinstance(output_contract, StructuredOutput)
    adapter = TypeAdapter(output_contract.result_type)
    result = adapter.dump_python(step.result, mode="json")
    return FinishStep(reason=step.reason, result=result)


@lru_cache
def _structured_adapter(result_type: type[object]) -> TypeAdapter[Any]:
    finish = create_model(
        "StructuredFinishStep",
        __base__=_StructuredFinishStep,
        result=(result_type, ...),
    )
    step_type = Annotated[_CallToolStep | finish, Field(discriminator="type")]
    return TypeAdapter(step_type)


_CONVERSATIONAL_ADAPTER = TypeAdapter(
    Annotated[
        _SayStep | _CallToolStep | _ConversationalFinishStep,
        Field(discriminator="type"),
    ]
)


def _step_adapter(output_contract: OutputContract) -> TypeAdapter[Any]:
    if isinstance(output_contract, ConversationalOutput):
        return _CONVERSATIONAL_ADAPTER
    if isinstance(output_contract, StructuredOutput):
        return _structured_adapter(output_contract.result_type)
    raise TypeError("unsupported output contract")


class _InvalidArgumentsJson(ValueError):
    pass


def _decode_provider_step(value: object, output_contract: OutputContract) -> dict[str, object]:
    thawed = thaw_json_value(value)
    if type(thawed) is not dict or set(thawed) != {"type", "say", "call_tool", "finish"}:
        raise ProtocolValidationError("provider step violates the closed wire envelope")
    step_type = thawed["type"]
    if type(step_type) is not str:
        raise ProtocolValidationError("provider step violates the closed wire envelope")

    if step_type == "say":
        if not isinstance(output_contract, ConversationalOutput):
            raise ProtocolValidationError("provider step violates the output contract")
        payload = _selected_payload(thawed, "say")
        if set(payload) != {"text"} or type(payload["text"]) is not str:
            raise ProtocolValidationError("provider say payload is malformed")
        return {"type": "say", "text": payload["text"]}

    if step_type == "call_tool":
        payload = _selected_payload(thawed, "call_tool")
        if (
            set(payload) != {"tool_id", "arguments"}
            or type(payload["tool_id"]) is not str
            or type(payload["arguments"]) is not str
        ):
            raise ProtocolValidationError("provider tool payload is malformed")
        arguments = _decode_arguments_json(payload["arguments"])
        return {
            "type": "call_tool",
            "tool_id": payload["tool_id"],
            "arguments": arguments,
        }

    if step_type == "finish":
        payload = _selected_payload(thawed, "finish")
        expected = {"reason"}
        if isinstance(output_contract, StructuredOutput):
            expected.add("result")
        elif not isinstance(output_contract, ConversationalOutput):
            raise TypeError("unsupported output contract")
        if set(payload) != expected:
            raise ProtocolValidationError("provider finish payload is malformed")
        reason = payload["reason"]
        if reason is not None and type(reason) is not str:
            raise ProtocolValidationError("provider finish reason is malformed")
        logical: dict[str, object] = {"type": "finish", "reason": reason}
        if isinstance(output_contract, StructuredOutput):
            if type(payload["result"]) is not dict:
                raise ProtocolValidationError("provider finish result is malformed")
            logical["result"] = payload["result"]
        return logical

    raise ProtocolValidationError("provider step type is unknown")


def _selected_payload(value: dict[str, object], selected: str) -> dict[str, object]:
    for name in ("say", "call_tool", "finish"):
        payload = value[name]
        if name == selected:
            if type(payload) is not dict:
                raise ProtocolValidationError("selected provider step payload is absent")
        elif payload is not None:
            raise ProtocolValidationError("provider step selected multiple branch payloads")
    return cast(dict[str, object], value[selected])


def _decode_arguments_json(value: str) -> dict[str, object]:
    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, child in pairs:
            if key in result:
                raise _InvalidArgumentsJson
            result[key] = child
        return result

    def reject_constant(_value: str) -> object:
        raise _InvalidArgumentsJson

    try:
        decoded = json.loads(
            value,
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except (_InvalidArgumentsJson, ValueError, RecursionError):
        raise ProtocolValidationError("provider tool arguments are not strict JSON") from None
    if type(decoded) is not dict:
        raise ProtocolValidationError("provider tool arguments must encode one JSON object")
    return decoded


def _audit_provider_wire_schema(schema: dict[str, object]) -> None:
    if schema.get("type") != "object" or "anyOf" in schema or "oneOf" in schema:
        raise RuntimeError("provider wire schema root must be one object")

    def walk(node: object) -> None:
        if isinstance(node, dict):
            additional = node.get("additionalProperties")
            if isinstance(additional, dict):
                raise RuntimeError("provider wire schema contains a map-shaped object")
            schema_type = node.get("type")
            types = schema_type if isinstance(schema_type, list) else [schema_type]
            if "object" in types or "properties" in node:
                properties = node.get("properties")
                required = node.get("required")
                if (
                    not isinstance(properties, dict)
                    or node.get("additionalProperties") is not False
                    or not isinstance(required, list)
                    or required != list(properties)
                ):
                    raise RuntimeError("provider wire schema contains a non-strict object")
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(schema)


__all__ = [
    "MODEL_STEP_OUTPUT_NAME",
    "ProtocolValidationError",
    "ValidatedStep",
    "model_step_schema",
    "provider_wire_schema",
    "validate_provider_step",
    "validate_model_step",
]
