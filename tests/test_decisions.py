"""Paid decision recovery uses original durable evidence before any effects."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from provider_runtime.agent_runtime import AgentAttempt

from llm_agent_kernel import OneShotStopKind
from llm_agent_kernel.decisions import (
    IsolatedDecisionScope,
    ModelDecisionRequest,
    model_decision_id,
)
from llm_agent_kernel.fakes import InMemoryModelDecisionJournal
from test_kernel import _definition, _Runtime, _terminal


def _request(definition, plan, *, ordinal=1):
    scope = IsolatedDecisionScope("stable-owner-operation")
    return ModelDecisionRequest(
        scope=scope,
        ordinal=ordinal,
        definition_fingerprint=definition.fingerprint,
        plan_revision=plan.plan_revision,
        input_ids=(),
        through_checkpoint=None,
        as_of=datetime.now(UTC),
        model_step_ordinal_before=ordinal - 1,
        protocol_repairs=0,
        canonical_content=("original canonical request",),
        submitted_content=("original submitted request",),
        provider_attempt=AgentAttempt(model_decision_id(scope, ordinal), "d" * 64),
    )


def test_request_identity_excludes_attempt_but_fingerprint_covers_content():
    definition, plan, _ = _definition()
    request = _request(definition, plan)
    changed = replace(request, submitted_content=("changed",))
    assert request.decision_id == changed.decision_id
    assert request.request_fingerprint != changed.request_fingerprint
    assert (
        replace(
            request,
            ordinal=2,
            provider_attempt=AgentAttempt(model_decision_id(request.scope, 2), "d" * 64),
        ).decision_id
        != request.decision_id
    )


async def test_one_shot_completed_decision_replays_without_initial_read_or_provider(tmp_path: Path):
    from typing import cast

    from llm_tools import ToolEffect, ToolId
    from provider_runtime.agent_runtime import AgentRuntime

    from llm_agent_kernel import InitialReadCall, OneShotCompleted, RunId, SessionMode
    from llm_agent_kernel.decisions import DurableIsolatedDecisions, IsolatedDecisionScope
    from llm_agent_kernel.fakes import ScriptedToolDispatchPort
    from llm_agent_kernel.kernel import run_one_shot
    from llm_agent_kernel.provider import CodexProvider
    from test_kernel import _budget_factory, _Owner, _permit, _sections

    definition, plan, _ = _definition(
        mode=SessionMode.isolated, structured=True, effect=ToolEffect.Read
    )
    scope = IsolatedDecisionScope("stable-owner-operation")
    request = replace(
        _request(definition, plan),
        scope=scope,
        through_checkpoint=None,
        provider_attempt=AgentAttempt(model_decision_id(scope, 1), "d" * 64),
    )
    journal = InMemoryModelDecisionJournal()
    await journal.arm(request)
    await journal.complete(
        request,
        _terminal(
            {"type": "finish", "result": {"answer": "original"}}, attempt=request.provider_attempt
        ),
    )
    runtime = _Runtime([])
    dispatch = ScriptedToolDispatchPort(())
    outcome = await run_one_shot(
        decisions=DurableIsolatedDecisions(scope, journal),
        run_id=RunId("new-attempt"),
        definition=definition,
        inputs=(),
        as_of=request.as_of,
        plan=plan,
        source_sections=_sections("new context is not original"),
        owner=_Owner(),
        permit=_permit(),
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
    from llm_agent_kernel.fakes import ScriptedToolDispatchPort
    from llm_agent_kernel.kernel import run_one_shot
    from llm_agent_kernel.provider import CodexProvider
    from test_kernel import _budget_factory, _Owner, _permit, _sections

    definition, plan, _ = _definition(mode=SessionMode.isolated, structured=True)
    scope = IsolatedDecisionScope("stable-owner-operation")
    request = replace(
        _request(definition, plan),
        scope=scope,
        through_checkpoint=None,
        provider_attempt=AgentAttempt(model_decision_id(scope, 1), "d" * 64),
    )
    journal = InMemoryModelDecisionJournal()
    await journal.arm(request)
    runtime = _Runtime([])
    owner = _Owner()
    outcome = await run_one_shot(
        decisions=DurableIsolatedDecisions(scope, journal),
        run_id=RunId("new-random-attempt"),
        definition=definition,
        inputs=(),
        as_of=request.as_of,
        plan=plan,
        source_sections=_sections(),
        owner=owner,
        permit=_permit(),
        provider=CodexProvider(cast(AgentRuntime, runtime), cwd_parent=tmp_path),
        dispatcher=ScriptedToolDispatchPort(()),
        budget_factory=_budget_factory(),
    )
    assert outcome.type is OneShotStopKind.model_decision_uncertain
    assert outcome.metrics.provider_turns == 0
    assert runtime.opens == runtime.turns == []
