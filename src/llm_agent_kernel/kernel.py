"""Bounded thread and isolated agent loops."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
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
    AgentFailure,
    AgentQuotaExhausted,
    AgentRuntimeDefect,
    AgentRuntimeError,
    AgentTerminal,
    ConcurrentTurn,
    CredentialRejected,
    CredentialUnavailable,
    ExecutableUnavailable,
    FrozenJsonDict,
    InvalidAgentRequest,
    McpConfigurationError,
    McpUnavailable,
    SdkUnavailable,
    SessionMismatch,
    SessionUnavailable,
    TextContent,
    TurnNotStarted,
    UnsupportedCapability,
)

from .cancellation import CancellationToken
from .context import (
    ContextLimitExceeded,
    ToolObservation,
    bootstrap_context,
    continuation_context,
    run_context,
)
from .coordination import (
    AdmissionDeferred,
    AdmissionGranted,
    AdmissionPort,
    AdmissionRejected,
    AdmissionRequest,
    AdmissionStateDefect,
    AdmissionToken,
    AdmissionUsage,
    AlreadyParked,
    AlreadyReleased,
    AppendInputs,
    CheckpointStateDefect,
    ClaimAcquired,
    ClaimBusy,
    ClaimDeferred,
    ClaimNoWork,
    ContextSourceDefect,
    ContextSourcePort,
    InputCheckpointPort,
    NoNewInput,
    Parked,
    Preempt,
    Released,
    SessionRefStateDefect,
    SettleIdle,
    SettleMoreInput,
    ToolBudgetFactoryPort,
    ToolDispatchDefect,
    ToolDispatchPort,
)
from .definitions import (
    NO_RESULT,
    AgentDefinition,
    Checkpoint,
    ConversationConclusion,
    DispatchCompleted,
    DispatchLineage,
    DispatchSuspended,
    FinishStep,
    HostConclusion,
    HostInput,
    InitialReadCall,
    InitialReadDispatchLineage,
    InputClaim,
    InputProjectionRequest,
    IsolatedDispatchLineage,
    OneShotCompleted,
    OneShotOutcome,
    OneShotStopped,
    OwnerToken,
    ProviderUsage,
    RunId,
    RunMetrics,
    SayStep,
    SessionMode,
    StoppedConclusion,
    StopReason,
    StructuredConclusion,
    StructuredOutput,
    SuspensionConclusion,
    ThreadBusy,
    ThreadCompleted,
    ThreadDeferred,
    ThreadId,
    ThreadNoWork,
    ThreadOutcome,
    ThreadStopKind,
    ThreadStopped,
    ThreadSuspended,
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
from .protocol import ProtocolValidationError, ValidatedToolCall, validate_provider_step
from .provider import ProviderDefect, ProviderSessionLease, ProviderSessionPort
from .sessions import ContinuingSessionState, SessionCoordinator, StaleSessionReference
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


async def _settle_claim(
    checkpoints: InputCheckpointPort,
    claim: InputClaim,
    through_checkpoint: Checkpoint,
    conclusion: HostConclusion,
) -> SettleIdle | SettleMoreInput:
    result = await checkpoints.settle(claim, through_checkpoint, conclusion)
    if not isinstance(result, SettleIdle | SettleMoreInput):
        raise KernelConfigurationDefect("checkpoint port returned an unknown settlement result")
    return result


async def _release_claim(
    checkpoints: InputCheckpointPort,
    claim: InputClaim,
    reason: str,
) -> None:
    result = await checkpoints.release(claim, reason)
    if not isinstance(result, Released | AlreadyReleased):
        raise KernelConfigurationDefect("checkpoint port returned an unknown release result")


async def _park_claim(
    checkpoints: InputCheckpointPort,
    claim: InputClaim,
    reason: str,
) -> None:
    result = await checkpoints.park(claim, reason)
    if not isinstance(result, Parked | AlreadyParked):
        raise KernelConfigurationDefect("checkpoint port returned an unknown park result")


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


async def _claim_and_admit(
    *,
    run_id: RunId,
    thread_id: ThreadId,
    owner_token: OwnerToken,
    definition: AgentDefinition,
    checkpoints: InputCheckpointPort,
    admission: AdmissionPort,
    budget_factory: ToolBudgetFactoryPort,
    cancellation: CancellationToken,
    state: _RunState,
    event: Callable[..., None],
) -> tuple[InputClaim, AdmissionToken, BudgetState] | ThreadOutcome:
    claim_result = await checkpoints.claim(thread_id, owner_token)
    if not isinstance(claim_result, ClaimNoWork | ClaimBusy | ClaimDeferred | ClaimAcquired):
        raise KernelConfigurationDefect("checkpoint port returned an unknown claim result")
    event(EventKind.claim, claim_type=claim_result.type)
    if isinstance(claim_result, ClaimNoWork):
        event(EventKind.outcome, outcome_type="no_work")
        return ThreadNoWork(state.metrics(consumed=False))
    if isinstance(claim_result, ClaimBusy):
        event(EventKind.outcome, outcome_type="busy")
        return ThreadBusy(state.metrics(consumed=False))
    if isinstance(claim_result, ClaimDeferred):
        event(EventKind.outcome, outcome_type="deferred")
        return ThreadDeferred(state.metrics(consumed=False), claim_result.until)
    claim = claim_result.claim
    current_checkpoint = claim.through_checkpoint
    admitted_inputs = list(claim.inputs)

    try:
        require_host_plan(claim.plan, definition.maximum_profile)
    except (PlanValidationError, TypeError, ValueError):
        await _park_claim(checkpoints, claim, "invalid frozen tool plan")
        event(EventKind.outcome, outcome_type="configuration_error")
        return ThreadStopped(state.metrics(consumed=False), ThreadStopKind.configuration_error)

    async def early_stop(kind: ThreadStopKind, reason: StopReason) -> ThreadStopped:
        try:
            result = await checkpoints.poll(claim, current_checkpoint)
            if isinstance(result, AppendInputs):
                _validate_append(result, current_checkpoint, admitted_inputs)
            elif isinstance(result, Preempt):
                cancellation.cancel()
                await _release_claim(checkpoints, claim, "preempted by host policy")
                event(EventKind.cancellation, cancellation_type="preempted")
                event(EventKind.outcome, outcome_type="preempted")
                return ThreadStopped(state.metrics(consumed=False), ThreadStopKind.preempted)
            elif not isinstance(result, NoNewInput):
                raise KernelConfigurationDefect("invalid settlement poll result")
            await _settle_claim(
                checkpoints,
                claim,
                current_checkpoint,
                StoppedConclusion(reason),
            )
        except (CheckpointStateDefect, KernelConfigurationDefect, TypeError, ValueError):
            await _park_claim(checkpoints, claim, "checkpoint defect before admission")
            event(EventKind.outcome, outcome_type="configuration_error")
            return ThreadStopped(
                state.metrics(consumed=False),
                ThreadStopKind.configuration_error,
            )
        except BaseException:
            await _release_claim(checkpoints, claim, "early stop interrupted")
            raise
        event(EventKind.settlement, settlement_type="stopped", stop_kind=kind.value)
        event(EventKind.outcome, outcome_type=kind.value)
        return ThreadStopped(state.metrics(consumed=True), kind)

    if claim.attempt_number > definition.limits.max_no_progress_attempts:
        return await early_stop(ThreadStopKind.provider_error, StopReason.provider_error)

    try:
        budgets = _create_tool_budget(budget_factory, claim.plan)
    except (KernelConfigurationDefect, TypeError, ValueError):
        await _park_claim(checkpoints, claim, "invalid frozen tool budget")
        event(EventKind.outcome, outcome_type="configuration_error")
        return ThreadStopped(state.metrics(consumed=False), ThreadStopKind.configuration_error)
    except BaseException:
        await _release_claim(checkpoints, claim, "tool budget construction interrupted")
        raise

    request = AdmissionRequest(
        run_id=run_id,
        thread_id=thread_id,
        attempt_number=claim.attempt_number,
        maximum_turns=definition.limits.max_provider_turns,
        maximum_input_tokens=definition.limits.max_provider_input_tokens,
        maximum_output_tokens=definition.limits.max_provider_output_tokens,
    )
    try:
        result = await admission.reserve(request)
    except AdmissionStateDefect:
        await _park_claim(checkpoints, claim, "admission state defect")
        event(EventKind.outcome, outcome_type="configuration_error")
        return ThreadStopped(state.metrics(consumed=False), ThreadStopKind.configuration_error)
    except BaseException:
        await _release_claim(checkpoints, claim, "admission reservation interrupted")
        raise
    if not isinstance(result, AdmissionGranted | AdmissionDeferred | AdmissionRejected):
        await _park_claim(checkpoints, claim, "invalid admission result")
        event(EventKind.outcome, outcome_type="configuration_error")
        return ThreadStopped(state.metrics(consumed=False), ThreadStopKind.configuration_error)
    event(EventKind.admission, admission_type=result.type)
    if isinstance(result, AdmissionDeferred):
        await _release_claim(checkpoints, claim, "admission deferred")
        event(EventKind.outcome, outcome_type="deferred")
        return ThreadDeferred(state.metrics(consumed=False), result.until)
    if isinstance(result, AdmissionRejected):
        return await early_stop(ThreadStopKind.budget_exhausted, StopReason.budget_exhausted)

    token = result.token
    try:
        _require_admission_token(request, token)
    except KernelConfigurationDefect:
        try:
            await _park_claim(checkpoints, claim, "invalid admission token")
        finally:
            await admission.settle(token, AdmissionUsage(0, ProviderUsage(), state.elapsed()))
        event(EventKind.outcome, outcome_type="configuration_error")
        return ThreadStopped(state.metrics(consumed=False), ThreadStopKind.configuration_error)
    return claim, token, budgets


async def run_thread(
    *,
    run_id: RunId,
    thread_id: ThreadId,
    owner_token: OwnerToken,
    definition: AgentDefinition,
    checkpoints: InputCheckpointPort,
    admission: AdmissionPort,
    sessions: SessionCoordinator,
    context_source: ContextSourcePort,
    dispatcher: ToolDispatchPort,
    budget_factory: ToolBudgetFactoryPort,
    input_projection: InputProjectionRequest | None = None,
    cancellation: CancellationToken | None = None,
    consume_on_cancel: bool = True,
    event_sink: EventSink | None = None,
    diagnostics: DiagnosticTranscript | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> ThreadOutcome:
    """Run one exclusive, bounded host-input claim to a durable boundary."""

    if definition.session_mode is not SessionMode.continuing:
        raise ValueError("a thread run requires a continuing definition")
    if type(consume_on_cancel) is not bool:
        raise TypeError("consume_on_cancel must be bool")
    definition.input_projection_policy.resolve(input_projection)
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

    start = await _claim_and_admit(
        run_id=run_id,
        thread_id=thread_id,
        owner_token=owner_token,
        definition=definition,
        checkpoints=checkpoints,
        admission=admission,
        budget_factory=budget_factory,
        cancellation=cancellation,
        state=state,
        event=event,
    )
    if not isinstance(start, tuple):
        return start
    claim, token, budgets = start
    current_checkpoint = claim.through_checkpoint
    admitted_inputs = list(claim.inputs)
    session: ContinuingSessionState | None = None
    appended_batches: list[tuple[tuple[HostInput, ...], datetime, Checkpoint]] = []
    pending_content: list[TextContent] = []
    previous_lease_usage = ProviderUsage()
    observations: list[ToolObservation] = []
    repairs = 0
    dispatched = False
    speculative_session_discarded = False

    async def release_claim(reason: str) -> None:
        await _release_claim(checkpoints, claim, reason)

    async def park_claim(reason: str) -> None:
        await _park_claim(checkpoints, claim, reason)

    async def poll_before_settlement() -> NoNewInput | AppendInputs | Preempt:
        result = await checkpoints.poll(claim, current_checkpoint)
        if isinstance(result, AppendInputs):
            _validate_append(result, current_checkpoint, admitted_inputs)
        elif not isinstance(result, NoNewInput | Preempt):
            raise KernelConfigurationDefect("checkpoint port returned an unknown poll result")
        return result

    async def stop(kind: ThreadStopKind, reason: StopReason) -> ThreadStopped:
        if session is not None and state.provider_turns > 0:
            await discard_speculative_session()
        if isinstance(await poll_before_settlement(), Preempt):
            cancellation.cancel()
            return await preempt()
        await _settle_claim(
            checkpoints,
            claim,
            current_checkpoint,
            StoppedConclusion(reason),
        )
        event(EventKind.settlement, settlement_type="stopped", stop_kind=kind.value)
        state.outcome_type = kind.value
        return ThreadStopped(state.metrics(consumed=True), kind)

    async def preempt() -> ThreadStopped:
        if session is not None and state.provider_turns > 0:
            await discard_speculative_session()
        await release_claim("preempted by host policy")
        event(EventKind.cancellation, cancellation_type="preempted")
        state.outcome_type = ThreadStopKind.preempted.value
        return ThreadStopped(state.metrics(consumed=False), ThreadStopKind.preempted)

    async def cancelled() -> ThreadStopped:
        event(EventKind.cancellation, cancellation_type="cancelled")
        if consume_on_cancel:
            if session is not None and state.provider_turns > 0:
                await discard_speculative_session()
            if isinstance(await poll_before_settlement(), Preempt):
                return await preempt()
            await _settle_claim(
                checkpoints,
                claim,
                current_checkpoint,
                StoppedConclusion(StopReason.cancelled),
            )
            event(EventKind.settlement, settlement_type="cancelled")
            state.outcome_type = ThreadStopKind.cancelled.value
            return ThreadStopped(state.metrics(consumed=True), ThreadStopKind.cancelled)
        if session is not None and state.provider_turns > 0:
            await discard_speculative_session()
        await release_claim("cancelled without consuming host input")
        state.outcome_type = ThreadStopKind.cancelled.value
        return ThreadStopped(state.metrics(consumed=False), ThreadStopKind.cancelled)

    async def poll() -> NoNewInput | AppendInputs | Preempt:
        nonlocal current_checkpoint
        result = await checkpoints.poll(claim, current_checkpoint)
        if isinstance(result, NoNewInput):
            return result
        if isinstance(result, Preempt):
            cancellation.cancel()
            return result
        if not isinstance(result, AppendInputs):
            raise KernelConfigurationDefect("checkpoint port returned an unknown poll result")
        _validate_append(result, current_checkpoint, admitted_inputs)
        current_checkpoint = result.new_checkpoint
        admitted_inputs.extend(result.inputs)
        appended_batches.append((result.inputs, result.new_as_of, result.new_checkpoint))
        source = await context_source.continuation(
            definition,
            claim,
            result.inputs,
            current_checkpoint,
        )
        projection = continuation_context(
            definition,
            claim.plan,
            source,
            inputs=result.inputs,
            as_of=result.new_as_of,
            prior_visible_bytes=state.visible_bytes,
            input_projection=input_projection,
        )
        state.visible_bytes = projection.cumulative_visible_bytes
        pending_content.append(TextContent(projection.rendered))
        return result

    async def account_session_usage() -> None:
        nonlocal previous_lease_usage
        if session is None:
            raise KernelConfigurationDefect("provider usage requested without a session")
        current = await sessions.accumulated_usage(session)
        state.add_usage(current, previous_lease_usage)
        previous_lease_usage = current

    async def discard_speculative_session() -> None:
        nonlocal speculative_session_discarded
        if session is None or speculative_session_discarded:
            return
        await sessions.discard_before_replay(session)
        speculative_session_discarded = True

    async def configuration_failure(
        reason: str,
        *,
        discard_reference: bool,
    ) -> ThreadStopped:
        try:
            if session is not None:
                await account_session_usage()
                if discard_reference and state.provider_turns > 0:
                    await discard_speculative_session()
        finally:
            await park_claim(reason)
        state.outcome_type = ThreadStopKind.configuration_error.value
        return ThreadStopped(
            state.metrics(consumed=False),
            ThreadStopKind.configuration_error,
        )

    async def provider_turn(
        remaining: float,
    ) -> AgentTerminal | ThreadOutcome | None:
        nonlocal previous_lease_usage, session
        if session is None:
            raise KernelConfigurationDefect("provider turn requires a live session")
        state.provider_turns += 1
        event(EventKind.provider_turn, provider_turn=state.provider_turns, phase="started")
        emit_diagnostic(
            diagnostics,
            run_id,
            DiagnosticKind.provider_input,
            "\n".join(part.text for part in pending_content),
        )
        try:
            terminal = await sessions.run_observed_turn(
                session,
                tuple(pending_content),
                cancellation,
                timeout_seconds=remaining,
            )
            pending_content.clear()
            await account_session_usage()
        except _PROVIDER_CONFIGURATION_ERRORS:
            raise KernelConfigurationDefect(
                "provider configuration cannot satisfy the definition"
            ) from None
        except (SessionMismatch, SessionUnavailable) as error:
            await account_session_usage()
            if cancellation.cancelled:
                return await cancelled()
            if not dispatched and session.fallback_available:
                session = await sessions.cold_fallback(session, error)
                previous_lease_usage = ProviderUsage()
                source = await context_source.bootstrap(definition, claim)
                projection = bootstrap_context(
                    definition,
                    claim.inputs,
                    claim.as_of,
                    claim.plan,
                    source,
                    prior_visible_bytes=state.visible_bytes,
                    input_projection=input_projection,
                )
                state.visible_bytes = projection.cumulative_visible_bytes
                pending_content[:] = [TextContent(projection.rendered)]
                for batch, batch_as_of, batch_checkpoint in appended_batches:
                    source = await context_source.continuation(
                        definition,
                        claim,
                        batch,
                        batch_checkpoint,
                    )
                    projection = continuation_context(
                        definition,
                        claim.plan,
                        source,
                        inputs=batch,
                        as_of=batch_as_of,
                        prior_visible_bytes=state.visible_bytes,
                        input_projection=input_projection,
                    )
                    state.visible_bytes = projection.cumulative_visible_bytes
                    pending_content.append(TextContent(projection.rendered))
                return None
            return await stop(ThreadStopKind.provider_error, StopReason.provider_error)
        except TurnNotStarted as error:
            state.provider_turns -= 1
            await account_session_usage()
            if error.reason == "cancelled":
                return await cancelled()
            return await stop(
                ThreadStopKind.budget_exhausted,
                StopReason.budget_exhausted,
            )
        except AgentRuntimeError:
            await account_session_usage()
            if cancellation.cancelled:
                return await cancelled()
            return await stop(ThreadStopKind.provider_error, StopReason.provider_error)

        event(
            EventKind.provider_turn,
            provider_turn=state.provider_turns,
            phase="finished",
            status=terminal.status,
        )
        if terminal.status == "cancelled":
            emit_diagnostic(
                diagnostics,
                run_id,
                DiagnosticKind.provider_terminal,
                terminal.final_text,
            )
            return await cancelled()
        if terminal.status == "failed":
            emit_diagnostic(
                diagnostics,
                run_id,
                DiagnosticKind.provider_terminal,
                terminal.final_text,
            )
            kind, reason = _failed_terminal_stop(terminal)
            return await stop(kind, reason)
        if terminal.status != "succeeded":
            raise KernelConfigurationDefect("provider returned an unknown terminal status")

        session = await sessions.store_terminal_ref(session, terminal)
        emit_diagnostic(
            diagnostics,
            run_id,
            DiagnosticKind.provider_terminal,
            terminal.final_text,
        )
        if _kernel_budget_exhausted(definition, state):
            return await stop(
                ThreadStopKind.budget_exhausted,
                StopReason.budget_exhausted,
            )
        return terminal

    try:
        try:
            if cancellation.cancelled:
                return await cancelled()
            session = await sessions.acquire_continuing(
                thread_id,
                definition,
                recovering=claim.attempt_number > 1,
            )
            if cancellation.cancelled:
                return await cancelled()

            if session.cold_bootstrap:
                source = await context_source.bootstrap(definition, claim)
                projection = bootstrap_context(
                    definition,
                    claim.inputs,
                    claim.as_of,
                    claim.plan,
                    source,
                    prior_visible_bytes=state.visible_bytes,
                    input_projection=input_projection,
                )
            else:
                source = await context_source.continuation(
                    definition,
                    claim,
                    claim.inputs,
                    claim.through_checkpoint,
                )
                projection = run_context(
                    definition,
                    claim.inputs,
                    claim.as_of,
                    claim.plan,
                    source,
                    prior_visible_bytes=state.visible_bytes,
                    input_projection=input_projection,
                )
            state.visible_bytes = projection.cumulative_visible_bytes
            pending_content.insert(0, TextContent(projection.rendered))

            while True:
                if cancellation.cancelled:
                    return await cancelled()
                if state.provider_turns >= definition.limits.max_provider_turns:
                    return await stop(
                        ThreadStopKind.budget_exhausted,
                        StopReason.budget_exhausted,
                    )
                if isinstance(await poll(), Preempt):
                    return await preempt()
                if cancellation.cancelled:
                    return await cancelled()
                if not pending_content:
                    raise KernelConfigurationDefect("provider turn has no new canonical material")
                remaining = definition.limits.max_cooperative_seconds - state.elapsed()
                if remaining <= 0:
                    return await stop(
                        ThreadStopKind.budget_exhausted,
                        StopReason.budget_exhausted,
                    )

                turn = await provider_turn(remaining)
                if turn is None:
                    continue
                if not isinstance(turn, AgentTerminal):
                    return turn
                terminal = turn
                state.model_step_ordinal += 1
                try:
                    if not isinstance(terminal.structured_output, FrozenJsonDict):
                        raise ProtocolValidationError(
                            "successful terminal requires one structured object"
                        )
                    step = validate_provider_step(
                        terminal.structured_output,
                        definition.output_contract,
                        claim.plan,
                    )
                except (ProtocolValidationError, TypeError, ValueError):
                    event(EventKind.validation, valid=False)
                    state.model_step_ordinal -= 1
                    if repairs >= definition.limits.max_protocol_repairs:
                        return await stop(
                            ThreadStopKind.protocol_error,
                            StopReason.protocol_error,
                        )
                    repairs += 1
                    source = await context_source.continuation(
                        definition,
                        claim,
                        (),
                        current_checkpoint,
                    )
                    projection = continuation_context(
                        definition,
                        claim.plan,
                        source,
                        correction="Return exactly one value matching the required step schema.",
                        prior_visible_bytes=state.visible_bytes,
                    )
                    state.visible_bytes = projection.cumulative_visible_bytes
                    pending_content.append(TextContent(projection.rendered))
                    continue
                event(
                    EventKind.validation,
                    valid=True,
                    step_type=step.step.type if isinstance(step, ValidatedToolCall) else step.type,
                )

                if isinstance(step, ValidatedToolCall):
                    if cancellation.cancelled:
                        return await cancelled()
                    before_dispatch = await poll()
                    if isinstance(before_dispatch, Preempt):
                        return await preempt()
                    if isinstance(before_dispatch, AppendInputs):
                        continue
                    if cancellation.cancelled:
                        return await cancelled()
                    if _kernel_budget_exhausted(definition, state):
                        return await stop(
                            ThreadStopKind.budget_exhausted,
                            StopReason.budget_exhausted,
                        )
                    dispatched = True
                    lineage = DispatchLineage(
                        claim.claim_id,
                        current_checkpoint,
                        tuple(item.input_id for item in admitted_inputs),
                        state.model_step_ordinal,
                    )
                    event(
                        EventKind.tool_dispatch,
                        tool_id=str(step.tool_id),
                        model_step_ordinal=state.model_step_ordinal,
                        plan_revision=claim.plan.plan_revision,
                        implementation_revision=step.binding.implementation_revision,
                    )
                    dispatch = await dispatcher.dispatch(
                        binding=step.binding,
                        validated_input=step.arguments,
                        plan=claim.plan,
                        budgets=budgets,
                        cancellation=cancellation,
                        lineage=lineage,
                    )
                    if isinstance(dispatch, DispatchSuspended):
                        if isinstance(await poll_before_settlement(), Preempt):
                            cancellation.cancel()
                            return await preempt()
                        await _settle_claim(
                            checkpoints,
                            claim,
                            current_checkpoint,
                            SuspensionConclusion(dispatch.host_ref, dispatch.waiting_for),
                        )
                        event(
                            EventKind.suspension,
                            waiting_for=dispatch.waiting_for.value,
                        )
                        state.outcome_type = "suspended"
                        return ThreadSuspended(
                            state.metrics(consumed=True),
                            dispatch.host_ref,
                            dispatch.waiting_for,
                        )
                    if not isinstance(dispatch, DispatchCompleted):
                        raise KernelConfigurationDefect(
                            "dispatcher returned an unknown result variant"
                        )
                    observations.append(
                        ToolObservation(
                            step.binding,
                            dispatch.result,
                            state.model_step_ordinal,
                        )
                    )
                    if cancellation.cancelled:
                        return await cancelled()
                    if isinstance(await poll(), Preempt):
                        return await preempt()
                    if cancellation.cancelled:
                        return await cancelled()
                    if _kernel_budget_exhausted(definition, state):
                        return await stop(
                            ThreadStopKind.budget_exhausted,
                            StopReason.budget_exhausted,
                        )
                    source = await context_source.continuation(
                        definition,
                        claim,
                        (),
                        current_checkpoint,
                    )
                    projection = continuation_context(
                        definition,
                        claim.plan,
                        source,
                        observations=(observations[-1],),
                        prior_visible_bytes=state.visible_bytes,
                    )
                    state.visible_bytes = projection.cumulative_visible_bytes
                    pending_content.append(TextContent(projection.rendered))
                    continue

                if cancellation.cancelled:
                    return await cancelled()
                settlement_poll = await poll_before_settlement()
                if isinstance(settlement_poll, Preempt):
                    cancellation.cancel()
                    return await preempt()
                if cancellation.cancelled:
                    return await cancelled()
                if isinstance(step, SayStep):
                    conclusion = ConversationConclusion(step.text)
                elif isinstance(step, FinishStep):
                    conclusion = (
                        ConversationConclusion(None)
                        if step.result is NO_RESULT
                        else StructuredConclusion(step.result)
                    )
                else:
                    _unreachable(step)
                settlement = await _settle_claim(
                    checkpoints,
                    claim,
                    current_checkpoint,
                    conclusion,
                )
                event(
                    EventKind.settlement,
                    settlement_type=settlement.type,
                    more_input=isinstance(settlement, SettleMoreInput),
                )
                state.outcome_type = "completed"
                return ThreadCompleted(state.metrics(consumed=True))
        except asyncio.CancelledError:
            await release_claim("kernel task cancelled")
            raise
        except _PROVIDER_CONFIGURATION_ERRORS:
            return await configuration_failure(
                "provider configuration defect",
                discard_reference=True,
            )
        except AgentRuntimeError:
            if cancellation.cancelled:
                return await cancelled()
            return await stop(ThreadStopKind.provider_error, StopReason.provider_error)
        except (SessionRefStateDefect, StaleSessionReference):
            return await configuration_failure(
                "session reference defect",
                discard_reference=False,
            )
        except (
            AgentRuntimeDefect,
            CheckpointStateDefect,
            ContextLimitExceeded,
            ContextSourceDefect,
            ExecutorConfigurationDefect,
            KernelConfigurationDefect,
            PlanValidationError,
            PositionConflictDefect,
            ProviderDefect,
            RecoveryRequired,
            ToolDispatchDefect,
            TypeError,
            ValueError,
        ):
            return await configuration_failure(
                "configuration defect",
                discard_reference=True,
            )
        except BaseException:
            await release_claim("unexpected kernel interruption")
            raise
    finally:
        try:
            if session is not None:
                await account_session_usage()
        finally:
            try:
                if session is not None:
                    await sessions.release(session)
            finally:
                await admission.settle(
                    token,
                    AdmissionUsage(state.provider_turns, state.usage(), state.elapsed()),
                )
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


async def run_one_shot(
    *,
    run_id: RunId,
    definition: AgentDefinition,
    inputs: tuple[HostInput, ...],
    as_of: datetime,
    plan: FrozenToolPlan,
    source_sections: PromptSections,
    admission: AdmissionPort,
    provider: ProviderSessionPort,
    dispatcher: ToolDispatchPort,
    budget_factory: ToolBudgetFactoryPort,
    initial_read: InitialReadCall | None = None,
    input_projection: InputProjectionRequest | None = None,
    parent_admission: AdmissionToken | None = None,
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

    def stopped(kind: ThreadStopKind) -> OneShotStopped:
        if kind is ThreadStopKind.cancelled:
            event(EventKind.cancellation, cancellation_type="cancelled")
        state.outcome_type = kind.value
        return OneShotStopped(state.metrics(consumed=False), kind)

    def completed(result: object) -> OneShotCompleted:
        state.outcome_type = "completed"
        return OneShotCompleted(state.metrics(consumed=False), result)

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
            return stopped(ThreadStopKind.configuration_error)
        state.visible_bytes = projection.cumulative_visible_bytes

    admission_request = AdmissionRequest(
        run_id=run_id,
        thread_id=None,
        attempt_number=None,
        maximum_turns=definition.limits.max_provider_turns,
        maximum_input_tokens=definition.limits.max_provider_input_tokens,
        maximum_output_tokens=definition.limits.max_provider_output_tokens,
        parent=parent_admission,
    )
    try:
        admission_result = await admission.reserve(admission_request)
    except AdmissionStateDefect:
        event(EventKind.outcome, outcome_type="configuration_error")
        return stopped(ThreadStopKind.configuration_error)
    if not isinstance(admission_result, AdmissionGranted | AdmissionDeferred | AdmissionRejected):
        event(EventKind.outcome, outcome_type="configuration_error")
        return stopped(ThreadStopKind.configuration_error)
    event(EventKind.admission, admission_type=admission_result.type)
    if isinstance(admission_result, AdmissionDeferred | AdmissionRejected):
        event(EventKind.outcome, outcome_type="budget_exhausted")
        return stopped(ThreadStopKind.budget_exhausted)
    assert isinstance(admission_result, AdmissionGranted)

    token = admission_result.token
    try:
        _require_admission_token(admission_request, token)
    except KernelConfigurationDefect:
        await admission.settle(token, AdmissionUsage(0, ProviderUsage(), state.elapsed()))
        event(EventKind.outcome, outcome_type="configuration_error")
        return stopped(ThreadStopKind.configuration_error)
    lease: ProviderSessionLease | None = None
    previous_lease_usage = ProviderUsage()
    repairs = 0
    pending_content: list[TextContent] = []

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
                return stopped(ThreadStopKind.cancelled)
            if validated_initial_read is not None:
                budgets = _create_tool_budget(budget_factory, plan)
                if cancellation.cancelled:
                    return stopped(ThreadStopKind.cancelled)
                lineage = InitialReadDispatchLineage(run_id)
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
                dispatch = await dispatcher.dispatch(
                    binding=validated_initial_read.binding,
                    validated_input=validated_initial_read.arguments,
                    plan=plan,
                    budgets=budgets,
                    cancellation=cancellation,
                    lineage=lineage,
                )
                if isinstance(dispatch, DispatchSuspended):
                    return stopped(ThreadStopKind.configuration_error)
                if not isinstance(dispatch, DispatchCompleted):
                    raise KernelConfigurationDefect("dispatcher returned an unknown result variant")
                if cancellation.cancelled:
                    return stopped(ThreadStopKind.cancelled)
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
                            initial_read_position=lineage.position,
                        ),
                    ),
                    prior_visible_bytes=state.visible_bytes,
                    input_projection=input_projection,
                )
                state.visible_bytes = projection.cumulative_visible_bytes
            assert projection is not None
            assert budgets is not None
            pending_content.append(TextContent(projection.rendered))
            lease = await provider.open_isolated(definition)

            while True:
                if cancellation.cancelled:
                    return stopped(ThreadStopKind.cancelled)
                if state.provider_turns >= definition.limits.max_provider_turns:
                    return stopped(ThreadStopKind.budget_exhausted)
                remaining = definition.limits.max_cooperative_seconds - state.elapsed()
                if remaining <= 0:
                    return stopped(ThreadStopKind.budget_exhausted)
                state.provider_turns += 1
                event(EventKind.provider_turn, provider_turn=state.provider_turns, phase="started")
                emit_diagnostic(
                    diagnostics,
                    run_id,
                    DiagnosticKind.provider_input,
                    "\n".join(part.text for part in pending_content),
                )
                terminal = await provider.run_observed_turn(
                    lease,
                    tuple(pending_content),
                    cancellation,
                    timeout_seconds=remaining,
                )
                pending_content.clear()
                await account_lease_usage()
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
                    return stopped(ThreadStopKind.cancelled)
                if terminal.status == "failed":
                    kind, _reason = _failed_terminal_stop(terminal)
                    return stopped(kind)
                if terminal.status != "succeeded":
                    raise KernelConfigurationDefect("provider returned an unknown terminal status")
                if _kernel_budget_exhausted(definition, state):
                    return stopped(ThreadStopKind.budget_exhausted)

                state.model_step_ordinal += 1
                try:
                    if not isinstance(terminal.structured_output, FrozenJsonDict):
                        raise ProtocolValidationError(
                            "successful terminal requires one structured object"
                        )
                    step = validate_provider_step(
                        terminal.structured_output,
                        definition.output_contract,
                        plan,
                    )
                except (ProtocolValidationError, TypeError, ValueError):
                    state.model_step_ordinal -= 1
                    event(EventKind.validation, valid=False)
                    if repairs >= definition.limits.max_protocol_repairs:
                        return stopped(ThreadStopKind.protocol_error)
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
                        return stopped(ThreadStopKind.cancelled)
                    if _kernel_budget_exhausted(definition, state):
                        return stopped(ThreadStopKind.budget_exhausted)
                    event(
                        EventKind.tool_dispatch,
                        tool_id=str(step.tool_id),
                        model_step_ordinal=state.model_step_ordinal,
                        plan_revision=plan.plan_revision,
                        implementation_revision=step.binding.implementation_revision,
                    )
                    dispatch = await dispatcher.dispatch(
                        binding=step.binding,
                        validated_input=step.arguments,
                        plan=plan,
                        budgets=budgets,
                        cancellation=cancellation,
                        lineage=IsolatedDispatchLineage(
                            run_id,
                            state.model_step_ordinal,
                        ),
                    )
                    if isinstance(dispatch, DispatchSuspended):
                        return stopped(ThreadStopKind.configuration_error)
                    if not isinstance(dispatch, DispatchCompleted):
                        raise KernelConfigurationDefect(
                            "dispatcher returned an unknown result variant"
                        )
                    if cancellation.cancelled:
                        return stopped(ThreadStopKind.cancelled)
                    projection = continuation_context(
                        definition,
                        plan,
                        PromptSections(()),
                        observations=(
                            ToolObservation(
                                step.binding,
                                dispatch.result,
                                state.model_step_ordinal,
                            ),
                        ),
                        prior_visible_bytes=state.visible_bytes,
                    )
                    state.visible_bytes = projection.cumulative_visible_bytes
                    pending_content.append(TextContent(projection.rendered))
                    continue
                if isinstance(step, FinishStep) and step.result is not NO_RESULT:
                    if cancellation.cancelled:
                        return stopped(ThreadStopKind.cancelled)
                    return completed(step.result)
                raise KernelConfigurationDefect("isolated structured run ended without a result")
        except _PROVIDER_CONFIGURATION_ERRORS:
            await account_lease_usage()
            return stopped(ThreadStopKind.configuration_error)
        except TurnNotStarted as error:
            state.provider_turns -= 1
            await account_lease_usage()
            if error.reason == "cancelled":
                return stopped(ThreadStopKind.cancelled)
            return stopped(ThreadStopKind.budget_exhausted)
        except AgentRuntimeError:
            await account_lease_usage()
            if cancellation.cancelled:
                return stopped(ThreadStopKind.cancelled)
            return stopped(ThreadStopKind.provider_error)
        except (
            AgentRuntimeDefect,
            ContextLimitExceeded,
            ContextSourceDefect,
            ExecutorConfigurationDefect,
            KernelConfigurationDefect,
            PlanValidationError,
            PositionConflictDefect,
            ProviderDefect,
            RecoveryRequired,
            ToolDispatchDefect,
            TypeError,
            ValueError,
        ):
            await account_lease_usage()
            return stopped(ThreadStopKind.configuration_error)
    finally:
        try:
            if lease is not None:
                await account_lease_usage()
        finally:
            try:
                if lease is not None:
                    await provider.close(lease)
            finally:
                await admission.settle(
                    token,
                    AdmissionUsage(state.provider_turns, state.usage(), state.elapsed()),
                )
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


def _failed_terminal_stop(terminal: AgentTerminal) -> tuple[ThreadStopKind, StopReason]:
    if terminal.status != "failed":
        raise KernelConfigurationDefect("terminal is not failed")
    if isinstance(terminal.failure, AgentQuotaExhausted):
        return ThreadStopKind.quota_exhausted, StopReason.quota_exhausted
    if not isinstance(terminal.failure, AgentFailure):
        raise KernelConfigurationDefect("failed terminal lacks a known failure")
    if terminal.failure.cause == "turn_timeout":
        return ThreadStopKind.budget_exhausted, StopReason.budget_exhausted
    return ThreadStopKind.provider_error, StopReason.provider_error


def _validate_append(
    result: AppendInputs,
    current_checkpoint: Checkpoint,
    admitted_inputs: list[HostInput],
) -> None:
    if result.new_checkpoint == current_checkpoint:
        raise KernelConfigurationDefect("appended input did not advance the checkpoint")
    input_ids = tuple(item.input_id for item in result.inputs)
    known = {item.input_id for item in admitted_inputs}
    if known.intersection(input_ids) or len(input_ids) != len(set(input_ids)):
        raise KernelConfigurationDefect("appended input identities are not new and unique")


def _require_admission_token(request: AdmissionRequest, token: AdmissionToken) -> None:
    if token.run_id != request.run_id:
        raise KernelConfigurationDefect("admission token names a different run")
    if (
        token.reserved_turns < request.maximum_turns
        or token.reserved_input_tokens < request.maximum_input_tokens
        or token.reserved_output_tokens < request.maximum_output_tokens
    ):
        raise KernelConfigurationDefect("admission token does not cover the run maximum")
    if request.parent is None:
        if not token.owns_live_slot:
            raise KernelConfigurationDefect("root admission token does not own a live slot")
        return
    if not request.parent.owns_live_slot:
        raise KernelConfigurationDefect("child admission parent does not own the root slot")
    if token.owns_live_slot:
        raise KernelConfigurationDefect("child admission token must share its parent slot")
    if (
        token.root_epoch_id != request.parent.root_epoch_id
        or token.window_id != request.parent.window_id
    ):
        raise KernelConfigurationDefect("child admission token is outside its parent epoch")


def _unreachable(value: object) -> Never:
    raise KernelConfigurationDefect(f"unreachable model step: {type(value).__name__}")


__all__ = [
    "KernelConfigurationDefect",
    "run_one_shot",
    "run_thread",
]
