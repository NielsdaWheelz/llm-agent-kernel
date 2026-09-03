"""Closed model-step grammar and independent semantic validation."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any, Literal

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


def model_step_schema(output_contract: OutputContract) -> dict[str, object]:
    """Return the exact provider schema for one output contract."""

    return dict(_step_adapter(output_contract).json_schema())


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


__all__ = [
    "MODEL_STEP_OUTPUT_NAME",
    "ProtocolValidationError",
    "ValidatedStep",
    "model_step_schema",
    "validate_model_step",
]
