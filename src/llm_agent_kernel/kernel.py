"""Contained isolated inference and its durable paid-decision boundary."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Never

from llm_tools import (
    BudgetState,
    ExecutorConfigurationDefect,
    FrozenToolPlan,
    PositionConflictDefect,
    PromptSections,
    RecoveryRequired,
    RunLimits,
)
from provider_runtime.agent_runtime import (
    AgentAccepted,
    AgentFailure,
    AgentInputRecorded,
    AgentMessage,
    AgentNative,
    AgentNotSubmitted,
    AgentPermissionRequest,
    AgentQuotaExhausted,
    AgentRuntimeDefect,
    AgentRuntimeError,
    AgentTerminal,
    AgentText,
    AgentToolCall,
    AgentToolUse,
    AgentTurn,
    AgentUsage,
    ConcurrentTurn,
    CredentialRejected,
    CredentialUnavailable,
    ExecutableUnavailable,
    InvalidAgentRequest,
    JsonSchemaAgentOutput,
    McpConfigurationError,
    McpUnavailable,
    NativeTerminalEvidence,
    OutputSchemaMismatch,
    SdkUnavailable,
    TextContent,
    UnsupportedCapability,
    decode_agent_output,
)
from provider_runtime.types import Present, TokenUsage

from .cancellation import CancellationToken
from .context import (
    ContextLimitExceeded,
    ToolObservation,
    bootstrap_context,
    continuation_context,
    recorded_model_context,
)
from .coordination import (
    ContextSourceDefect,
    OwnerPort,
    ToolBudgetFactoryPort,
    ToolDispatchDefect,
    ToolDispatchPort,
)
from .decisions import (
    DurableIsolatedDecisions,
    IsolatedDecisionScope,
    IsolatedModelDecisions,
    ModelDecisionArmed,
    ModelDecisionCompleted,
    ModelDecisionDefect,
    ModelDecisionJournal,
    ModelDecisionNotSubmitted,
    ModelDecisionRequest,
    ModelDecisionUncertain,
    TransientModelDecisions,
    model_decision_id,
)
from .definitions import (
    NO_RESULT,
    AgentDefinition,
    DispatchCompleted,
    DispatchSuspended,
    FinishStep,
    HostInput,
    InitialReadCall,
    InitialReadDispatchLineage,
    InputProjectionRequest,
    IsolatedDispatchLineage,
    OneShotCompleted,
    OneShotOutcome,
    OneShotStopKind,
    OneShotStopped,
    OwnerPermit,
    ProviderUsage,
    RunId,
    RunMetrics,
    SessionMode,
    StructuredOutput,
)
from .events import (
    DiagnosticKind,
    DiagnosticTranscript,
    EventAttribute,
    EventKind,
    EventSink,
    KernelEvent,
    emit_diagnostic,
    emit_event,
)
from .protocol import (
    MODEL_STEP_OUTPUT_NAME,
    ProtocolValidationError,
    ValidatedToolCall,
    provider_wire_schema,
    validate_provider_step,
)
from .provider import (
    ProviderContainmentViolation,
    ProviderDefect,
    ProviderSessionLease,
    ProviderSessionPort,
    ProviderStreamDefect,
)
from .tools import (
    PlanValidationError,
    _validate_initial_read_call,
    require_host_plan,
    require_read_only_plan,
)


class KernelConfigurationDefect(RuntimeError):
    """A host or dependency invariant prevents safe progress."""


_PROVIDER_CONFIGURATION_ERRORS = (
    ConcurrentTurn,
    CredentialRejected,
    CredentialUnavailable,
    ExecutableUnavailable,
    InvalidAgentRequest,
    McpConfigurationError,
    McpUnavailable,
    SdkUnavailable,
    UnsupportedCapability,
)


class _RunState:
    def __init__(self, run_id: RunId, clock: Callable[[], float]) -> None:
        self.run_id = run_id
        self.clock = clock
        self.started = clock()
        self.provider_turns = 0
        self.input_tokens: int | None = None
        self.output_tokens: int | None = None
        self.input_usage_incomplete = False
        self.output_usage_incomplete = False
        self.visible_bytes = 0
        self.model_step_ordinal = 0
        self.model_decision_ordinal = 0
        self.model_decision_id: str | None = None
        self.pending_model_decision = False
        self.outcome_type: str | None = None

    def elapsed(self) -> float:
        return max(0.0, self.clock() - self.started)

    def usage(self) -> ProviderUsage:
        return ProviderUsage(self.input_tokens, self.output_tokens)

    def metrics(self, *, consumed: bool) -> RunMetrics:
        return RunMetrics(
            self.run_id,
            self.provider_turns,
            self.usage(),
            self.elapsed(),
            consumed,
        )

    def add_usage(self, current: ProviderUsage, previous: ProviderUsage) -> None:
        if current.input_tokens is None and self.provider_turns > 0:
            self.input_usage_incomplete = True
        if current.output_tokens is None and self.provider_turns > 0:
            self.output_usage_incomplete = True
        self.input_tokens = (
            None
            if self.input_usage_incomplete
            else _add_delta(self.input_tokens, current.input_tokens, previous.input_tokens)
        )
        self.output_tokens = (
            None
            if self.output_usage_incomplete
            else _add_delta(self.output_tokens, current.output_tokens, previous.output_tokens)
        )


async def run_one_shot(
    *,
    run_id: RunId,
    definition: AgentDefinition,
    inputs: tuple[HostInput, ...],
    as_of: datetime,
    plan: FrozenToolPlan,
    source_sections: PromptSections,
    owner: OwnerPort,
    permit: OwnerPermit,
    decisions: IsolatedModelDecisions,
    provider: ProviderSessionPort,
    dispatcher: ToolDispatchPort,
    budget_factory: ToolBudgetFactoryPort,
    initial_read: InitialReadCall | None = None,
    input_projection: InputProjectionRequest | None = None,
    cancellation: CancellationToken | None = None,
    event_sink: EventSink | None = None,
    diagnostics: DiagnosticTranscript | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> OneShotOutcome:
    """Run a fresh isolated structured session with no canonical thread state."""

    if definition.session_mode is not SessionMode.isolated:
        raise ValueError("one-shot requires an isolated definition")
    if not isinstance(definition.output_contract, StructuredOutput):
        raise ValueError("one-shot requires a structured output contract")
    definition.input_projection_policy.resolve(input_projection)
    require_host_plan(plan, definition.maximum_profile)
    require_read_only_plan(plan)
    if initial_read is not None and not isinstance(initial_read, InitialReadCall):
        raise TypeError("initial_read must be an InitialReadCall")
    validated_initial_read = (
        None if initial_read is None else _validate_initial_read_call(initial_read, plan)
    )
    budgets = (
        None if validated_initial_read is not None else _create_tool_budget(budget_factory, plan)
    )
    cancellation = cancellation or CancellationToken()
    state = _RunState(run_id, clock)

    def event(kind: EventKind, **attributes: None | bool | int | float | str) -> None:
        if event_sink is None:
            return
        try:
            value = KernelEvent(
                run_id,
                kind,
                datetime.now(UTC),
                tuple(EventAttribute(name, value) for name, value in attributes.items()),
            )
        except Exception:
            return
        emit_event(event_sink, value)

    def stopped(kind: OneShotStopKind) -> OneShotStopped:
        if kind is OneShotStopKind.cancelled:
            event(EventKind.cancellation, cancellation_type="cancelled")
        state.outcome_type = kind.value
        return OneShotStopped(state.metrics(consumed=False), kind)

    def completed(result: object) -> OneShotCompleted:
        state.outcome_type = "completed"
        return OneShotCompleted(state.metrics(consumed=False), result)

    if not isinstance(decisions, DurableIsolatedDecisions | TransientModelDecisions):
        raise TypeError("one-shot requires an explicit durable or transient decision policy")
    journal = decisions.journal if isinstance(decisions, DurableIsolatedDecisions) else None
    replay: ModelDecisionCompleted | None = None
    retry: ModelDecisionNotSubmitted | None = None
    if isinstance(decisions, DurableIsolatedDecisions):
        recorded = await decisions.journal.latest(decisions.scope)
        if isinstance(recorded, ModelDecisionArmed):
            return stopped(OneShotStopKind.model_decision_uncertain)
        if recorded is not None:
            if not isinstance(recorded, ModelDecisionCompleted | ModelDecisionNotSubmitted):
                return stopped(OneShotStopKind.configuration_error)
            request = recorded.request
            if (
                request.scope != decisions.scope
                or request.definition_fingerprint != definition.fingerprint
                or request.plan_revision != plan.plan_revision
                or request.input_ids != tuple(item.input_id for item in inputs)
                or request.as_of != as_of
                or request.through_checkpoint is not None
                or request.model_step_ordinal_before + request.protocol_repairs
                >= definition.limits.max_provider_turns
            ):
                return stopped(OneShotStopKind.configuration_error)
            if isinstance(recorded, ModelDecisionCompleted):
                replay = recorded
            else:
                retry = recorded
            state.model_step_ordinal = request.model_step_ordinal_before
            state.model_decision_ordinal = (
                request.ordinal - 1 if replay is not None else request.ordinal
            )

    projection = None
    if validated_initial_read is None:
        try:
            projection = bootstrap_context(
                definition,
                inputs,
                as_of,
                plan,
                source_sections,
                prior_visible_bytes=state.visible_bytes,
                input_projection=input_projection,
            )
        except ContextLimitExceeded:
            event(EventKind.outcome, outcome_type="configuration_error")
            return stopped(OneShotStopKind.configuration_error)
        state.visible_bytes = projection.cumulative_visible_bytes

    await owner.require_current(permit)
    lease: ProviderSessionLease | None = None
    previous_lease_usage = ProviderUsage()
    saved_request = (
        replay.request if replay is not None else retry.request if retry is not None else None
    )
    repairs = 0 if saved_request is None else saved_request.protocol_repairs
    pending_content: list[TextContent] = []
    canonical_content: list[str] = []
    canonical_pending_prefix = 0
    armed_request: ModelDecisionRequest | None = None
    recovery_bootstrap_pending = saved_request is not None

    async def account_lease_usage() -> None:
        nonlocal previous_lease_usage
        if lease is None:
            return
        current = await provider.accumulated_usage(lease)
        state.add_usage(current, previous_lease_usage)
        previous_lease_usage = current

    try:
        try:
            if cancellation.cancelled:
                return stopped(OneShotStopKind.cancelled)
            if validated_initial_read is not None and saved_request is None:
                budgets = _create_tool_budget(budget_factory, plan)
                if cancellation.cancelled:
                    return stopped(OneShotStopKind.cancelled)
                lineage = InitialReadDispatchLineage(
                    run_id,
                    decisions.scope.operation_id
                    if isinstance(decisions, DurableIsolatedDecisions)
                    else f"transient:{run_id}",
                )
                event(
                    EventKind.tool_dispatch,
                    tool_id=str(validated_initial_read.binding.spec.id),
                    dispatch_origin="initial_read",
                    invocation_position=str(lineage.position),
                    plan_revision=plan.plan_revision,
                    implementation_revision=(
                        validated_initial_read.binding.implementation_revision
                    ),
                )
                await owner.require_current(permit)
                dispatch = await dispatcher.dispatch(
                    binding=validated_initial_read.binding,
                    validated_input=validated_initial_read.arguments,
                    plan=plan,
                    budgets=budgets,
                    cancellation=cancellation,
                    lineage=lineage,
                )
                if isinstance(dispatch, DispatchSuspended):
                    return stopped(OneShotStopKind.configuration_error)
                if not isinstance(dispatch, DispatchCompleted):
                    raise KernelConfigurationDefect("dispatcher returned an unknown result variant")
                if cancellation.cancelled:
                    return stopped(OneShotStopKind.cancelled)
                projection = bootstrap_context(
                    definition,
                    inputs,
                    as_of,
                    plan,
                    source_sections,
                    observations=(
                        ToolObservation(
                            validated_initial_read.binding,
                            dispatch.result,
                            None,
                            dispatch.model_text,
                            initial_read_position=lineage.position,
                        ),
                    ),
                    prior_visible_bytes=state.visible_bytes,
                    input_projection=input_projection,
                )
                state.visible_bytes = projection.cumulative_visible_bytes
            if saved_request is not None:
                canonical_content[:] = saved_request.canonical_content
                pending_content[:] = [TextContent(text) for text in canonical_content]
                state.visible_bytes = 0
            else:
                assert projection is not None
                canonical_content.append(projection.rendered)
                pending_content.append(TextContent(projection.rendered))
            canonical_pending_prefix = len(pending_content)
            if budgets is None:
                budgets = _create_tool_budget(budget_factory, plan)

            while True:
                if cancellation.cancelled:
                    return stopped(OneShotStopKind.cancelled)
                if state.model_step_ordinal + repairs >= definition.limits.max_provider_turns:
                    return stopped(OneShotStopKind.budget_exhausted)
                remaining = definition.limits.max_cooperative_seconds - state.elapsed()
                if remaining <= 0:
                    return stopped(OneShotStopKind.budget_exhausted)
                replayed = replay is not None
                if replay is not None:
                    terminal = replay.terminal
                    state.model_decision_id = replay.request.decision_id
                    state.model_decision_ordinal = replay.request.ordinal
                    replay = None
                    pending_content.clear()
                else:
                    if lease is None:
                        if recovery_bootstrap_pending:
                            state.visible_bytes += sum(
                                len(part.text.encode())
                                for part in pending_content[:canonical_pending_prefix]
                            )
                            recovery_bootstrap_pending = False
                        lease = await provider.open_isolated(definition)
                    canonical_content.extend(
                        part.text for part in pending_content[canonical_pending_prefix:]
                    )
                    canonical_pending_prefix = 0
                    _require_decision_context(definition, state.visible_bytes, canonical_content)
                    scope = (
                        decisions.scope
                        if isinstance(decisions, DurableIsolatedDecisions)
                        else IsolatedDecisionScope(f"transient:{run_id}")
                    )
                    await owner.require_current(permit)
                    turn = provider.prepare_observed_turn(
                        lease,
                        tuple(pending_content),
                        cancellation,
                        attempt_id=model_decision_id(scope, state.model_decision_ordinal + 1),
                        input_id=str(inputs[0].input_id) if inputs else permit.operation_id,
                        timeout_seconds=remaining,
                    )
                    current_request = ModelDecisionRequest(
                        scope=scope,
                        ordinal=state.model_decision_ordinal + 1,
                        definition_fingerprint=definition.fingerprint,
                        plan_revision=plan.plan_revision,
                        input_ids=tuple(item.input_id for item in inputs),
                        through_checkpoint=None,
                        as_of=as_of,
                        model_step_ordinal_before=state.model_step_ordinal,
                        protocol_repairs=repairs,
                        canonical_content=tuple(canonical_content),
                        submitted_content=tuple(part.text for part in pending_content),
                        provider_attempt=turn.attempt,
                    )
                    state.model_decision_id = current_request.decision_id
                    armed_request = current_request if journal is not None else None
                    state.provider_turns += 1
                    state.model_decision_ordinal += 1
                    event(
                        EventKind.provider_turn, provider_turn=state.provider_turns, phase="started"
                    )
                    emit_diagnostic(
                        diagnostics,
                        run_id,
                        DiagnosticKind.provider_input,
                        "\n".join(part.text for part in pending_content),
                    )

                    result = await _record_observed_turn(
                        lease, turn, cancellation, current_request, journal
                    )
                    armed_request = None
                    if isinstance(result, AgentNotSubmitted):
                        state.provider_turns -= 1
                        return stopped(
                            OneShotStopKind.cancelled
                            if cancellation.cancelled
                            else OneShotStopKind.provider_error
                        )
                    terminal = result
                    pending_content.clear()
                    await account_lease_usage()
                canonical_content.append(recorded_model_context(terminal))
                if replayed:
                    pending_content[:] = [TextContent(text) for text in canonical_content]
                    canonical_pending_prefix = len(pending_content)
                event(
                    EventKind.provider_turn,
                    provider_turn=state.provider_turns,
                    phase="finished",
                    status=terminal.status,
                )
                emit_diagnostic(
                    diagnostics,
                    run_id,
                    DiagnosticKind.provider_terminal,
                    terminal.final_text,
                )
                if terminal.status == "cancelled":
                    return stopped(OneShotStopKind.cancelled)
                if terminal.status == "failed":
                    kind = _failed_terminal_stop(terminal)
                    return stopped(kind)
                if terminal.status != "succeeded":
                    raise KernelConfigurationDefect("provider returned an unknown terminal status")
                if _kernel_budget_exhausted(definition, state):
                    return stopped(OneShotStopKind.budget_exhausted)

                state.model_step_ordinal += 1
                try:
                    step = validate_provider_step(
                        decode_agent_output(
                            JsonSchemaAgentOutput(
                                name=MODEL_STEP_OUTPUT_NAME,
                                schema=provider_wire_schema(definition.output_contract),
                            ),
                            terminal,
                        ),
                        definition.output_contract,
                        plan,
                    )
                except (OutputSchemaMismatch, ProtocolValidationError, TypeError, ValueError):
                    state.model_step_ordinal -= 1
                    event(EventKind.validation, valid=False)
                    if repairs >= definition.limits.max_protocol_repairs:
                        return stopped(OneShotStopKind.protocol_error)
                    repairs += 1
                    projection = continuation_context(
                        definition,
                        plan,
                        PromptSections(()),
                        correction="Return exactly one value matching the required step schema.",
                        prior_visible_bytes=state.visible_bytes,
                    )
                    state.visible_bytes = projection.cumulative_visible_bytes
                    pending_content.append(TextContent(projection.rendered))
                    continue
                event(EventKind.validation, valid=True)

                if isinstance(step, ValidatedToolCall):
                    if cancellation.cancelled:
                        return stopped(OneShotStopKind.cancelled)
                    if _kernel_budget_exhausted(definition, state):
                        return stopped(OneShotStopKind.budget_exhausted)
                    event(
                        EventKind.tool_dispatch,
                        tool_id=str(step.tool_id),
                        model_step_ordinal=state.model_step_ordinal,
                        plan_revision=plan.plan_revision,
                        implementation_revision=step.binding.implementation_revision,
                    )
                    assert state.model_decision_id is not None
                    await owner.require_current(permit)
                    dispatch = await dispatcher.dispatch(
                        binding=step.binding,
                        validated_input=step.arguments,
                        plan=plan,
                        budgets=budgets,
                        cancellation=cancellation,
                        lineage=IsolatedDispatchLineage(
                            run_id,
                            state.model_step_ordinal,
                            state.model_decision_id,
                        ),
                    )
                    if isinstance(dispatch, DispatchSuspended):
                        return stopped(OneShotStopKind.configuration_error)
                    if not isinstance(dispatch, DispatchCompleted):
                        raise KernelConfigurationDefect(
                            "dispatcher returned an unknown result variant"
                        )
                    if cancellation.cancelled:
                        return stopped(OneShotStopKind.cancelled)
                    projection = continuation_context(
                        definition,
                        plan,
                        PromptSections(()),
                        observations=(
                            ToolObservation(
                                step.binding,
                                dispatch.result,
                                state.model_step_ordinal,
                                dispatch.model_text,
                            ),
                        ),
                        prior_visible_bytes=state.visible_bytes,
                    )
                    state.visible_bytes = projection.cumulative_visible_bytes
                    pending_content.append(TextContent(projection.rendered))
                    continue
                if isinstance(step, FinishStep) and step.result is not NO_RESULT:
                    if cancellation.cancelled:
                        return stopped(OneShotStopKind.cancelled)
                    return completed(step.result)
                raise KernelConfigurationDefect("isolated structured run ended without a result")
        except _PROVIDER_CONFIGURATION_ERRORS:
            await account_lease_usage()
            if armed_request is not None:
                return stopped(OneShotStopKind.model_decision_uncertain)
            return stopped(OneShotStopKind.configuration_error)
        except AgentRuntimeError:
            await account_lease_usage()
            if armed_request is not None:
                return stopped(OneShotStopKind.model_decision_uncertain)
            if cancellation.cancelled:
                return stopped(OneShotStopKind.cancelled)
            return stopped(OneShotStopKind.provider_error)
        except ModelDecisionUncertain:
            await account_lease_usage()
            return stopped(OneShotStopKind.model_decision_uncertain)
        except (
            AgentRuntimeDefect,
            ContextLimitExceeded,
            ContextSourceDefect,
            ExecutorConfigurationDefect,
            KernelConfigurationDefect,
            ModelDecisionDefect,
            PlanValidationError,
            PositionConflictDefect,
            ProviderDefect,
            RecoveryRequired,
            ToolDispatchDefect,
            TypeError,
            ValueError,
        ):
            await account_lease_usage()
            return stopped(OneShotStopKind.configuration_error)
    finally:
        try:
            if lease is not None:
                await account_lease_usage()
        finally:
            try:
                if lease is not None:
                    try:
                        await provider.close(lease)
                    except Exception as error:
                        lease.record_diagnostics(
                            (f"{type(error).__name__}: provider session cleanup failed",)
                        )
            finally:
                event(
                    EventKind.usage,
                    provider_turns=state.provider_turns,
                    input_tokens=state.input_tokens,
                    output_tokens=state.output_tokens,
                )
                event(
                    EventKind.outcome,
                    outcome_type=state.outcome_type or "interrupted",
                )


async def _record_observed_turn(
    lease: ProviderSessionLease,
    turn: AgentTurn,
    cancellation: CancellationToken,
    request: ModelDecisionRequest,
    journal: ModelDecisionJournal | None,
) -> AgentTerminal | AgentNotSubmitted:
    """Arm the prepared request and retain submission truth before product work."""
    if journal is not None:
        try:
            await journal.arm(request)
        except BaseException as error:
            turn.revoke()
            try:
                await turn.close()
            except BaseException as cleanup_error:
                error.add_note(f"{type(cleanup_error).__name__}: prepared turn cleanup also failed")
            raise

    async def accept(terminal: AgentTerminal) -> None:
        if journal is not None:
            committed = await journal.complete(request, terminal)
            if committed != ModelDecisionCompleted(request, terminal):
                raise ModelDecisionDefect("journal substituted a completed model decision")

    result = await _consume_observed_turn(lease, turn, cancellation, accept)
    if isinstance(result, AgentNotSubmitted) and journal is not None:
        await journal.not_submitted(request, result)
    return result


async def _consume_observed_turn(
    lease: ProviderSessionLease,
    turn: AgentTurn,
    cancellation: CancellationToken,
    accept: Callable[[AgentTerminal], Awaitable[None]],
) -> AgentTerminal | AgentNotSubmitted:
    """Inspect all contained events and commit native truth before cleanup."""
    stream = turn.events()
    terminal: AgentTerminal | None = None
    observed_usage: TokenUsage | None = None
    primary_error: BaseException | None = None
    cancel_wait = asyncio.create_task(cancellation.wait())
    next_event = None
    try:
        if cancellation.cancelled:
            turn.revoke()
        submission = await turn.submit()
        if isinstance(submission, AgentNotSubmitted):
            return submission
        if not isinstance(submission, AgentAccepted):
            raise ModelDecisionUncertain("prepared provider submission remains unresolved")
        interrupted = False
        while True:
            next_event = asyncio.ensure_future(anext(stream))
            if not interrupted:
                done, _ = await asyncio.wait(
                    (next_event, cancel_wait), return_when=asyncio.FIRST_COMPLETED
                )
                if cancel_wait in done and not next_event.done():
                    interrupted = True
                    turn.revoke()
                    await turn.interrupt()
            try:
                if interrupted:
                    async with asyncio.timeout(5.0):
                        event = await next_event
                else:
                    event = await next_event
            except StopAsyncIteration as error:
                raise ProviderStreamDefect(
                    "prepared provider stream ended without native truth"
                ) from error
            if isinstance(event, AgentText | AgentNative | AgentMessage | AgentInputRecorded):
                continue
            if isinstance(event, AgentUsage):
                observed_usage = event.usage
                continue
            if isinstance(event, AgentToolUse | AgentPermissionRequest | AgentToolCall):
                raise ProviderContainmentViolation(
                    "contained provider emitted tool or permission authority"
                )
            if not isinstance(event, AgentTerminal):
                raise ProviderStreamDefect("prepared provider emitted an unknown event")
            terminal = event
            if terminal.session_ref != lease.session.ref:
                raise ProviderStreamDefect("provider terminal changed the live session reference")
            if not isinstance(terminal.evidence, NativeTerminalEvidence):
                raise ModelDecisionUncertain("local provider stop is not native terminal evidence")
            if (
                terminal.evidence.attempt != turn.attempt
                or terminal.evidence.native_ref != submission.turn
            ):
                raise ProviderStreamDefect(
                    "provider terminal changed its submitted attempt or native turn"
                )
            await accept(terminal)
            return terminal
    except BaseException as error:
        primary_error = error
        raise
    finally:
        cancel_wait.cancel()
        if next_event is not None and not next_event.done():
            next_event.cancel()
        await asyncio.gather(
            cancel_wait, *((next_event,) if next_event is not None else ()), return_exceptions=True
        )
        if terminal is not None and isinstance(terminal.usage, Present):
            observed_usage = terminal.usage.value
        if not isinstance(turn.submission, AgentNotSubmitted):
            lease.record_usage(observed_usage)
        try:
            close = await turn.close()
            lease.record_diagnostics(close.diagnostics)
            if primary_error is not None:
                for diagnostic in close.diagnostics:
                    primary_error.add_note(diagnostic)
        except BaseException as cleanup_error:
            if primary_error is not None:
                primary_error.add_note(
                    f"{type(cleanup_error).__name__}: prepared turn cleanup failed"
                )
            elif terminal is None:
                raise
            else:
                lease.record_diagnostics(
                    (f"{type(cleanup_error).__name__}: prepared turn cleanup failed",)
                )


def _require_decision_context(
    definition: AgentDefinition, visible_bytes: int, canonical: list[str]
) -> None:
    limit = definition.limits.max_new_context_bytes
    if visible_bytes > limit or sum(len(text.encode()) for text in canonical) > limit:
        raise ContextLimitExceeded("durable model context exceeds its bounded request limit")


def _add_delta(total: int | None, current: int | None, previous: int | None) -> int | None:
    if current is None:
        return total
    delta = current - (previous or 0)
    if delta < 0:
        raise KernelConfigurationDefect("provider usage decreased within one live session")
    return (total or 0) + delta


def _kernel_budget_exhausted(definition: AgentDefinition, state: _RunState) -> bool:
    limits = definition.limits
    return (
        state.elapsed() >= limits.max_cooperative_seconds
        or (
            state.input_tokens is not None and state.input_tokens > limits.max_provider_input_tokens
        )
        or (
            state.output_tokens is not None
            and state.output_tokens > limits.max_provider_output_tokens
        )
    )


def _create_tool_budget(
    factory: ToolBudgetFactoryPort,
    plan: FrozenToolPlan,
) -> BudgetState:
    try:
        budgets = factory.create(plan)
        limits = budgets.limits
    except (AttributeError, TypeError, ValueError) as error:
        raise KernelConfigurationDefect("tool budget factory returned invalid state") from error
    if not isinstance(limits, RunLimits) or limits != plan.profile.run_limits:
        raise KernelConfigurationDefect("tool budget limits do not match the frozen run plan")
    return budgets


def _failed_terminal_stop(terminal: AgentTerminal) -> OneShotStopKind:
    if terminal.status != "failed":
        raise KernelConfigurationDefect("terminal is not failed")
    if isinstance(terminal.failure, AgentQuotaExhausted):
        return OneShotStopKind.quota_exhausted
    if not isinstance(terminal.failure, AgentFailure):
        raise KernelConfigurationDefect("failed terminal lacks a known failure")
    if terminal.failure.cause == "turn_timeout":
        return OneShotStopKind.budget_exhausted
    return OneShotStopKind.provider_error


def _unreachable(value: object) -> Never:
    raise KernelConfigurationDefect(f"unreachable model step: {type(value).__name__}")


__all__ = ["KernelConfigurationDefect", "run_one_shot"]
