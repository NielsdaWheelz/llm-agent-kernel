"""Run one fake-backed continuing thread without provider or network access."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from llm_tools import (
    BudgetState,
    CapabilityProfile,
    FrozenToolPlan,
    HostTable,
    InvocationPosition,
    ProfileId,
    PromptSection,
    PromptSectionKind,
    PromptSections,
    PromptText,
    Reservation,
    RunLimits,
    Settlement,
    ToolCatalog,
    ToolPlan,
)
from provider_runtime.agent_runtime import (
    AgentEvent,
    AgentRuntime,
    AgentSession,
    AgentSessionRef,
    AgentSessionRequest,
    AgentTerminal,
    CredentialRef,
    TurnRequest,
    freeze_json_object,
)
from provider_runtime.types import Absent, CancelSignal, Present, TokenUsage

from llm_agent_kernel import (
    AgentDefinition,
    AgentRole,
    Checkpoint,
    ClaimAcquired,
    ClaimId,
    CodexProvider,
    ConversationalOutput,
    ConversationConclusion,
    DefinitionId,
    HostInput,
    InMemoryAdmissionPort,
    InMemoryInputCheckpointPort,
    InMemorySessionRefPort,
    InputClaim,
    InputId,
    OwnerToken,
    ProviderConfiguration,
    RunId,
    ScriptedToolDispatchPort,
    SessionCoordinator,
    SessionMode,
    StaticContextSource,
    ThreadCompleted,
    ThreadId,
    run_thread,
)


def sections(kind: str, text: str) -> PromptSections:
    return PromptSections((PromptSection(PromptSectionKind(kind), (), PromptText(text)),))


class NoToolBudget:
    """BudgetState for an empty plan; tool accounting is unreachable."""

    def __init__(self, limits: RunLimits) -> None:
        self.limits = limits

    @property
    def remaining_elapsed_seconds(self) -> float:
        return self.limits.max_elapsed_seconds

    async def reserve(
        self,
        position: InvocationPosition,
        reservation: Reservation,
    ) -> bool:
        raise AssertionError(f"empty plan cannot reserve {position}: {reservation}")

    async def settle(
        self,
        position: InvocationPosition,
        settlement: Settlement,
    ) -> None:
        raise AssertionError(f"empty plan cannot settle {position}: {settlement}")


class NoToolBudgetFactory:
    def create(self, plan: FrozenToolPlan) -> BudgetState:
        return cast(BudgetState, NoToolBudget(plan.profile.run_limits))


class ScriptedRuntime:
    """One-response AgentRuntime test double; it performs no external I/O."""

    def __init__(self) -> None:
        self.ref = AgentSessionRef(
            "agent-session-ref.v1",
            "codex",
            "sdk",
            "scripted-session",
            "example",
            "1" * 64,
            "2" * 64,
        )

    async def open_session(self, request: AgentSessionRequest) -> AgentSession:
        del request
        return AgentSession(self.ref)

    async def stream_turn(
        self,
        session: AgentSession,
        request: TurnRequest,
        *,
        approvals: object | None = None,
        cancel: CancelSignal | None = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        del session, request, approvals, cancel
        yield AgentTerminal(
            status="succeeded",
            failure=None,
            final_text="scripted provider projection",
            session_ref=self.ref,
            structured_output=freeze_json_object(
                {
                    "type": "say",
                    "say": {"text": "Hello from the bounded kernel."},
                    "call_tool": None,
                    "finish": None,
                }
            ),
            usage=Present(TokenUsage(12, 6, 18, Absent(), Absent(), Absent())),
        )

    async def run_turn(self, *_args: object, **_kwargs: object) -> AgentTerminal:
        raise AssertionError("the kernel must consume AgentRuntime.stream_turn")

    async def close_session(self, session: AgentSession) -> None:
        del session


async def main() -> None:
    run_limits = RunLimits(1, 1, 1_024, 1_024, 1, 30.0)
    catalog = ToolCatalog.compose(())
    maximum = CapabilityProfile(ProfileId("empty"), (), run_limits).freeze(catalog)
    plan = ToolPlan(maximum.id, HostTable()).freeze(catalog, maximum)
    definition = AgentDefinition(
        DefinitionId("example"),
        AgentRole("assistant", sections("role", "Answer the admitted input.")),
        sections("stable_context", "This is an offline example."),
        SessionMode.continuing,
        ConversationalOutput(),
        maximum,
        ProviderConfiguration(CredentialRef("local_account", "example"), "scripted"),
        "minimal-example-v1",
    )

    now = datetime.now(UTC)
    host_input = HostInput(InputId("input-1"), sections("input", "Say hello."), now)
    claim = InputClaim(
        ClaimId("claim-1"),
        (host_input,),
        Checkpoint("checkpoint-1"),
        now,
        plan,
        1,
    )
    checkpoints = InMemoryInputCheckpointPort((ClaimAcquired(claim),))
    runtime = ScriptedRuntime()

    with TemporaryDirectory() as directory:
        provider = CodexProvider(cast(AgentRuntime, runtime), cwd_parent=Path(directory))
        try:
            outcome = await run_thread(
                run_id=RunId("run-1"),
                thread_id=ThreadId("thread-1"),
                owner_token=OwnerToken("owner-1"),
                definition=definition,
                checkpoints=checkpoints,
                admission=InMemoryAdmissionPort(),
                sessions=SessionCoordinator(provider, InMemorySessionRefPort()),
                context_source=StaticContextSource(
                    sections("canonical_context", "No prior thread state.")
                ),
                dispatcher=ScriptedToolDispatchPort(()),
                budget_factory=NoToolBudgetFactory(),
            )
        finally:
            await provider.shutdown()

    assert isinstance(outcome, ThreadCompleted)
    conclusion = checkpoints.settlements[0].conclusion
    assert isinstance(conclusion, ConversationConclusion)
    print(conclusion.text)


if __name__ == "__main__":
    asyncio.run(main())
