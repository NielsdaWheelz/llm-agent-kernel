"""Provider-neutral prompt context with exact authority and size bounds."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from llm_tools import (
    FrozenToolPlan,
    InvocationPosition,
    PromptAttribute,
    PromptAttributeName,
    PromptJson,
    PromptSection,
    PromptSectionKind,
    PromptSections,
    PromptText,
    ToolBinding,
    ToolEffect,
    ToolResult,
    render_prompt,
)

from .definitions import AgentDefinition, HostInput, InputProjectionRequest
from .tools import publish_host_plan, require_host_plan


class ContextLimitExceeded(ValueError):
    """Required context cannot fit without silently losing evidence."""


@dataclass(frozen=True, slots=True)
class ToolObservation:
    binding: ToolBinding[Any, Any, Any]
    result: ToolResult
    model_step_ordinal: int | None
    recomputable: bool = False
    source_references: tuple[str, ...] = ()
    initial_read_position: InvocationPosition | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.binding, ToolBinding):
            raise TypeError("an observation requires its exact tool binding")
        if not isinstance(self.result, dict):
            raise TypeError("an observation result must be an llm-tools ToolResult")
        if self.initial_read_position is None:
            if type(self.model_step_ordinal) is not int or self.model_step_ordinal <= 0:
                raise ValueError("observation model-step ordinal must be positive")
        elif not isinstance(self.initial_read_position, InvocationPosition):
            raise TypeError("initial Read observation position must be InvocationPosition")
        elif self.model_step_ordinal is not None:
            raise ValueError("an initial Read observation is not a model step")
        if type(self.recomputable) is not bool:
            raise TypeError("observation recomputable must be bool")
        if self.recomputable and self.binding.spec.effect is not ToolEffect.Read:
            raise ValueError("only a Read observation may be marked recomputable")
        if type(self.source_references) is not tuple or any(
            type(reference) is not str or not reference for reference in self.source_references
        ):
            raise ValueError("observation source references must be non-empty strings")
        if self.recomputable and not self.source_references:
            raise ValueError("a recomputable Read requires a stable source reference")
        if self.initial_read_position is not None and self.recomputable:
            raise ValueError("an initial Read observation is required initial context")


@dataclass(frozen=True, slots=True)
class ContextProjection:
    """Kernel-rendered model-visible material newly submitted by this run."""

    sections: PromptSections
    rendered: str
    visible_bytes: int
    cumulative_visible_bytes: int


def bootstrap_context(
    definition: AgentDefinition,
    inputs: tuple[HostInput, ...],
    as_of: datetime,
    plan: FrozenToolPlan,
    source_sections: PromptSections,
    *,
    observations: tuple[ToolObservation, ...] = (),
    correction: str | None = None,
    prior_visible_bytes: int = 0,
    input_projection: InputProjectionRequest | None = None,
) -> ContextProjection:
    """Build one cold bootstrap solely from canonical host material."""

    if not isinstance(source_sections, PromptSections):
        raise TypeError("bootstrap source must be PromptSections")
    render_source_timestamps, render_batch_as_of = _resolve_input_projection(
        definition, input_projection
    )
    return _project(
        definition,
        plan,
        (
            *definition.role.instructions.sections,
            *definition.stable_context.sections,
            *source_sections.sections,
            publish_host_plan(plan, definition.maximum_profile),
            _input_batch(
                inputs,
                as_of,
                render_source_timestamps=render_source_timestamps,
                render_batch_as_of=render_batch_as_of,
            ),
        ),
        observations,
        correction,
        prior_visible_bytes,
    )


def run_context(
    definition: AgentDefinition,
    inputs: tuple[HostInput, ...],
    as_of: datetime,
    plan: FrozenToolPlan,
    source_sections: PromptSections,
    *,
    observations: tuple[ToolObservation, ...] = (),
    correction: str | None = None,
    prior_visible_bytes: int = 0,
    input_projection: InputProjectionRequest | None = None,
) -> ContextProjection:
    """Build the first delta for a healthy continuing session and new run."""

    if not isinstance(source_sections, PromptSections):
        raise TypeError("run source must be PromptSections")
    render_source_timestamps, render_batch_as_of = _resolve_input_projection(
        definition, input_projection
    )
    return _project(
        definition,
        plan,
        (
            *source_sections.sections,
            publish_host_plan(plan, definition.maximum_profile),
            _input_batch(
                inputs,
                as_of,
                render_source_timestamps=render_source_timestamps,
                render_batch_as_of=render_batch_as_of,
            ),
        ),
        observations,
        correction,
        prior_visible_bytes,
    )


def continuation_context(
    definition: AgentDefinition,
    plan: FrozenToolPlan,
    source_sections: PromptSections,
    *,
    inputs: tuple[HostInput, ...] = (),
    as_of: datetime | None = None,
    observations: tuple[ToolObservation, ...] = (),
    correction: str | None = None,
    prior_visible_bytes: int = 0,
    input_projection: InputProjectionRequest | None = None,
) -> ContextProjection:
    """Build only material not already sent during the current run."""

    if not isinstance(source_sections, PromptSections):
        raise TypeError("continuation source must be PromptSections")
    render_source_timestamps, render_batch_as_of = _resolve_input_projection(
        definition, input_projection
    )
    if bool(inputs) != (as_of is not None):
        raise ValueError("new host input and its as_of must be supplied together")
    dynamic = (
        (
            *source_sections.sections,
            _input_batch(
                inputs,
                as_of,
                render_source_timestamps=render_source_timestamps,
                render_batch_as_of=render_batch_as_of,
            ),
        )
        if as_of is not None
        else source_sections.sections
    )
    return _project(
        definition,
        plan,
        dynamic,
        observations,
        correction,
        prior_visible_bytes,
    )


def _project(
    definition: AgentDefinition,
    plan: FrozenToolPlan,
    base_sections: tuple[PromptSection, ...],
    observations: tuple[ToolObservation, ...],
    correction: str | None,
    prior_visible_bytes: int,
) -> ContextProjection:
    if not isinstance(definition, AgentDefinition):
        raise TypeError("context requires an AgentDefinition")
    if not isinstance(base_sections, tuple) or any(
        not isinstance(section, PromptSection) for section in base_sections
    ):
        raise TypeError("context source must provide typed PromptSections")
    if type(observations) is not tuple or any(
        not isinstance(observation, ToolObservation) for observation in observations
    ):
        raise TypeError("context observations must be a tuple of ToolObservation")
    if correction is not None and (type(correction) is not str or not correction.strip()):
        raise ValueError("a protocol correction must not be empty")
    if type(prior_visible_bytes) is not int or prior_visible_bytes < 0:
        raise ValueError("prior visible context bytes must be a non-negative integer")

    require_host_plan(plan, definition.maximum_profile)
    suffix = () if correction is None else (_correction(correction),)
    omitted: set[int] = set()
    while True:
        observation_sections = tuple(
            _omission_marker((observation,)) if index in omitted else _observation(observation)
            for index, observation in enumerate(observations)
        )
        sections = PromptSections((*base_sections, *observation_sections, *suffix))
        require_host_plan(plan, definition.maximum_profile)
        rendered = render_prompt(sections)
        visible_bytes = len(rendered.encode("utf-8"))
        cumulative = prior_visible_bytes + visible_bytes
        if cumulative <= definition.limits.max_new_context_bytes:
            return ContextProjection(sections, rendered, visible_bytes, cumulative)

        removable = next(
            (
                index
                for index, observation in enumerate(observations)
                if index not in omitted and observation.recomputable
            ),
            None,
        )
        if removable is None:
            raise ContextLimitExceeded(
                "context exceeds its cumulative limit without an omittable Read observation"
            )
        omitted.add(removable)


def _resolve_input_projection(
    definition: AgentDefinition,
    request: InputProjectionRequest | None,
) -> tuple[bool, bool]:
    if not isinstance(definition, AgentDefinition):
        raise TypeError("context requires an AgentDefinition")
    return definition.input_projection_policy.resolve(request)


def _input_batch(
    inputs: tuple[HostInput, ...],
    as_of: datetime,
    *,
    render_source_timestamps: bool,
    render_batch_as_of: bool,
) -> PromptSection:
    if type(inputs) is not tuple or not inputs:
        raise ValueError("an admitted host-input batch must not be empty")
    if any(not isinstance(item, HostInput) for item in inputs):
        raise TypeError("input batches must contain HostInput values")
    if not isinstance(as_of, datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("input batch as_of must be timezone-aware")
    batch_attributes = (
        (PromptAttribute(PromptAttributeName("as_of"), as_of.isoformat()),)
        if render_batch_as_of
        else ()
    )
    return PromptSection(
        kind=PromptSectionKind("host_input_batch"),
        attributes=batch_attributes,
        body=PromptSections(
            PromptSection(
                kind=PromptSectionKind("host_input"),
                attributes=(
                    PromptAttribute(PromptAttributeName("input_id"), str(item.input_id)),
                    *(
                        (
                            PromptAttribute(
                                PromptAttributeName("source_timestamp"),
                                item.source_timestamp.isoformat(),
                            ),
                        )
                        if render_source_timestamps
                        else ()
                    ),
                ),
                body=item.sections,
            )
            for item in inputs
        ),
    )


def _observation(observation: ToolObservation) -> PromptSection:
    if observation.initial_read_position is not None:
        lineage_attributes = (
            PromptAttribute(
                PromptAttributeName("origin"),
                "initial_read",
            ),
        )
    else:
        assert observation.model_step_ordinal is not None
        lineage_attributes = (
            PromptAttribute(
                PromptAttributeName("model_step_ordinal"),
                observation.model_step_ordinal,
            ),
        )
    return PromptSection(
        kind=PromptSectionKind("tool_observation"),
        attributes=(
            *lineage_attributes,
            PromptAttribute(
                PromptAttributeName("tool_id"),
                str(observation.binding.spec.id),
            ),
        ),
        body=PromptJson(
            {
                "result": observation.result,
                "source_references": list(observation.source_references),
            }
        ),
    )


def _omission_marker(observations: tuple[ToolObservation, ...]) -> PromptSection:
    return PromptSection(
        kind=PromptSectionKind("omitted_read_observations"),
        attributes=(),
        body=PromptJson(
            {
                "observations": [
                    {
                        "model_step_ordinal": observation.model_step_ordinal,
                        "source_references": list(observation.source_references),
                        "tool_id": str(observation.binding.spec.id),
                    }
                    for observation in observations
                ],
                "reason": "cumulative_context_limit",
            }
        ),
    )


def _correction(text: str) -> PromptSection:
    return PromptSection(
        kind=PromptSectionKind("protocol_correction"),
        attributes=(),
        body=PromptText(text),
    )


__all__ = [
    "ContextLimitExceeded",
    "ContextProjection",
    "ToolObservation",
    "bootstrap_context",
    "continuation_context",
    "run_context",
]
