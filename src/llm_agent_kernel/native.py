"""Serial host callbacks with independent native observation and control."""

from __future__ import annotations

import asyncio
import hashlib
from collections import deque
from collections.abc import Awaitable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, cast

from llm_tools import (
    PromptSections,
    ToolBinding,
    canonical_json_bytes,
    render_prompt,
    validate_tool_input,
)
from provider_runtime.agent_runtime import (
    AgentAccepted,
    AgentAttempt,
    AgentControlReceipt,
    AgentEvent,
    AgentInputRecorded,
    AgentMessage,
    AgentNative,
    AgentNotSubmitted,
    AgentPermissionRequest,
    AgentSubmission,
    AgentTerminal,
    AgentText,
    AgentToolCall,
    AgentToolReply,
    AgentToolUse,
    AgentTurnControls,
    AgentUncertain,
    AgentUsage,
    LocalStopEvidence,
    NativeTerminalEvidence,
    TextContent,
    codex_native_request_fits,
    thaw_json_value,
)
from provider_runtime.tool_adapter import (
    CanonicalToolCall,
    PublishedTools,
    RejectedToolArguments,
    RejectedToolCall,
    ToolPublication,
    lower_tools,
)
from provider_runtime.types import Present, TokenUsage, ToolCall

from .cancellation import CancellationToken
from .context import input_batch
from .coordination import (
    AppendInputs,
    NoNewInput,
    OwnerPort,
    PollResult,
    Preempt,
    ToolBudgetFactoryPort,
    ToolDispatchPort,
)
from .definitions import (
    Checkpoint,
    DispatchCompleted,
    DispatchSuspended,
    InputId,
    NativeDispatchLineage,
)
from .native_contract import (
    NativeDefect,
    NativeDefinition,
    NativeDelivery,
    NativeInputPort,
    NativeInvocationProposal,
    NativeJournal,
    NativeMessagePort,
    NativeRejected,
    NativeReply,
    NativeRequest,
    NativeUncertain,
)
from .provider import ProviderContainmentViolation, ProviderSessionLease, ProviderSessionPort
from .tools import require_native_plan


@dataclass(frozen=True, slots=True)
class _Callback:
    call: AgentToolCall
    proposal: NativeInvocationProposal
    binding: ToolBinding[Any, Any, Any]
    validated_input: object
    size: int


def native_request_fits(definition: NativeDefinition, sections: PromptSections) -> bool:
    """Measure actual kernel framing against the provider's contained request bound."""
    return codex_native_request_fits(
        render_prompt(sections),
        output=definition.output,
        reasoning=definition.provider.reasoning,
        input_id=_delivery_id("request-fit", ()),
    )


async def run_native(
    *,
    definition: NativeDefinition,
    request: NativeRequest,
    provider: ProviderSessionPort,
    session: ProviderSessionLease | None,
    owner: OwnerPort,
    journal: NativeJournal,
    inputs: NativeInputPort,
    dispatch: ToolDispatchPort,
    budgets: ToolBudgetFactoryPort,
    messages: NativeMessagePort,
    cancellation: CancellationToken,
) -> AgentNotSubmitted | AgentTerminal:
    """Supervise one native attempt; host policy owns task continuation/recovery."""
    await owner.require_current(request.permit)
    recovered = await journal.recover(request.attempt_id)
    if recovered is not None:
        if recovered.request.fingerprint != request.fingerprint:
            raise NativeDefect("native recovery changed its frozen request")
        await owner.require_current(request.permit)
        return recovered.terminal
    require_native_plan(request.plan, definition.maximum_profile)
    fingerprint = definition.session_fingerprint(request.plan)
    if session is None:
        raise NativeDefect("a new native attempt requires an explicitly acquired live session")
    if (
        session.definition_fingerprint != fingerprint
        or session.owner_token != request.permit.owner_token
    ):
        raise NativeDefect("native session belongs to another definition, plan or owner")
    published = lower_tools(ToolPublication(request.plan, ()))
    budget_state = budgets.create(request.plan)
    if budget_state.limits != request.plan.profile.run_limits:
        raise NativeDefect("native tool budget differs from the frozen plan")
    timeout = (
        None
        if request.deadline_at is None
        else (request.deadline_at - datetime.now(UTC)).total_seconds()
    )
    if timeout is not None and timeout <= 0:
        raise NativeDefect("native operation deadline already expired")
    initial_id = _delivery_id(request.attempt_id, request.input_ids)
    turn = provider.prepare_native_turn(
        session,
        (TextContent(render_prompt(request.submitted_sections)),),
        attempt_id=request.attempt_id,
        input_id=initial_id,
        controls=AgentTurnControls(
            definition.control.rpc_seconds,
            definition.control.pending_calls,
            definition.control.pending_call_bytes,
        ),
        timeout_seconds=timeout,
    )
    if turn.attempt.attempt_id != request.attempt_id:
        turn.revoke()
        await turn.close()
        raise NativeDefect("provider preparation changed its host attempt identity")
    queue: deque[_Callback] = deque()
    queued_bytes = 0
    active: _Callback | None = None
    callback_task: asyncio.Task[NativeReply] | None = None
    next_event: asyncio.Future[AgentEvent] | None = None
    poll_task: asyncio.Task[PollResult] | None = None
    cancel_wait: asyncio.Task[bool] | None = None
    interrupt_task: asyncio.Task[AgentControlReceipt] | None = None
    steer_task: asyncio.Task[AgentControlReceipt] | None = None
    steering_delivery: NativeDelivery | None = None
    terminal: AgentTerminal | None = None
    observed_usage: TokenUsage | None = None
    submission: AgentSubmission | None = None
    submit_task: asyncio.Task[AgentSubmission] | None = None
    armed = False
    stop_reason: str | None = None
    stop_deadline: float | None = None
    checkpoint = request.through_checkpoint
    delivered_checkpoint = request.through_checkpoint
    delivered_ids = request.input_ids
    deliveries = {
        initial_id: NativeDelivery(
            request.attempt_id, initial_id, request.input_ids, "initial", "prepared", None
        )
    }
    delivery_checkpoints = {initial_id: request.through_checkpoint}
    last_invalid: tuple[str, str] | None = None
    primary_error: BaseException | None = None

    async def poll() -> PollResult:
        await asyncio.sleep(definition.control.poll_seconds)
        return await inputs.poll(request, checkpoint)

    async def stop(reason: str) -> None:
        nonlocal stop_reason, stop_deadline, interrupt_task
        if stop_reason is not None:
            return
        stop_reason = reason
        turn.revoke()
        await journal.fence(request.attempt_id, reason)
        if callback_task is not None:
            callback_task.cancel()
        queue.clear()
        stop_deadline = (
            asyncio.get_running_loop().time() + definition.control.interrupt_grace_seconds
        )
        interrupt_task = asyncio.create_task(turn.interrupt())

    async def execute(callback: _Callback) -> NativeReply:
        await owner.require_current(request.permit)
        record = await journal.record_invocation(callback.proposal)
        if (
            replace(
                record.proposal,
                input_ids=callback.proposal.input_ids,
                through_checkpoint=callback.proposal.through_checkpoint,
            )
            != callback.proposal
            or not record.invocation_id
            or type(record.ordinal) is not int
            or record.ordinal < 1
        ):
            raise NativeDefect("native invocation journal changed the accepted proposal")
        if record.reply is not None:
            receipt = record.reply
        else:
            if callback.proposal.validation_error is not None:
                result = callback.proposal.validation_error
            else:
                await owner.require_current(request.permit)
                result = await dispatch.dispatch(
                    binding=callback.binding,
                    validated_input=callback.validated_input,
                    plan=request.plan,
                    budgets=budget_state,
                    cancellation=cancellation,
                    lineage=NativeDispatchLineage(
                        request.attempt_id,
                        record.invocation_id,
                        record.ordinal,
                        request.permit,
                        record.proposal.input_ids,
                        record.proposal.through_checkpoint,
                        fingerprint,
                    ),
                )
            receipt = _reply(result)
            await journal.record_reply(record.invocation_id, receipt)
        await owner.require_current(request.permit)
        await turn.reply(callback.call, AgentToolReply(receipt.text, receipt.success))
        return receipt

    async def observe_poll(result: PollResult) -> None:
        nonlocal pending_input
        if isinstance(result, Preempt):
            await stop(result.reason)
        elif isinstance(result, AppendInputs):
            if pending_input is None:
                pending_input = result
            else:
                existing = {item.input_id: item for item in pending_input.inputs}
                if any(
                    item.input_id in existing and existing[item.input_id] != item
                    for item in result.inputs
                ):
                    raise NativeDefect("native input append changed an original input")
                pending_input = AppendInputs(
                    (
                        *pending_input.inputs,
                        *(item for item in result.inputs if item.input_id not in existing),
                    ),
                    result.new_checkpoint,
                    result.new_as_of,
                )
        elif not isinstance(result, NoNewInput):
            raise NativeDefect("native input port returned an unknown result")

    try:
        await owner.require_current(request.permit)
        await journal.arm(
            request,
            turn.attempt,
            definition_fingerprint=fingerprint,
            submitted_request=turn.submitted_request,
        )
        armed = True
        await journal.record_delivery(deliveries[initial_id])
        before = await inputs.poll(request, checkpoint)
        if cancellation.cancelled or isinstance(before, Preempt):
            turn.revoke()
        pending_input = before if isinstance(before, AppendInputs) else None
        submit_task = asyncio.create_task(turn.submit())
        poll_task = asyncio.create_task(poll())
        cancel_wait = asyncio.create_task(cancellation.wait())
        while not submit_task.done():
            pending: list[asyncio.Task[object]] = [submit_task]
            if stop_reason is None:
                pending.extend((poll_task, cancel_wait))
            if interrupt_task is not None:
                pending.append(interrupt_task)
            grace = (
                None
                if stop_deadline is None
                else max(0.0, stop_deadline - asyncio.get_running_loop().time())
            )
            done, _ = await asyncio.wait(
                pending, timeout=grace, return_when=asyncio.FIRST_COMPLETED
            )
            if not done:
                submission = turn.submission
                if isinstance(submission, AgentAccepted):
                    break
                if not isinstance(submission, AgentUncertain):
                    raise NativeUncertain("native submission has no authoritative outcome")
                terminal = AgentTerminal(
                    status="cancelled",
                    failure=None,
                    final_text="",
                    session_ref=session.session.ref,
                    evidence=LocalStopEvidence(submission, stop_reason or "interrupted"),
                )
                await journal.record_outcome(request.attempt_id, submission)
                await journal.record_outcome(request.attempt_id, terminal)
                return terminal
            if cancel_wait in done and stop_reason is None:
                await stop("cancelled")
            if poll_task in done and stop_reason is None:
                await observe_poll(poll_task.result())
                poll_task = asyncio.create_task(poll())
            if interrupt_task is not None and interrupt_task in done:
                control = interrupt_task.result()
                if control.operation != "interrupt":
                    raise NativeDefect("native interrupt receipt changed its operation")
                await journal.record_outcome(request.attempt_id, control)
                interrupt_task = None
        submission = await submit_task
        if isinstance(submission, AgentNotSubmitted):
            await journal.record_outcome(request.attempt_id, submission)
            await journal.fence(request.attempt_id, submission.reason)
            return submission
        if not isinstance(submission, AgentAccepted):
            if not isinstance(submission, AgentUncertain):
                raise NativeDefect("provider returned unknown submission evidence")
            await journal.record_outcome(request.attempt_id, submission)
            raise NativeUncertain("native submission remains unresolved")
        await journal.bind(request.attempt_id, submission.turn)
        await journal.record_delivery(
            replace(deliveries[initial_id], state="sent", evidence=submission)
        )
        stream = turn.events()
        next_event = asyncio.ensure_future(anext(stream))
        while True:
            waiters = [next_event, poll_task]
            if stop_reason is None:
                waiters.append(cancel_wait)
            if callback_task is not None:
                waiters.append(callback_task)
            if steer_task is not None:
                waiters.append(steer_task)
            if interrupt_task is not None:
                waiters.append(interrupt_task)
            remaining_grace = (
                None
                if stop_deadline is None
                else max(0.0, stop_deadline - asyncio.get_running_loop().time())
            )
            done, _ = await asyncio.wait(
                waiters, timeout=remaining_grace, return_when=asyncio.FIRST_COMPLETED
            )
            if not done:
                # Reader-latched native truth wins an expired local stop grace.
                if turn.terminal is not None and isinstance(
                    turn.terminal.evidence, NativeTerminalEvidence
                ):
                    terminal = turn.terminal
                    _require_terminal(terminal, turn.attempt, submission)
                else:
                    terminal = AgentTerminal(
                        status="cancelled",
                        failure=None,
                        final_text="",
                        session_ref=session.session.ref,
                        evidence=LocalStopEvidence(submission, stop_reason or "interrupted"),
                    )
                await journal.record_outcome(request.attempt_id, terminal)
                return terminal
            if interrupt_task is not None and interrupt_task in done:
                control = interrupt_task.result()
                if control.operation != "interrupt" or (
                    control.turn != submission.turn
                    and not (
                        control.turn is None and control.disposition in ("not_sent", "unknown")
                    )
                ):
                    raise NativeDefect("native interrupt receipt changed its operation or turn")
                await journal.record_outcome(request.attempt_id, control)
                interrupt_task = None
            if next_event in done:
                try:
                    event = next_event.result()
                except StopAsyncIteration as error:
                    raise NativeUncertain(
                        "native stream ended without terminal evidence"
                    ) from error
                if isinstance(event, AgentTerminal):
                    terminal = event
                    if isinstance(terminal.evidence, NativeTerminalEvidence):
                        _require_terminal(terminal, turn.attempt, submission)
                    await journal.record_outcome(request.attempt_id, terminal)
                    return terminal
                if isinstance(event, AgentToolUse | AgentPermissionRequest):
                    raise ProviderContainmentViolation(
                        "native provider emitted undeclared authority activity"
                    )
                if isinstance(event, AgentToolCall):
                    if event.turn != submission.turn:
                        raise NativeDefect("native callback changed its submitted turn")
                    if stop_reason is None:
                        callback = _callback(
                            event, request, published, delivered_ids, delivered_checkpoint
                        )
                        total_calls = len(queue) + (1 if active is not None else 0) + 1
                        if (
                            total_calls > definition.control.pending_calls
                            or queued_bytes + callback.size > definition.control.pending_call_bytes
                        ):
                            raise NativeDefect("native callback queue overflow")
                        queue.append(callback)
                        queued_bytes += callback.size
                elif isinstance(event, AgentMessage):
                    if event.turn != submission.turn:
                        raise NativeDefect("native public message changed its turn")
                    if event.phase == "commentary" and stop_reason is None:
                        await messages.record(request.attempt_id, event)
                        last_invalid = None
                elif isinstance(event, AgentInputRecorded):
                    if event.turn != submission.turn or event.input_id not in deliveries:
                        raise NativeDefect("native input recording has unknown delivery identity")
                    deliveries[event.input_id] = replace(
                        deliveries[event.input_id], state="recorded", evidence=event
                    )
                    await journal.record_delivery(deliveries[event.input_id])
                    delivered_ids += tuple(
                        value
                        for value in deliveries[event.input_id].input_ids
                        if value not in delivered_ids
                    )
                    delivered_checkpoint = delivery_checkpoints[event.input_id]
                    last_invalid = None
                elif isinstance(event, AgentUsage):
                    observed_usage = event.usage
                elif not isinstance(event, AgentText | AgentNative):
                    raise NativeDefect("native provider emitted an unknown event")
                next_event = asyncio.ensure_future(anext(stream))
            if callback_task is not None and callback_task in done:
                if callback_task.cancelled() and stop_reason is not None:
                    receipt = None
                else:
                    receipt = callback_task.result()
                if active is None:
                    raise NativeDefect("callback completion has no active invocation")
                queued_bytes -= active.size
                if receipt is not None and isinstance(receipt.result, NativeRejected):
                    identity = (active.proposal.proposal_digest, active.call.call_id)
                    if (
                        last_invalid is not None
                        and last_invalid[0] == identity[0]
                        and last_invalid[1] != identity[1]
                    ):
                        await stop("no_progress")
                    last_invalid = identity
                else:
                    last_invalid = None
                active = None
                callback_task = None
            if cancel_wait in done and stop_reason is None and turn.terminal is None:
                await stop("cancelled")
            if poll_task in done:
                await observe_poll(poll_task.result())
                poll_task = asyncio.create_task(poll())
            if steer_task is not None and steer_task in done:
                control = steer_task.result()
                if (
                    steering_delivery is None
                    or control.operation != "steer"
                    or (
                        control.turn != submission.turn
                        and not (
                            control.turn is None and control.disposition in ("not_sent", "unknown")
                        )
                    )
                    or control.input_id != steering_delivery.delivery_id
                ):
                    raise NativeDefect("native steer receipt changed its delivery or turn")
                await journal.record_outcome(request.attempt_id, control)
                if deliveries[steering_delivery.delivery_id].state != "recorded":
                    state = (
                        "queued"
                        if control.disposition == "accepted"
                        else "rejected"
                        if control.disposition in ("not_sent", "rejected")
                        else "sent"
                    )
                    deliveries[steering_delivery.delivery_id] = replace(
                        steering_delivery, state=state, evidence=control
                    )
                    await journal.record_delivery(deliveries[steering_delivery.delivery_id])
                    if control.disposition == "unknown" and stop_reason is None:
                        raise NativeUncertain("native input steering has unresolved delivery")
                steer_task = None
                steering_delivery = None
            if pending_input is not None and stop_reason is None and steer_task is None:
                new_ids = tuple(item.input_id for item in pending_input.inputs)
                if set(new_ids).intersection(delivered_ids):
                    raise NativeDefect("native input append repeated an admitted input")
                await owner.require_current(request.permit)
                delivery_id = _delivery_id(request.attempt_id, new_ids)
                delivery = NativeDelivery(
                    request.attempt_id, delivery_id, new_ids, "steer", "prepared", None
                )
                deliveries[delivery_id] = delivery
                delivery_checkpoints[delivery_id] = pending_input.new_checkpoint
                await journal.record_delivery(delivery)
                content = render_prompt(
                    PromptSections(
                        (
                            input_batch(
                                pending_input.inputs,
                                pending_input.new_as_of,
                                render_source_timestamps=True,
                                render_batch_as_of=True,
                            ),
                        )
                    )
                )
                steering_delivery = delivery
                steer_task = asyncio.create_task(
                    turn.steer(input_id=delivery_id, input=(TextContent(content),))
                )
                checkpoint = pending_input.new_checkpoint
                pending_input = None
                last_invalid = None
            if callback_task is None and queue and stop_reason is None:
                active = queue.popleft()
                callback_task = asyncio.create_task(execute(active))
    except BaseException as error:
        primary_error = error
        turn.revoke()
        if armed:
            try:
                if turn.terminal is not None and isinstance(
                    turn.terminal.evidence, NativeTerminalEvidence
                ):
                    _require_terminal(turn.terminal, turn.attempt, turn.submission)
                    await journal.record_outcome(request.attempt_id, turn.terminal)
                elif turn.submission is not None:
                    await journal.record_outcome(request.attempt_id, turn.submission)
                await journal.fence(request.attempt_id, type(error).__name__)
            except BaseException as retention_error:
                error.add_note(
                    f"{type(retention_error).__name__}: native evidence retention or fencing failed"
                )
        raise
    finally:
        tasks = tuple(
            task
            for task in (
                callback_task,
                submit_task,
                next_event,
                poll_task,
                cancel_wait,
                interrupt_task,
                steer_task,
            )
            if task is not None
        )
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(
            *(cast(Awaitable[object], task) for task in tasks), return_exceptions=True
        )
        if terminal is not None and isinstance(terminal.usage, Present):
            observed_usage = terminal.usage.value
        if not isinstance(turn.submission, AgentNotSubmitted):
            session.record_usage(observed_usage)
        try:
            close = await turn.close()
            session.record_diagnostics(close.diagnostics)
            if (
                primary_error is not None
                or terminal is None
                or terminal.status != "succeeded"
                or not close.local_closed
            ):
                await provider.discard(session)
        except BaseException as cleanup_error:
            session.record_diagnostics((f"{type(cleanup_error).__name__}: native cleanup failed",))
            if primary_error is not None:
                primary_error.add_note("native cleanup also failed")
            elif terminal is None and not isinstance(submission, AgentNotSubmitted):
                raise


def _delivery_id(attempt_id: str, input_ids: tuple[InputId, ...]) -> str:
    return hashlib.sha256(
        canonical_json_bytes({"attempt_id": attempt_id, "input_ids": list(input_ids)})
    ).hexdigest()


def _callback(
    call: AgentToolCall,
    request: NativeRequest,
    published: PublishedTools,
    input_ids: tuple[InputId, ...],
    checkpoint: Checkpoint | None,
) -> _Callback:
    raw = thaw_json_value(call.arguments)
    resolved = published.decode_tool_call(ToolCall(call.call_id, call.name, cast(Any, raw)))
    if isinstance(resolved, RejectedToolCall):
        raise ProviderContainmentViolation("native callback selected an undeclared tool")
    binding = request.plan.catalog_view.binding(resolved.tool_id)
    rejection = None
    validated = None
    if isinstance(resolved, RejectedToolArguments):
        rejection = NativeRejected(
            "input_too_large" if resolved.reason == "InputTooLarge" else "invalid_arguments",
            "arguments do not meet the declared tool contract; correct them before requesting this tool again",
        )
    elif isinstance(resolved, CanonicalToolCall):
        try:
            validated = validate_tool_input(binding, dict(resolved.arguments))
        except (TypeError, ValueError):
            rejection = NativeRejected(
                "invalid_arguments",
                "arguments do not meet the declared tool contract; correct them before requesting this tool again",
            )
    else:
        raise NativeDefect("native tool publication returned unknown resolution")
    proposal_digest = hashlib.sha256(
        canonical_json_bytes(
            {"name": call.name, "arguments": raw, "plan_revision": request.plan.plan_revision}
        )
    ).hexdigest()
    proposal = NativeInvocationProposal(
        request.attempt_id,
        call.call_id,
        resolved.tool_id,
        call.arguments,
        proposal_digest,
        request.plan.plan_revision,
        binding.spec.tool_contract_revision,
        binding.implementation_revision,
        binding.policy_revision,
        input_ids,
        checkpoint,
        rejection,
    )
    return _Callback(
        call,
        proposal,
        binding,
        validated,
        len(canonical_json_bytes({"name": call.name, "arguments": raw})),
    )


def _reply(result: DispatchCompleted | DispatchSuspended | NativeRejected) -> NativeReply:
    if isinstance(result, DispatchCompleted):
        return NativeReply(result.model_text, result.result["type"] == "Success", result)
    if isinstance(result, DispatchSuspended):
        value = {
            "type": "pending_action",
            "action_ref": str(result.host_ref),
            "waiting_for": result.waiting_for.value,
            "text": "the action is pending and has not executed; continue independent work and await its host resolution",
        }
        return NativeReply(canonical_json_bytes(value).decode(), True, result)
    if isinstance(result, NativeRejected):
        return NativeReply(
            canonical_json_bytes(
                {"type": "rejected", "code": result.code, "text": result.text}
            ).decode(),
            False,
            result,
        )
    raise NativeDefect("native dispatcher returned an unknown result")


def _require_terminal(
    terminal: AgentTerminal, attempt: AgentAttempt, submission: AgentSubmission | None
) -> None:
    evidence = terminal.evidence
    if not isinstance(evidence, NativeTerminalEvidence) or evidence.attempt != attempt:
        raise NativeDefect("native terminal changed its submitted attempt")
    if not isinstance(submission, AgentAccepted) or evidence.native_ref != submission.turn:
        raise NativeDefect("native terminal changed its accepted native identity")


__all__ = ["run_native"]
