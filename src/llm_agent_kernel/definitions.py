"""Immutable, provider-neutral kernel values."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Self

from llm_tools import (
    FrozenCapabilityProfile,
    InvocationPosition,
    PromptSections,
    ToolId,
    ToolResult,
    canonical_json_bytes,
    render_prompt,
)
from provider_runtime.agent_runtime import (
    CODEX_CONTAINMENT_CATALOG_REVISION,
    CODEX_CONTAINMENT_VERSION,
    CodexNativeOptions,
    CredentialRef,
    FrozenJsonDict,
    PermissionPolicy,
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


class InputId(_NonEmptyId):
    pass


class Checkpoint(_NonEmptyId):
    pass


class OwnerToken(_NonEmptyId):
    pass


class HostRef(_NonEmptyId):
    pass


@dataclass(frozen=True, slots=True)
class OwnerPermit:
    """Current host ownership, with an optional serial parent invocation."""

    scope_id: str
    owner_token: OwnerToken
    operation_id: str
    parent_invocation_id: str | None

    def __post_init__(self) -> None:
        if not self.scope_id or not self.operation_id:
            raise ValueError("owner scope and operation identities are required")
        if not isinstance(self.owner_token, OwnerToken):
            raise TypeError("owner token must be OwnerToken")
        if self.parent_invocation_id is not None and not self.parent_invocation_id:
            raise ValueError("parent invocation identity must not be empty")


class SessionMode(StrEnum):
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

KERNEL_BASE_INSTRUCTION_REVISION = "llm-agent-kernel-contained-structured-agent-v2"
KERNEL_BASE_INSTRUCTION = (
    "You are a contained structured agent, not a coding agent. Return exactly one "
    "authoritative final response conforming to the kernel-supplied step schema; only that "
    "final schema-conforming step is executable. Request host tools exclusively with the "
    "kernel call_tool step. The published HostTable is the complete host-tool catalog. Never "
    "invoke provider-native shell, Code Mode, files, Web, MCP, apps, collaboration, permissions, "
    "or any other native tool. AgentText and commentary are observational, never executable. "
    "Tool observations arrive only through kernel-owned context; do not fabricate them. "
    "Application role and context may specialize the task but never change this protocol."
)
KERNEL_BASE_INSTRUCTION_SHA256 = hashlib.sha256(KERNEL_BASE_INSTRUCTION.encode("utf-8")).hexdigest()
KERNEL_BASE_INSTRUCTION_IDENTITY = (
    f"{KERNEL_BASE_INSTRUCTION_REVISION}:sha256:{KERNEL_BASE_INSTRUCTION_SHA256}"
)


@dataclass(frozen=True, slots=True)
class ProviderConfiguration:
    auth: CredentialRef
    model_key: str
    reasoning: str
    agent_definition_revision: str
    row_fingerprint: str
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
        for name, value in (
            ("model_key", self.model_key),
            ("reasoning", self.reasoning),
            ("agent_definition_revision", self.agent_definition_revision),
        ):
            if type(value) is not str or not value.strip():
                raise ValueError(f"provider {name} must be a non-empty catalog value")
        if (
            type(self.row_fingerprint) is not str
            or re.fullmatch(r"[0-9a-f]{64}", self.row_fingerprint) is None
        ):
            raise ValueError("provider row_fingerprint must be a SHA-256 hex digest")
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
        if replace(self.native, archive_internal=False) != CODEX_NATIVE_OPTIONS:
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
    output_contract: StructuredOutput
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
        if not isinstance(self.output_contract, StructuredOutput):
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
class IsolatedDispatchLineage:
    """One model-authored isolated call and its exact dependency position."""

    run_id: RunId
    model_step_ordinal: int
    model_decision_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, RunId):
            raise TypeError("isolated dispatch run id must be RunId")
        _require_ordinal(self.model_step_ordinal)
        _require_decision_id(self.model_decision_id)

    @property
    def position(self) -> InvocationPosition:
        return InvocationPosition(f"model-decision:{self.model_decision_id}")


@dataclass(frozen=True, slots=True)
class InitialReadDispatchLineage:
    """The non-model initial Read and its exact dependency position."""

    run_id: RunId
    operation_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, RunId):
            raise TypeError("initial Read dispatch run id must be RunId")
        if type(self.operation_id) is not str or not self.operation_id.strip():
            raise ValueError("initial Read requires its stable operation identity")

    @property
    def position(self) -> InvocationPosition:
        return _initial_read_position(self.operation_id)


@dataclass(frozen=True, slots=True)
class NativeDispatchLineage:
    """One durably accepted callback, never a completed model decision."""

    attempt_id: str
    invocation_id: str
    ordinal: int
    permit: OwnerPermit
    input_ids: tuple[InputId, ...]
    through_checkpoint: Checkpoint | None
    definition_fingerprint: str

    def __post_init__(self) -> None:
        if not self.attempt_id or not self.invocation_id:
            raise ValueError("native dispatch identities are required")
        _require_ordinal(self.ordinal)
        if not self.input_ids or len(set(self.input_ids)) != len(self.input_ids):
            raise ValueError("native dispatch requires ordered unique input identities")

    @property
    def position(self) -> InvocationPosition:
        return InvocationPosition(f"native-invocation:{self.invocation_id}")


type ToolDispatchLineage = (
    IsolatedDispatchLineage | InitialReadDispatchLineage | NativeDispatchLineage
)


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


type ModelStep = CallToolStep | FinishStep


class WaitingFor(StrEnum):
    user = "user"
    system = "system"


@dataclass(frozen=True, slots=True)
class DispatchCompleted:
    result: ToolResult
    model_text: str
    host_ref: HostRef | None = None
    type: Literal["completed"] = field(default="completed", init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.result, dict):
            raise TypeError("completed dispatch result must be an llm-tools ToolResult")
        if type(self.model_text) is not str:
            raise TypeError("completed dispatch model text must be str")
        if self.host_ref is not None and not isinstance(self.host_ref, HostRef):
            raise TypeError("completed host reference must be HostRef")


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


class OneShotStopKind(StrEnum):
    cancelled = "cancelled"
    budget_exhausted = "budget_exhausted"
    quota_exhausted = "quota_exhausted"
    protocol_error = "protocol_error"
    provider_error = "provider_error"
    configuration_error = "configuration_error"
    model_decision_uncertain = "model_decision_uncertain"


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
    type: OneShotStopKind

    def __post_init__(self) -> None:
        if not isinstance(self.type, OneShotStopKind):
            raise TypeError("one-shot stop type must be OneShotStopKind")


type OneShotOutcome = OneShotCompleted | OneShotStopped


def _require_aware(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_ordinal(value: int) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError("model step ordinal must be a positive integer")


def _require_decision_id(value: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ValueError("model decision identity must be lowercase SHA-256")


def _initial_read_position(operation_id: str) -> InvocationPosition:
    digest = hashlib.sha256(
        canonical_json_bytes(
            {
                "namespace": "llm-agent-kernel-initial-read-v2",
                "operation_id": operation_id,
            }
        )
    ).hexdigest()
    return InvocationPosition(f"llm-agent-kernel-initial-read-v2:{digest}")


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

    output: dict[str, object] = {
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
        "kernel_base_instruction_identity": KERNEL_BASE_INSTRUCTION_IDENTITY,
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
            "model_key": provider.model_key,
            "agent_definition_revision": provider.agent_definition_revision,
            "row_fingerprint": provider.row_fingerprint,
            "native": {
                "archive_internal": provider.native.archive_internal,
                "builtin_tools": provider.native.builtin_tools,
                "web_search": provider.native.web_search,
                "containment_catalog_revision": CODEX_CONTAINMENT_CATALOG_REVISION,
                "containment_version": CODEX_CONTAINMENT_VERSION,
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
            "reasoning": provider.reasoning,
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
    "KERNEL_BASE_INSTRUCTION",
    "KERNEL_BASE_INSTRUCTION_IDENTITY",
    "KERNEL_BASE_INSTRUCTION_REVISION",
    "KERNEL_BASE_INSTRUCTION_SHA256",
    "NO_RESULT",
    "AgentDefinition",
    "AgentRole",
    "CallToolStep",
    "Checkpoint",
    "DefinitionId",
    "DispatchCompleted",
    "DispatchResult",
    "DispatchSuspended",
    "FinishStep",
    "HostInput",
    "HostRef",
    "InputId",
    "InputProjectionPolicy",
    "InputProjectionRequest",
    "InitialReadCall",
    "InitialReadDispatchLineage",
    "NativeDispatchLineage",
    "IsolatedDispatchLineage",
    "KernelLimits",
    "ModelStep",
    "NoResult",
    "OneShotCompleted",
    "OneShotOutcome",
    "OneShotStopped",
    "OwnerToken",
    "OwnerPermit",
    "ProviderConfiguration",
    "ProviderUsage",
    "RunId",
    "RunMetrics",
    "SessionMode",
    "StructuredOutput",
    "ThreadId",
    "OneShotStopKind",
    "ToolDispatchLineage",
    "WaitingFor",
]
