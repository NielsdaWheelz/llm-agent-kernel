"""Paid decision recovery uses original durable evidence before any effects."""

from dataclasses import replace
from pathlib import Path

from provider_runtime.agent_runtime import TextContent

from llm_agent_kernel import ClaimAcquired, ConversationConclusion, ThreadCompleted, ThreadStopKind
from llm_agent_kernel.decisions import (
    ModelDecisionArmed,
    ModelDecisionCompleted,
    ModelDecisionDefect,
    ModelDecisionRequest,
    ModelDecisionScope,
)
from llm_agent_kernel.definitions import ThreadId
from llm_agent_kernel.fakes import InMemoryInputCheckpointPort, InMemoryModelDecisionJournal
from test_kernel import _claim, _definition, _Runtime, _terminal, _thread


def _request(definition, claim, *, ordinal=1):
    return ModelDecisionRequest(
        scope=ModelDecisionScope(ThreadId("thread-1"), claim.inputs[0].input_id),
        ordinal=ordinal,
        definition_fingerprint=definition.fingerprint,
        plan_revision=claim.plan.plan_revision,
        input_ids=tuple(item.input_id for item in claim.inputs),
        through_checkpoint=claim.through_checkpoint,
        as_of=claim.as_of,
        model_step_ordinal_before=ordinal - 1,
        protocol_repairs=0,
        canonical_content=("original canonical request",),
        submitted_content=("original submitted request",),
    )


async def test_completed_decision_replays_without_opening_or_paying_provider(tmp_path: Path):
    definition, plan, _ = _definition()
    claim = _claim(plan)
    journal = InMemoryModelDecisionJournal()
    request = _request(definition, claim)
    terminal = _terminal({"type": "say", "text": "original accepted answer"})
    await journal.arm(request)
    await journal.complete(request, terminal)
    runtime = _Runtime([])
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    outcome, _ = await _thread(tmp_path, definition, claim, runtime, checkpoints, decisions=journal)
    assert isinstance(outcome, ThreadCompleted)
    assert outcome.metrics.provider_turns == 0
    assert runtime.opens == runtime.turns == []
    assert checkpoints.settlements[0].conclusion == ConversationConclusion(
        "original accepted answer"
    )


async def test_armed_uncertainty_is_parked_before_poison_or_provider(tmp_path: Path):
    definition, plan, _ = _definition()
    claim = _claim(plan, attempt=999)
    journal = InMemoryModelDecisionJournal()
    request = _request(definition, claim)
    await journal.arm(request)
    runtime = _Runtime([])
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    outcome, _ = await _thread(tmp_path, definition, claim, runtime, checkpoints, decisions=journal)
    assert outcome.type is ThreadStopKind.model_decision_uncertain
    assert not outcome.metrics.input_consumed
    assert not checkpoints.settlements
    assert checkpoints.park_reasons
    assert runtime.opens == runtime.turns == []
    assert await journal.latest(request.scope) == ModelDecisionArmed(request)


async def test_changed_definition_cannot_replay_paid_decision(tmp_path: Path):
    definition, plan, _ = _definition()
    claim = _claim(plan)
    journal = InMemoryModelDecisionJournal()
    request = replace(_request(definition, claim), definition_fingerprint="f" * 64)
    await journal.arm(request)
    await journal.complete(request, _terminal({"type": "say", "text": "stale authority"}))
    runtime = _Runtime([])
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    outcome, _ = await _thread(tmp_path, definition, claim, runtime, checkpoints, decisions=journal)
    assert outcome.type is ThreadStopKind.configuration_error
    assert not checkpoints.settlements
    assert checkpoints.park_reasons
    assert not runtime.opens


class _RejectCompletion(InMemoryModelDecisionJournal):
    async def complete(self, request, terminal):
        raise ModelDecisionDefect("durable completion failed")


async def test_completion_failure_prevents_settlement(tmp_path: Path):
    definition, plan, _ = _definition()
    claim = _claim(plan)
    journal = _RejectCompletion()
    runtime = _Runtime([(_terminal({"type": "say", "text": "must remain unpublished"}),)])
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    outcome, _ = await _thread(tmp_path, definition, claim, runtime, checkpoints, decisions=journal)
    assert outcome.type is ThreadStopKind.configuration_error
    assert not checkpoints.settlements
    latest = await journal.latest(_request(definition, claim).scope)
    assert isinstance(latest, ModelDecisionArmed)


async def test_original_terminal_is_durable_before_settlement(tmp_path: Path):
    definition, plan, _ = _definition()
    claim = _claim(plan)
    journal = InMemoryModelDecisionJournal()
    terminal = _terminal({"type": "say", "text": "accepted"})

    class Checkpoints(InMemoryInputCheckpointPort):
        async def settle(self, claim, through_checkpoint, conclusion):
            latest = await journal.latest(_request(definition, claim).scope)
            assert isinstance(latest, ModelDecisionCompleted)
            assert latest.terminal == terminal
            assert latest.request.canonical_content
            return await super().settle(claim, through_checkpoint, conclusion)

    runtime = _Runtime([(terminal,)])
    checkpoints = Checkpoints((ClaimAcquired(claim),))
    outcome, _ = await _thread(tmp_path, definition, claim, runtime, checkpoints, decisions=journal)
    assert isinstance(outcome, ThreadCompleted)


def test_request_identity_excludes_attempt_but_fingerprint_covers_content():
    definition, plan, _ = _definition()
    claim = _claim(plan)
    request = _request(definition, claim)
    changed = replace(request, submitted_content=("changed",))
    assert request.decision_id == changed.decision_id
    assert request.request_fingerprint != changed.request_fingerprint
    assert replace(request, ordinal=2).decision_id != request.decision_id


async def test_completed_tool_decision_continues_on_fresh_canonical_context(tmp_path: Path):
    from llm_tools import ToolEffect

    from llm_agent_kernel import DispatchCompleted
    from llm_agent_kernel.fakes import ScriptedToolDispatchPort

    definition, plan, _ = _definition(effect=ToolEffect.Read)
    claim = _claim(plan)
    journal = InMemoryModelDecisionJournal()
    request = _request(definition, claim)
    await journal.arm(request)
    await journal.complete(
        request,
        _terminal(
            {
                "type": "call_tool",
                "tool_id": "test.observe",
                "arguments": {"value": "original"},
            }
        ),
    )
    runtime = _Runtime([(_terminal({"type": "say", "text": "done"}),)])
    dispatch = ScriptedToolDispatchPort(
        (DispatchCompleted({"type": "Success", "value": {"value": "read evidence"}}),)
    )
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    outcome, _ = await _thread(
        tmp_path, definition, claim, runtime, checkpoints, dispatch, decisions=journal
    )
    assert isinstance(outcome, ThreadCompleted)
    assert outcome.metrics.provider_turns == 1
    assert len(runtime.turns) == len(runtime.opens) == len(dispatch.calls) == 1
    submitted = "\n".join(
        part.text for part in runtime.turns[0].input if isinstance(part, TextContent)
    )
    assert "original canonical request" in submitted
    assert "prior_model_decision" in submitted
    assert "read evidence" in submitted
    latest = await journal.latest(request.scope)
    assert isinstance(latest, ModelDecisionCompleted)
    assert latest.request.ordinal == 2
    assert latest.request.model_step_ordinal_before == 1
    assert "read evidence" in "\n".join(latest.request.canonical_content)


async def test_one_shot_completed_decision_replays_without_initial_read_or_provider(tmp_path: Path):
    from typing import cast

    from llm_tools import ToolEffect, ToolId
    from provider_runtime.agent_runtime import AgentRuntime

    from llm_agent_kernel import InitialReadCall, OneShotCompleted, RunId, SessionMode
    from llm_agent_kernel.decisions import DurableIsolatedDecisions, IsolatedDecisionScope
    from llm_agent_kernel.fakes import InMemoryAdmissionPort, ScriptedToolDispatchPort
    from llm_agent_kernel.kernel import run_one_shot
    from llm_agent_kernel.provider import CodexProvider
    from test_kernel import _budget_factory, _sections

    definition, plan, _ = _definition(
        mode=SessionMode.isolated, structured=True, effect=ToolEffect.Read
    )
    claim = _claim(plan)
    scope = IsolatedDecisionScope("stable-owner-operation")
    request = replace(_request(definition, claim), scope=scope, through_checkpoint=None)
    journal = InMemoryModelDecisionJournal()
    await journal.arm(request)
    await journal.complete(request, _terminal({"type": "finish", "result": {"answer": "original"}}))
    runtime = _Runtime([])
    dispatch = ScriptedToolDispatchPort(())
    outcome = await run_one_shot(
        decisions=DurableIsolatedDecisions(scope, journal),
        run_id=RunId("new-attempt"),
        definition=definition,
        inputs=claim.inputs,
        as_of=claim.as_of,
        plan=plan,
        source_sections=_sections("new context is not original"),
        admission=InMemoryAdmissionPort(),
        provider=CodexProvider(cast(AgentRuntime, runtime), cwd_parent=tmp_path),
        dispatcher=dispatch,
        budget_factory=_budget_factory(),
        initial_read=InitialReadCall(ToolId("test.observe"), {"value": "must not repeat"}),
    )
    assert isinstance(outcome, OneShotCompleted)
    assert outcome.result == {"answer": "original"}
    assert outcome.metrics.provider_turns == 0
    assert runtime.opens == runtime.turns == dispatch.calls == []


async def test_one_shot_uncertainty_cannot_be_evaded_by_new_run_id(tmp_path: Path):
    from typing import cast

    from provider_runtime.agent_runtime import AgentRuntime

    from llm_agent_kernel import RunId, SessionMode
    from llm_agent_kernel.decisions import DurableIsolatedDecisions, IsolatedDecisionScope
    from llm_agent_kernel.fakes import InMemoryAdmissionPort, ScriptedToolDispatchPort
    from llm_agent_kernel.kernel import run_one_shot
    from llm_agent_kernel.provider import CodexProvider
    from test_kernel import _budget_factory, _sections

    definition, plan, _ = _definition(mode=SessionMode.isolated, structured=True)
    claim = _claim(plan)
    scope = IsolatedDecisionScope("stable-owner-operation")
    request = replace(_request(definition, claim), scope=scope, through_checkpoint=None)
    journal = InMemoryModelDecisionJournal()
    await journal.arm(request)
    runtime = _Runtime([])
    admission = InMemoryAdmissionPort()
    outcome = await run_one_shot(
        decisions=DurableIsolatedDecisions(scope, journal),
        run_id=RunId("new-random-attempt"),
        definition=definition,
        inputs=claim.inputs,
        as_of=claim.as_of,
        plan=plan,
        source_sections=_sections(),
        admission=admission,
        provider=CodexProvider(cast(AgentRuntime, runtime), cwd_parent=tmp_path),
        dispatcher=ScriptedToolDispatchPort(()),
        budget_factory=_budget_factory(),
    )
    assert outcome.type is ThreadStopKind.model_decision_uncertain
    assert outcome.metrics.provider_turns == 0
    assert runtime.opens == runtime.turns == []


async def test_write_dispatch_has_durable_original_decision_and_no_effect_on_commit_failure(
    tmp_path: Path,
):
    from llm_tools import ToolEffect

    from llm_agent_kernel.fakes import ScriptedToolDispatchPort

    definition, plan, _ = _definition(effect=ToolEffect.Write)
    claim = _claim(plan)
    journal = _RejectCompletion()
    runtime = _Runtime(
        [
            (
                _terminal(
                    {
                        "type": "call_tool",
                        "tool_id": "test.observe",
                        "arguments": {"value": "write"},
                    }
                ),
            )
        ]
    )
    dispatch = ScriptedToolDispatchPort(())
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    outcome, _ = await _thread(
        tmp_path, definition, claim, runtime, checkpoints, dispatch, decisions=journal
    )
    assert outcome.type is ThreadStopKind.configuration_error
    assert not dispatch.calls and not checkpoints.settlements
    assert isinstance(await journal.latest(_request(definition, claim).scope), ModelDecisionArmed)


async def test_cancel_after_durable_arm_before_provider_entry_is_positively_undispatched(
    tmp_path: Path,
):
    from llm_agent_kernel import CancellationToken

    token = CancellationToken()

    class Journal(InMemoryModelDecisionJournal):
        async def arm(self, request):
            await super().arm(request)
            token.cancel()

    definition, plan, _ = _definition()
    claim = _claim(plan)
    journal = Journal()
    runtime = _Runtime([])
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    outcome, _ = await _thread(
        tmp_path, definition, claim, runtime, checkpoints, decisions=journal, cancellation=token
    )
    assert outcome.type is ThreadStopKind.cancelled
    assert outcome.metrics.provider_turns == 0
    assert not runtime.turns
    assert await journal.latest(_request(definition, claim).scope) is None


async def test_journal_substitution_cannot_change_model_output(tmp_path: Path):
    class Journal(InMemoryModelDecisionJournal):
        async def complete(self, request, terminal):
            original = await super().complete(request, terminal)
            return replace(original, terminal=_terminal({"type": "say", "text": "substituted"}))

    definition, plan, _ = _definition()
    claim = _claim(plan)
    journal = Journal()
    runtime = _Runtime([(_terminal({"type": "say", "text": "original"}),)])
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    outcome, _ = await _thread(tmp_path, definition, claim, runtime, checkpoints, decisions=journal)
    assert outcome.type is ThreadStopKind.configuration_error
    assert not checkpoints.settlements


async def test_replayed_read_retains_position_across_new_claim_and_attempt(tmp_path: Path):
    import pytest
    from llm_tools import ToolEffect

    from llm_agent_kernel import ClaimId, DispatchCompleted
    from llm_agent_kernel.fakes import ScriptedToolDispatchPort

    definition, plan, _ = _definition(effect=ToolEffect.Read)
    claim = _claim(plan)
    journal = InMemoryModelDecisionJournal()
    original = _terminal(
        {"type": "call_tool", "tool_id": "test.observe", "arguments": {"value": "original"}}
    )
    positions = []

    class CrashAfterRead(ScriptedToolDispatchPort):
        async def dispatch(self, **kwargs):
            positions.append(kwargs["lineage"].position)
            raise RuntimeError("crash after recorder-owned read")

    first = _Runtime([(original,)])
    with pytest.raises(RuntimeError, match="crash"):
        await _thread(
            tmp_path,
            definition,
            claim,
            first,
            InMemoryInputCheckpointPort((ClaimAcquired(claim),)),
            CrashAfterRead(()),
            decisions=journal,
        )
    recovered_claim = replace(claim, claim_id=ClaimId("new-attempt-claim"), attempt_number=2)
    second = _Runtime([(_terminal({"type": "say", "text": "done"}),)])
    dispatcher = ScriptedToolDispatchPort(
        (DispatchCompleted({"type": "Success", "value": {"value": "stored read"}}),)
    )
    outcome, _ = await _thread(
        tmp_path,
        definition,
        recovered_claim,
        second,
        InMemoryInputCheckpointPort((ClaimAcquired(recovered_claim),)),
        dispatcher,
        decisions=journal,
    )
    assert isinstance(outcome, ThreadCompleted)
    assert dispatcher.calls[0].lineage.position == positions[0]
    assert len(first.turns) == len(second.turns) == 1


async def test_completed_decision_survives_failed_session_cas_without_native_replay(tmp_path: Path):
    from llm_agent_kernel import ClaimId, StaleSessionRef
    from llm_agent_kernel.fakes import InMemorySessionRefPort

    class StaleReferences(InMemorySessionRefPort):
        async def compare_and_set(
            self, thread_id, definition_fingerprint, expected_generation, new_ref
        ):
            return StaleSessionRef()

    definition, plan, _ = _definition()
    claim = _claim(plan)
    journal = InMemoryModelDecisionJournal()
    references = StaleReferences()
    terminal = _terminal({"type": "say", "text": "paid accepted answer"})
    first_runtime = _Runtime([(terminal,)])
    first_checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    first, _ = await _thread(
        tmp_path,
        definition,
        claim,
        first_runtime,
        first_checkpoints,
        references=references,
        decisions=journal,
    )
    assert first.type is ThreadStopKind.configuration_error
    assert not first_checkpoints.settlements
    latest = await journal.latest(_request(definition, claim).scope)
    assert isinstance(latest, ModelDecisionCompleted) and latest.terminal == terminal

    recovered = replace(claim, claim_id=ClaimId("new-claim"), attempt_number=2)
    runtime = _Runtime([])
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(recovered),))
    outcome, _ = await _thread(
        tmp_path,
        definition,
        recovered,
        runtime,
        checkpoints,
        references=references,
        decisions=journal,
    )
    assert isinstance(outcome, ThreadCompleted)
    assert outcome.metrics.provider_turns == 0
    assert not runtime.opens and not runtime.turns
    assert checkpoints.settlements[0].conclusion == ConversationConclusion("paid accepted answer")
