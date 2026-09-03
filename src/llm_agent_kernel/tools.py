"""Strict host-tool authority and validation boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from llm_tools import (
    FrozenCapabilityProfile,
    FrozenToolPlan,
    HostTable,
    PromptSection,
    ToolBinding,
    ToolEffect,
    ToolId,
    publish_host_table,
    validate_tool_input,
)
from provider_runtime.agent_runtime import thaw_json_value

from .definitions import CallToolStep


class PlanValidationError(ValueError):
    """The selected frozen plan is not valid for this definition."""


class ToolProposalError(ValueError):
    """A model-proposed tool call is not valid under the selected plan."""


@dataclass(frozen=True, slots=True)
class ValidatedToolCall:
    """One exact frozen binding and its purely decoded input."""

    step: CallToolStep
    binding: ToolBinding[Any, Any, Any]
    arguments: object

    @property
    def tool_id(self) -> ToolId:
        return self.binding.spec.id


def require_host_plan(
    plan: FrozenToolPlan,
    maximum_profile: FrozenCapabilityProfile,
) -> None:
    """Prove exact plan integrity, containment, exposure, and serial execution."""

    if not isinstance(plan, FrozenToolPlan):
        raise TypeError("run plan must be a FrozenToolPlan")
    if not isinstance(maximum_profile, FrozenCapabilityProfile):
        raise TypeError("definition maximum must be a FrozenCapabilityProfile")
    if not isinstance(plan.exposure, HostTable):
        raise PlanValidationError("a kernel run requires HostTable exposure")
    if not plan.is_tightening_of(maximum_profile):
        raise PlanValidationError(
            "the frozen plan is inconsistent or does not tighten the definition maximum"
        )
    if plan.profile.run_limits.max_in_flight != 1:
        raise PlanValidationError("the frozen tool plan must set max_in_flight to one")


def publish_host_plan(
    plan: FrozenToolPlan,
    maximum_profile: FrozenCapabilityProfile,
) -> PromptSection:
    """Prove exact authority before publishing its dependency-owned HostTable."""

    require_host_plan(plan, maximum_profile)
    return publish_host_table(plan)


def require_read_only_plan(plan: FrozenToolPlan) -> None:
    """Reject a one-shot plan containing any Write binding."""

    if not isinstance(plan, FrozenToolPlan):
        raise TypeError("one-shot plan must be a FrozenToolPlan")
    if not plan.is_tightening_of(plan.profile):
        raise PlanValidationError("the frozen plan is internally inconsistent")
    if any(
        plan.catalog_view.spec(grant.id).effect is ToolEffect.Write
        for grant in plan.profile.ordered_grants
    ):
        raise PlanValidationError("an isolated one-shot plan must not contain Write tools")


def validate_tool_call(step: CallToolStep, plan: FrozenToolPlan) -> ValidatedToolCall:
    """Resolve and purely validate one proposal without execution-side mutation."""

    if not isinstance(step, CallToolStep):
        raise TypeError("tool validation requires a CallToolStep")
    if not isinstance(plan, FrozenToolPlan):
        raise TypeError("tool validation requires a FrozenToolPlan")
    if not plan.is_tightening_of(plan.profile):
        raise ToolProposalError("tool validation requires a consistent frozen plan")
    try:
        binding = plan.catalog_view.binding(step.tool_id)
        arguments = cast(dict[str, object], thaw_json_value(step.arguments))
        validated = validate_tool_input(binding, arguments)
    except (KeyError, TypeError, ValueError) as exc:
        raise ToolProposalError("invalid tool id or arguments") from exc
    return ValidatedToolCall(step=step, binding=binding, arguments=validated)


__all__ = [
    "PlanValidationError",
    "ToolProposalError",
    "ValidatedToolCall",
    "publish_host_plan",
    "require_host_plan",
    "require_read_only_plan",
    "validate_tool_call",
]
