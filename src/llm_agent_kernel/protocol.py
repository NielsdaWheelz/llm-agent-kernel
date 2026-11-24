"""Closed model-step grammar and independent semantic validation."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated, Any, Literal, cast

from llm_tools import FrozenToolPlan, ToolId, canonical_json_bytes
from provider_runtime.agent_runtime import (
    AgentTerminal,
    JsonSchemaAgentOutput,
    OutputSchemaMismatch,
    decode_agent_output,
    thaw_json_value,
)
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

from .definitions import CallToolStep, FinishStep, StructuredOutput
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


class _CallToolStep(_ClosedStep):
    type: Literal["call_tool"]
    tool_id: _CanonicalToolId
    arguments: dict[str, _JsonValue]


class _StructuredFinishStep(_ClosedStep):
    type: Literal["finish"]
    reason: str | None = None

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("finish reason must not be blank")
        return value


class ProtocolValidationError(ValueError):
    """A complete model value violates the grammar or output contract."""

    def __init__(self, message: str, stage: str, /, **attributes: str | int) -> None:
        super().__init__(message)
        self.attributes = {"failure_stage": stage, **attributes}


type ValidatedStep = ValidatedToolCall | FinishStep


def provider_wire_schema(output_contract: StructuredOutput) -> dict[str, object]:
    """Return the Codex-compatible envelope schema for one output contract."""

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
    if not isinstance(output_contract, StructuredOutput):
        raise TypeError("isolated output must be StructuredOutput")
    result_schema = cast(dict[str, object], thaw_json_value(output_contract.wire_schema))
    definitions = result_schema.pop("$defs", None)
    finish_properties: dict[str, object] = {
        "reason": {"type": ["string", "null"]},
        "result": result_schema,
    }
    finish_payload: dict[str, object] = {
        "type": "object",
        "properties": finish_properties,
        "required": list(finish_properties),
        "additionalProperties": False,
    }

    schema: dict[str, object] = {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": ["call_tool", "finish"]},
            "call_tool": {"anyOf": [call_tool_payload, {"type": "null"}]},
            "finish": {"anyOf": [finish_payload, {"type": "null"}]},
        },
        "required": ["type", "call_tool", "finish"],
        "additionalProperties": False,
    }
    if definitions is not None:
        schema["$defs"] = definitions
    _audit_provider_wire_schema(schema)
    return schema


def _validate_terminal_step(
    output: JsonSchemaAgentOutput,
    terminal: AgentTerminal,
    output_contract: StructuredOutput,
    plan: FrozenToolPlan,
    *,
    diagnostic_fields: tuple[str, ...] | None,
) -> ValidatedStep:
    try:
        value = decode_agent_output(output, terminal)
    except OutputSchemaMismatch:
        raise ProtocolValidationError(
            "provider output is not strict JSON", "strict_decode"
        ) from None
    return validate_provider_step(value, output_contract, plan, diagnostic_fields=diagnostic_fields)


def validate_provider_step(
    value: object,
    output_contract: StructuredOutput,
    plan: FrozenToolPlan,
    *,
    diagnostic_fields: tuple[str, ...] | None = None,
) -> ValidatedStep:
    """Decode the provider wire envelope, then validate the logical model step."""

    logical_value = _decode_provider_step(value)
    return validate_model_step(
        logical_value, output_contract, plan, diagnostic_fields=diagnostic_fields
    )


def validate_model_step(
    value: object,
    output_contract: StructuredOutput,
    plan: FrozenToolPlan,
    *,
    diagnostic_fields: tuple[str, ...] | None = None,
) -> ValidatedStep:
    """Validate a whole step before returning text or a dispatchable proposal."""

    logical = thaw_json_value(value)
    try:
        encoded = canonical_json_bytes(logical)
    except ValueError:
        raise ProtocolValidationError("model step is not canonical JSON", "strict_decode") from None
    adapter = _step_adapter(output_contract)
    try:
        step = adapter.validate_json(encoded, strict=True)
    except ValidationError as error:
        if not isinstance(logical, dict) or logical.get("type") != "finish":
            raise ProtocolValidationError(
                "model step violates its branch", "branch_or_tool"
            ) from None
        if diagnostic_fields is None:
            raise ProtocolValidationError(
                "model step violates the closed output contract", "result_validation"
            ) from None
        raise _finish_validation_error(error, diagnostic_fields) from None

    if isinstance(step, _CallToolStep):
        public_step = CallToolStep(ToolId(step.tool_id), dict(step.arguments))
        try:
            return validate_tool_call(public_step, plan)
        except ToolProposalError:
            raise ProtocolValidationError(
                "model step proposes an invalid tool call", "branch_or_tool"
            ) from None
    result = TypeAdapter(output_contract.result_type).dump_python(step.result, mode="json")
    return FinishStep(reason=step.reason, result=result)


def _finish_validation_error(
    error: ValidationError, fields: tuple[str, ...]
) -> ProtocolValidationError:
    field_indexes = {field: index for index, field in enumerate(fields)}
    attributes: dict[str, str | int] = {}
    extra_fields = 0
    result_failed = False
    for detail in error.errors(include_url=False, include_context=False, include_input=False):
        location = detail["loc"]
        if location[:2] != ("finish", "result"):
            attributes["unmapped"] = "invalid_value"
            continue
        result_failed = True
        field = location[2] if len(location) >= 3 else None
        if (
            len(location) == 3
            and detail["type"] == "extra_forbidden"
            and field not in field_indexes
        ):
            extra_fields += 1
            continue
        if isinstance(field, str) and field in field_indexes:
            code = "invalid_value"
            if len(location) == 3:
                code = _FIELD_VALIDATION_CODES.get(detail["type"], code)
            attributes.setdefault(f"field_{field_indexes[field]}", code)
        else:
            attributes["unmapped"] = "invalid_value"
    if extra_fields:
        attributes["extra_fields"] = extra_fields
    return ProtocolValidationError(
        "model step violates the closed output contract",
        "result_validation" if result_failed else "wire_envelope",
        **attributes,
    )


_FIELD_VALIDATION_CODES = {
    "invalid_text": "invalid_text",
    "missing": "missing",
    "string_too_long": "invalid_text",
    "string_too_short": "invalid_text",
    "string_type": "wrong_type",
}


@lru_cache
def _structured_adapter(result_type: type[object]) -> TypeAdapter[Any]:
    finish = create_model(
        "StructuredFinishStep",
        __base__=_StructuredFinishStep,
        result=(result_type, ...),
    )
    step_type = Annotated[_CallToolStep | finish, Field(discriminator="type")]
    return TypeAdapter(step_type)


def _step_adapter(output_contract: StructuredOutput) -> TypeAdapter[Any]:
    if not isinstance(output_contract, StructuredOutput):
        raise TypeError("isolated output must be StructuredOutput")
    return _structured_adapter(output_contract.result_type)


class _InvalidArgumentsJson(ValueError):
    pass


def _decode_provider_step(value: object) -> dict[str, object]:
    thawed = thaw_json_value(value)
    if type(thawed) is not dict or set(thawed) != {"type", "call_tool", "finish"}:
        raise ProtocolValidationError(
            "provider step violates the closed wire envelope", "wire_envelope"
        )
    step_type = thawed["type"]
    if type(step_type) is not str:
        raise ProtocolValidationError(
            "provider step violates the closed wire envelope", "wire_envelope"
        )

    if step_type == "call_tool":
        payload = _selected_payload(thawed, "call_tool")
        if (
            set(payload) != {"tool_id", "arguments"}
            or type(payload["tool_id"]) is not str
            or type(payload["arguments"]) is not str
        ):
            raise ProtocolValidationError("provider tool payload is malformed", "wire_envelope")
        arguments = _decode_arguments_json(payload["arguments"])
        return {
            "type": "call_tool",
            "tool_id": payload["tool_id"],
            "arguments": arguments,
        }

    if step_type == "finish":
        payload = _selected_payload(thawed, "finish")
        expected = {"reason", "result"}
        if set(payload) != expected:
            raise ProtocolValidationError("provider finish payload is malformed", "wire_envelope")
        reason = payload["reason"]
        if reason is not None and type(reason) is not str:
            raise ProtocolValidationError("provider finish reason is malformed", "wire_envelope")
        if type(payload["result"]) is not dict:
            raise ProtocolValidationError("provider finish result is malformed", "wire_envelope")
        return {"type": "finish", "reason": reason, "result": payload["result"]}

    raise ProtocolValidationError("provider step type is unknown", "branch_or_tool")


def _selected_payload(value: dict[str, object], selected: str) -> dict[str, object]:
    for name in ("call_tool", "finish"):
        payload = value[name]
        if name == selected:
            if type(payload) is not dict:
                raise ProtocolValidationError(
                    "selected provider step payload is absent", "branch_or_tool"
                )
        elif payload is not None:
            raise ProtocolValidationError(
                "provider step selected multiple branch payloads", "branch_or_tool"
            )
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
        raise ProtocolValidationError(
            "provider tool arguments are not strict JSON", "branch_or_tool"
        ) from None
    if type(decoded) is not dict:
        raise ProtocolValidationError(
            "provider tool arguments must encode one JSON object", "branch_or_tool"
        )
    return decoded


def _audit_provider_wire_schema(schema: dict[str, object]) -> None:
    if schema.get("type") != "object" or "anyOf" in schema or "oneOf" in schema:
        raise ValueError("provider wire schema root must be one object")

    def walk(node: object) -> None:
        if isinstance(node, dict):
            additional = node.get("additionalProperties")
            if isinstance(additional, dict):
                raise ValueError("provider wire schema contains a map-shaped object")
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
                    raise ValueError("provider wire schema contains a non-strict object")
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
    "provider_wire_schema",
    "validate_provider_step",
    "validate_model_step",
]
