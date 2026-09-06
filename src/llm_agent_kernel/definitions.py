"""Immutable, provider-neutral kernel values."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Self

from llm_tools import (
    FrozenCapabilityProfile,
    FrozenToolPlan,
    InvocationPosition,
    PromptSections,
    ToolId,
    ToolResult,
    canonical_json_bytes,
    render_prompt,
)
from provider_runtime.agent_runtime import (
    CodexNativeOptions,
    CredentialRef,
    FrozenJsonDict,
    PermissionPolicy,
    ReasoningSpec,
    TextContent,
    freeze_json_object,
    freeze_json_value,
    thaw_json_value,
)
from pydantic import TypeAdapter

from ._schema import compile_structured_result_schema


class _NonEmptyId(str):
    def __new__(cls, value: str) -> Self:
        if type(value) is not str or not value:
            raise ValueError(f"{cls.__name__} must be a non-empty string")
        return str.__new__(cls, value)


class DefinitionId(_NonEmptyId):
    pass


class ThreadId(_NonEmptyId):
    pass


class RunId(_NonEmptyId):
    pass


class ClaimId(_NonEmptyId):
    pass


class InputId(_NonEmptyId):
    pass


class Checkpoint(_NonEmptyId):
    pass


class OwnerToken(_NonEmptyId):
    pass


class HostRef(_NonEmptyId):
    pass


class SessionMode(StrEnum):
    continuing = "continuing"
    isolated = "isolated"


class BatchAsOfMode(StrEnum):
    always = "always"
    never = "never"
    on_request = "on_request"


@dataclass(frozen=True, slots=True)
class InputProjectionRequest:
    """Invocation-local request for definition-authorized input context."""

    render_batch_as_of: bool = False

    def __post_init__(self) -> None:
        if type(self.render_batch_as_of) is not bool:
            raise TypeError("render_batch_as_of must be bool")


@dataclass(frozen=True, slots=True)
class InputProjectionPolicy:
    """Definition-bound policy for model-visible host-input metadata."""

    render_source_timestamps: bool = True
    batch_as_of: BatchAsOfMode = BatchAsOfMode.always

    def __post_init__(self) -> None:
        if type(self.render_source_timestamps) is not bool:
            raise TypeError("render_source_timestamps must be bool")
        if not isinstance(self.batch_as_of, BatchAsOfMode):
            raise TypeError("batch_as_of must be BatchAsOfMode")

    def resolve(self, request: InputProjectionRequest | None) -> tuple[bool, bool]:
        """Validate one request and return source/as-of rendering decisions."""

        if request is not None and not isinstance(request, InputProjectionRequest):
            raise TypeError("input projection request must be InputProjectionRequest")
        render_requested_as_of = request is not None and request.render_batch_as_of
        if self.batch_as_of is BatchAsOfMode.never and render_requested_as_of:
            raise ValueError("definition prohibits model-visible batch as_of")
        render_batch_as_of = self.batch_as_of is BatchAsOfMode.always or (
            self.batch_as_of is BatchAsOfMode.on_request and render_requested_as_of
        )
        return self.render_source_timestamps, render_batch_as_of


@dataclass(frozen=True, slots=True)
class ConversationalOutput:
    kind: Literal["conversational"] = field(default="conversational", init=False)


@dataclass(frozen=True, slots=True)
class StructuredOutput:
    name: str
    result_type: type[Any]
    schema: FrozenJsonDict = field(init=False, repr=False)
    wire_schema: FrozenJsonDict = field(init=False, repr=False)
    kind: Literal["structured"] = field(default="structured", init=False)

    def __post_init__(self) -> None:
        if type(self.name) is not str or not self.name.strip():
            raise ValueError("structured output name must not be empty")
        schema = TypeAdapter(self.result_type).json_schema()
        if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
            raise ValueError("structured output must have a closed object schema")
        _require_closed_objects(schema)
        object.__setattr__(self, "schema", freeze_json_object(schema, context="output schema"))
        object.__setattr__(
            self,
            "wire_schema",
            freeze_json_object(
                compile_structured_result_schema(schema),
                context="structured output wire schema",
            ),
        )


type OutputContract = ConversationalOutput | StructuredOutput


@dataclass(frozen=True, slots=True)
class KernelLimits:
    max_provider_turns: int = 8
    max_protocol_repairs: int = 2
    max_no_progress_attempts: int = 3
    max_cooperative_seconds: float = 600.0
    max_provider_input_tokens: int = 100_000
    max_provider_output_tokens: int = 20_000
    max_new_context_bytes: int = 1_000_000

    def __post_init__(self) -> None:
        positive_integers = (
            self.max_provider_turns,
            self.max_no_progress_attempts,
            self.max_provider_input_tokens,
            self.max_provider_output_tokens,
            self.max_new_context_bytes,
        )
        if any(type(value) is not int for value in positive_integers):
            raise TypeError("kernel count, token, and byte limits must be integers")
        if any(value <= 0 for value in positive_integers):
            raise ValueError("kernel count, token, and byte limits must be positive")
        if type(self.max_protocol_repairs) is not int:
            raise TypeError("protocol repair limit must be an integer")
        if self.max_protocol_repairs < 0:
            raise ValueError("protocol repair limit must not be negative")
        if type(self.max_cooperative_seconds) not in (int, float):
            raise TypeError("kernel cooperative limit must be numeric")
        if not math.isfinite(self.max_cooperative_seconds) or self.max_cooperative_seconds <= 0:
            raise ValueError("kernel cooperative limit must be positive and finite")


CONTAINMENT_POLICY = PermissionPolicy(
    filesystem="read_only",
    network="disabled",
    approval="deny",
    allowed_tools=("*",),
)
CODEX_NATIVE_OPTIONS = CodexNativeOptions(web_search=False, builtin_tools="disabled")


@dataclass(frozen=True, slots=True)
class ProviderConfiguration:
    auth: CredentialRef
    model: str
    reasoning: ReasoningSpec | None = None
    system: tuple[TextContent, ...] = ()
    developer: tuple[TextContent, ...] = ()
    policy: PermissionPolicy = CONTAINMENT_POLICY
    native: CodexNativeOptions = CODEX_NATIVE_OPTIONS
    backend: Literal["codex"] = field(default="codex", init=False)
    transport: Literal["sdk"] = field(default="sdk", init=False)
    cwd_scope: Literal["private_empty_read_only"] = field(
        default="private_empty_read_only", init=False
    )
    additional_dirs: tuple[()] = field(default=(), init=False)
    mcp_servers: tuple[()] = field(default=(), init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.auth, CredentialRef) or self.auth.kind != "local_account":
            raise ValueError("Codex requires a local-account credential reference")
        if type(self.model) is not str or not self.model.strip():
            raise ValueError("provider model must not be empty")
        if self.reasoning is not None and not isinstance(self.reasoning, ReasoningSpec):
            raise TypeError("provider reasoning must be ReasoningSpec when present")
        if type(self.system) is not tuple or any(
            not isinstance(part, TextContent) for part in self.system
        ):
            raise TypeError("provider system material must be a tuple of TextContent")
        if type(self.developer) is not tuple or any(
            not isinstance(part, TextContent) for part in self.developer
        ):
            raise TypeError("provider developer material must be a tuple of TextContent")
        if self.policy != CONTAINMENT_POLICY:
            raise ValueError("provider policy must use the complete v1 containment posture")
        if self.native != CODEX_NATIVE_OPTIONS:
            raise ValueError("Codex native built-ins and Web must be disabled")


@dataclass(frozen=True, slots=True)
class AgentRole:
    role_id: str
    instructions: PromptSections

    def __post_init__(self) -> None:
        if type(self.role_id) is not str or not self.role_id.strip():
            raise ValueError("role id must not be empty")
        if not isinstance(self.instructions, PromptSections):
            raise TypeError("role instructions must be PromptSections")


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    definition_id: DefinitionId
    role: AgentRole
    stable_context: PromptSections
    session_mode: SessionMode
    output_contract: OutputContract
    maximum_profile: FrozenCapabilityProfile
    provider: ProviderConfiguration
    session_compatibility_revision: str
    limits: KernelLimits = KernelLimits()
    input_projection_policy: InputProjectionPolicy = InputProjectionPolicy()
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.definition_id, DefinitionId):
            raise TypeError("definition id must be DefinitionId")
        if not isinstance(self.role, AgentRole):
            raise TypeError("definition role must be AgentRole")
        if not isinstance(self.stable_context, PromptSections):
            raise TypeError("stable context must be PromptSections")
        if not isinstance(self.session_mode, SessionMode):
            raise TypeError("session mode must be SessionMode")
        if not isinstance(self.output_contract, ConversationalOutput | StructuredOutput):
            raise TypeError("definition output contract is invalid")
        if not isinstance(self.maximum_profile, FrozenCapabilityProfile):
            raise TypeError("maximum profile must be frozen")
        if not self.maximum_profile.is_tightening_of(self.maximum_profile):
            raise ValueError("maximum profile is internally inconsistent")
        if not isinstance(self.provider, ProviderConfiguration):
            raise TypeError("definition provider configuration is invalid")
        if (
            type(self.session_compatibility_revision) is not str
            or not self.session_compatibility_revision.strip()
        ):
            raise ValueError("session compatibility revision must not be empty")
        if not isinstance(self.limits, KernelLimits):
            raise TypeError("definition limits must be KernelLimits")
        if not isinstance(self.input_projection_policy, InputProjectionPolicy):
            raise TypeError("definition input projection policy must be InputProjectionPolicy")
        object.__setattr__(self, "fingerprint", _definition_fingerprint(self))


@dataclass(frozen=True, slots=True)
class HostInput:
    input_id: InputId
    sections: PromptSections
    source_timestamp: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.input_id, InputId):
            raise TypeError("host input id must be InputId")
        if not isinstance(self.sections, PromptSections):
            raise TypeError("host input must contain PromptSections")
        _require_aware(self.source_timestamp, "host input source timestamp")


@dataclass(frozen=True, slots=True)
class InputClaim:
    claim_id: ClaimId
    inputs: tuple[HostInput, ...]
    through_checkpoint: Checkpoint
    as_of: datetime
    plan: FrozenToolPlan
    attempt_number: int

    def __post_init__(self) -> None:
        if not isinstance(self.claim_id, ClaimId):
            raise TypeError("claim id must be ClaimId")
        if type(self.inputs) is not tuple or not self.inputs:
            raise ValueError("an input claim must contain a non-empty tuple")
        if any(not isinstance(item, HostInput) for item in self.inputs):
            raise TypeError("claim inputs must be HostInput values")
        input_ids = tuple(item.input_id for item in self.inputs)
        if len(input_ids) != len(set(input_ids)):
            raise ValueError("claim input ids must be unique")
        if not isinstance(self.through_checkpoint, Checkpoint):
            raise TypeError("claim checkpoint must be Checkpoint")
        _require_aware(self.as_of, "claim as_of")
        if not isinstance(self.plan, FrozenToolPlan):
            raise TypeError("claim plan must be FrozenToolPlan")
        if type(self.attempt_number) is not int:
            raise TypeError("claim attempt number must be an integer")
        if self.attempt_number <= 0:
            raise ValueError("claim attempt number must be positive")


@dataclass(frozen=True, slots=True)
class DispatchLineage:
    claim_id: ClaimId
    through_checkpoint: Checkpoint
    input_ids: tuple[InputId, ...]
    model_step_ordinal: int

    def __post_init__(self) -> None:
        if not isinstance(self.claim_id, ClaimId):
            raise TypeError("dispatch claim id must be ClaimId")
        if not isinstance(self.through_checkpoint, Checkpoint):
            raise TypeError("dispatch checkpoint must be Checkpoint")
        if type(self.input_ids) is not tuple or not self.input_ids:
            raise ValueError("thread dispatch lineage requires input ids")
        if any(not isinstance(item, InputId) for item in self.input_ids):
            raise TypeError("dispatch input ids must be InputId values")
        _require_ordinal(self.model_step_ordinal)


@dataclass(frozen=True, slots=True)
class IsolatedDispatchLineage:
    """One model-authored isolated call and its exact dependency position."""

    run_id: RunId
    model_step_ordinal: int

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, RunId):
            raise TypeError("isolated dispatch run id must be RunId")
        _require_ordinal(self.model_step_ordinal)

    @property
    def position(self) -> InvocationPosition:
        return _isolated_position(self.run_id, "model_step", self.model_step_ordinal)


@dataclass(frozen=True, slots=True)
class InitialReadDispatchLineage:
    """The non-model initial Read and its exact dependency position."""

    run_id: RunId

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, RunId):
            raise TypeError("initial Read dispatch run id must be RunId")

    @property
    def position(self) -> InvocationPosition:
        return _isolated_position(self.run_id, "initial_read", None)


type ToolDispatchLineage = DispatchLineage | IsolatedDispatchLineage | InitialReadDispatchLineage


@dataclass(frozen=True, slots=True)
class SayStep:
    text: str
    type: Literal["say"] = field(default="say", init=False)

    def __post_init__(self) -> None:
        if type(self.text) is not str or not self.text.strip():
            raise ValueError("say text must not be empty")


@dataclass(frozen=True, slots=True)
class CallToolStep:
    tool_id: ToolId
    arguments: FrozenJsonDict
    type: Literal["call_tool"] = field(default="call_tool", init=False)

    def __init__(self, tool_id: ToolId, arguments: dict[str, object] | FrozenJsonDict) -> None:
        if not isinstance(tool_id, ToolId):
            raise TypeError("call_tool tool id must be ToolId")
        object.__setattr__(self, "tool_id", tool_id)
        object.__setattr__(
            self,
            "arguments",
            freeze_json_object(arguments, context="call_tool arguments"),
        )
        object.__setattr__(self, "type", "call_tool")


@dataclass(frozen=True, slots=True)
class InitialReadCall:
    """One host-selected Read used to construct isolated initial context."""

    tool_id: ToolId
    arguments: FrozenJsonDict

    def __init__(self, tool_id: ToolId, arguments: dict[str, object] | FrozenJsonDict) -> None:
        if not isinstance(tool_id, ToolId):
            raise TypeError("initial Read tool id must be ToolId")
        object.__setattr__(self, "tool_id", tool_id)
        object.__setattr__(
            self,
            "arguments",
            freeze_json_object(arguments, context="initial Read arguments"),
        )


@dataclass(frozen=True, slots=True)
class NoResult:
    pass


NO_RESULT = NoResult()


@dataclass(frozen=True, slots=True)
class FinishStep:
    reason: str | None = None
    result: object = NO_RESULT
    type: Literal["finish"] = field(default="finish", init=False)

    def __post_init__(self) -> None:
        if self.reason is not None and (type(self.reason) is not str or not self.reason.strip()):
            raise ValueError("finish reason must not be empty when present")
        if self.result is not NO_RESULT:
            object.__setattr__(
                self, "result", freeze_json_value(self.result, context="finish result")
            )


type ModelStep = SayStep | CallToolStep | FinishStep


class WaitingFor(StrEnum):
    user = "user"
    system = "system"


@dataclass(frozen=True, slots=True)
class DispatchCompleted:
    result: ToolResult
    type: Literal["completed"] = field(default="completed", init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.result, dict):
            raise TypeError("completed dispatch result must be an llm-tools ToolResult")


@dataclass(frozen=True, slots=True)
class DispatchSuspended:
    host_ref: HostRef
    waiting_for: WaitingFor
    type: Literal["suspended"] = field(default="suspended", init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.host_ref, HostRef):
            raise TypeError("suspension host ref must be HostRef")
        if not isinstance(self.waiting_for, WaitingFor):
            raise TypeError("suspension waiting actor must be WaitingFor")


type DispatchResult = DispatchCompleted | DispatchSuspended


@dataclass(frozen=True, slots=True)
class ConversationConclusion:
    text: str | None
    type: Literal["conversation"] = field(default="conversation", init=False)

    def __post_init__(self) -> None:
        if self.text is not None and (type(self.text) is not str or not self.text.strip()):
            raise ValueError("conversation text must not be empty when present")


@dataclass(frozen=True, slots=True)
class StructuredConclusion:
    result: object
    type: Literal["structured"] = field(default="structured", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "result", freeze_json_value(self.result, context="conclusion result")
        )


@dataclass(frozen=True, slots=True)
class SuspensionConclusion:
    host_ref: HostRef
    waiting_for: WaitingFor
    type: Literal["suspension"] = field(default="suspension", init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.host_ref, HostRef):
            raise TypeError("suspension host ref must be HostRef")
        if not isinstance(self.waiting_for, WaitingFor):
            raise TypeError("suspension waiting actor must be WaitingFor")


class StopReason(StrEnum):
    budget_exhausted = "budget_exhausted"
    cancelled = "cancelled"
    protocol_error = "protocol_error"
    provider_error = "provider_error"
    quota_exhausted = "quota_exhausted"
    stopped = "stopped"


@dataclass(frozen=True, slots=True)
class StoppedConclusion:
    reason: StopReason
    type: Literal["stopped"] = field(default="stopped", init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.reason, StopReason):
            raise TypeError("stopped conclusion reason must be StopReason")


type HostConclusion = (
    ConversationConclusion | StructuredConclusion | SuspensionConclusion | StoppedConclusion
)


@dataclass(frozen=True, slots=True)
class ProviderUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None

    def __post_init__(self) -> None:
        for value in (self.input_tokens, self.output_tokens):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("available provider token usage must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class RunMetrics:
    run_id: RunId
    provider_turns: int
    usage: ProviderUsage
    duration_seconds: float
    input_consumed: bool

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, RunId):
            raise TypeError("run metrics require a RunId")
        if type(self.provider_turns) is not int or self.provider_turns < 0:
            raise ValueError("provider turn count must be a non-negative integer")
        if not isinstance(self.usage, ProviderUsage):
            raise TypeError("run usage must be ProviderUsage")
        if type(self.duration_seconds) not in (int, float):
            raise TypeError("run duration must be numeric")
        if not math.isfinite(self.duration_seconds) or self.duration_seconds < 0:
            raise ValueError("run duration must be finite and non-negative")
        if type(self.input_consumed) is not bool:
            raise TypeError("input_consumed must be bool")


@dataclass(frozen=True, slots=True)
class ThreadCompleted:
    metrics: RunMetrics
    type: Literal["completed"] = field(default="completed", init=False)


@dataclass(frozen=True, slots=True)
class ThreadSuspended:
    metrics: RunMetrics
    host_ref: HostRef
    waiting_for: WaitingFor
    type: Literal["suspended"] = field(default="suspended", init=False)


@dataclass(frozen=True, slots=True)
class ThreadNoWork:
    metrics: RunMetrics
    type: Literal["no_work"] = field(default="no_work", init=False)


@dataclass(frozen=True, slots=True)
class ThreadBusy:
    metrics: RunMetrics
    type: Literal["busy"] = field(default="busy", init=False)


@dataclass(frozen=True, slots=True)
class ThreadDeferred:
    metrics: RunMetrics
    until: datetime
    type: Literal["deferred"] = field(default="deferred", init=False)

    def __post_init__(self) -> None:
        _require_aware(self.until, "thread deferral")


class ThreadStopKind(StrEnum):
    preempted = "preempted"
    cancelled = "cancelled"
    budget_exhausted = "budget_exhausted"
    quota_exhausted = "quota_exhausted"
    protocol_error = "protocol_error"
    provider_error = "provider_error"
    configuration_error = "configuration_error"


@dataclass(frozen=True, slots=True)
class ThreadStopped:
    metrics: RunMetrics
    type: ThreadStopKind

    def __post_init__(self) -> None:
        if not isinstance(self.type, ThreadStopKind):
            raise TypeError("thread stop type must be ThreadStopKind")


type ThreadOutcome = (
    ThreadCompleted | ThreadSuspended | ThreadNoWork | ThreadBusy | ThreadDeferred | ThreadStopped
)


@dataclass(frozen=True, slots=True)
class OneShotCompleted:
    metrics: RunMetrics
    result: object
    type: Literal["completed"] = field(default="completed", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "result", freeze_json_value(self.result, context="one-shot result")
        )


@dataclass(frozen=True, slots=True)
class OneShotStopped:
    metrics: RunMetrics
    type: ThreadStopKind

    def __post_init__(self) -> None:
        if not isinstance(self.type, ThreadStopKind):
            raise TypeError("one-shot stop type must be ThreadStopKind")


type OneShotOutcome = OneShotCompleted | OneShotStopped


def _require_aware(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_ordinal(value: int) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError("model step ordinal must be a positive integer")


def _isolated_position(
    run_id: RunId,
    origin: Literal["initial_read", "model_step"],
    model_step_ordinal: int | None,
) -> InvocationPosition:
    digest = hashlib.sha256(
        canonical_json_bytes(
            {
                "model_step_ordinal": model_step_ordinal,
                "namespace": "llm-agent-kernel-isolated-position-v1",
                "origin": origin,
                "run_id": str(run_id),
            }
        )
    ).hexdigest()
    return InvocationPosition(f"llm-agent-kernel-isolated-v1:{digest}")


def _require_closed_objects(value: object) -> None:
    if isinstance(value, dict):
        if (value.get("type") == "object" or "properties" in value) and value.get(
            "additionalProperties"
        ) is not False:
            raise ValueError("every structured output object must be closed")
        for child in value.values():
            _require_closed_objects(child)
    elif isinstance(value, list):
        for child in value:
            _require_closed_objects(child)


def _definition_fingerprint(definition: AgentDefinition) -> str:
    from .protocol import MODEL_STEP_OUTPUT_NAME, provider_wire_schema

    output: dict[str, object]
    if isinstance(definition.output_contract, ConversationalOutput):
        output = {"kind": "conversational"}
    else:
        output = {
            "kind": "structured",
            "name": definition.output_contract.name,
            "schema": thaw_json_value(definition.output_contract.schema),
        }
    provider = definition.provider
    value = {
        "definition_id": str(definition.definition_id),
        "input_projection_policy": {
            "batch_as_of": definition.input_projection_policy.batch_as_of.value,
            "render_source_timestamps": (
                definition.input_projection_policy.render_source_timestamps
            ),
        },
        "limits": {
            "max_new_context_bytes": definition.limits.max_new_context_bytes,
            "max_protocol_repairs": definition.limits.max_protocol_repairs,
            "max_no_progress_attempts": definition.limits.max_no_progress_attempts,
            "max_provider_input_tokens": definition.limits.max_provider_input_tokens,
            "max_provider_output_tokens": definition.limits.max_provider_output_tokens,
            "max_provider_turns": definition.limits.max_provider_turns,
            "max_cooperative_seconds": definition.limits.max_cooperative_seconds,
        },
        "maximum_profile_revision": definition.maximum_profile.profile_revision,
        "output_contract": output,
        "provider_output": {
            "name": MODEL_STEP_OUTPUT_NAME,
            "schema": provider_wire_schema(definition.output_contract),
        },
        "provider": {
            "additional_dirs": [],
            "auth": {
                "kind": provider.auth.kind,
                "name": provider.auth.name,
                "profile_key": provider.auth.profile_key,
            },
            "backend": provider.backend,
            "cwd_scope": provider.cwd_scope,
            "developer": [part.text for part in provider.developer],
            "mcp_servers": [],
            "model": provider.model,
            "native": {
                "builtin_tools": provider.native.builtin_tools,
                "web_search": provider.native.web_search,
            },
            "policy": {
                "approval": provider.policy.approval,
                "allowed_tools": list(provider.policy.allowed_tools),
                "denied_tools": list(provider.policy.denied_tools),
                "environment": list(provider.policy.environment),
                "filesystem": provider.policy.filesystem,
                "network": provider.policy.network,
                "network_allowlist": list(provider.policy.network_allowlist),
            },
            "reasoning": None
            if provider.reasoning is None
            else {
                "effort": provider.reasoning.effort,
                "summary": provider.reasoning.summary,
                "thinking_budget": provider.reasoning.thinking_budget,
            },
            "system": [part.text for part in provider.system],
            "transport": provider.transport,
        },
        "role": {
            "id": definition.role.role_id,
            "instructions": render_prompt(definition.role.instructions),
        },
        "session_compatibility_revision": definition.session_compatibility_revision,
        "session_mode": definition.session_mode.value,
        "stable_context": render_prompt(definition.stable_context),
    }
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


__all__ = [
    "BatchAsOfMode",
    "CODEX_NATIVE_OPTIONS",
    "CONTAINMENT_POLICY",
    "NO_RESULT",
    "AgentDefinition",
    "AgentRole",
    "CallToolStep",
    "Checkpoint",
    "ClaimId",
    "ConversationConclusion",
    "ConversationalOutput",
    "DefinitionId",
    "DispatchCompleted",
    "DispatchLineage",
    "DispatchResult",
    "DispatchSuspended",
    "FinishStep",
    "HostConclusion",
    "HostInput",
    "HostRef",
    "InputClaim",
    "InputId",
    "InputProjectionPolicy",
    "InputProjectionRequest",
    "InitialReadCall",
    "InitialReadDispatchLineage",
    "IsolatedDispatchLineage",
    "KernelLimits",
    "ModelStep",
    "NoResult",
    "OneShotCompleted",
    "OneShotOutcome",
    "OneShotStopped",
    "OutputContract",
    "OwnerToken",
    "ProviderConfiguration",
    "ProviderUsage",
    "RunId",
    "RunMetrics",
    "SayStep",
    "SessionMode",
    "StopReason",
    "StructuredConclusion",
    "StructuredOutput",
    "SuspensionConclusion",
    "StoppedConclusion",
    "ThreadBusy",
    "ThreadCompleted",
    "ThreadDeferred",
    "ThreadId",
    "ThreadNoWork",
    "ThreadOutcome",
    "ThreadStopKind",
    "ThreadStopped",
    "ThreadSuspended",
    "ToolDispatchLineage",
    "WaitingFor",
]
