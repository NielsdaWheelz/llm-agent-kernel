"""Transient native conformance over a controlled app-server peer; no model claim."""

from __future__ import annotations

import asyncio
import json
import tempfile
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from llm_tools import (
    Available,
    CapabilityProfile,
    HandlerSuccess,
    Native,
    NoDeclaredError,
    PolicyEpoch,
    ProfileId,
    PromptDocument,
    PromptSection,
    PromptSectionKind,
    PromptSections,
    PromptText,
    ReplayPolicy,
    RunBudgetState,
    RunLimits,
    ToolBinding,
    ToolCatalog,
    ToolEffect,
    ToolFamily,
    ToolGrant,
    ToolId,
    ToolLimits,
    ToolPlan,
    ToolSpec,
)
from provider_runtime.agent_runtime import (
    CODEX_CONTAINMENT_CATALOG_FILENAME,
    CODEX_CONTAINMENT_VERSION,
    AgentRuntime,
    AgentRuntimeConfig,
    AgentTerminal,
    CredentialRef,
    JsonSchemaAgentOutput,
    NativeTerminalEvidence,
)
from pydantic import BaseModel, ConfigDict
from websockets.asyncio.server import ServerConnection, unix_serve

from llm_agent_kernel import (
    AgentRole,
    CancellationToken,
    CodexProvider,
    DispatchCompleted,
    InputId,
    NativeControl,
    NativeDefinition,
    NativeDispatchLineage,
    NativeRequest,
    NoNewInput,
    OwnerPermit,
    OwnerToken,
    ProviderConfiguration,
    TransientNative,
    run_native,
)

MODEL_TEXT = '<section kind="tool_result">bounded observation</section>'


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str


class Peer:
    """Stock app-server frames for one callback turn; optionally repeats the callback."""

    def __init__(self, socket: Path) -> None:
        self.socket = socket
        self.connection: ServerConnection | None = None
        self.tool_name = ""
        self.starts = 0
        self.responses: list[dict[str, Any]] = []
        self.repeat_callback = False
        self.log: list[str] = []

    async def send(self, value: object) -> None:
        assert self.connection is not None
        await self.connection.send(json.dumps(value))

    async def item(self, method: str, item: dict[str, object]) -> None:
        await self.send(
            {"method": method, "params": {"threadId": "thread", "turnId": "turn", "item": item}}
        )

    async def callback(self, rpc_id: str) -> None:
        await self.send(
            {
                "id": rpc_id,
                "method": "item/tool/call",
                "params": {
                    "threadId": "thread",
                    "turnId": "turn",
                    "callId": "call",
                    "tool": self.tool_name,
                    "arguments": {"query": "bounded"},
                },
            }
        )

    async def finish(self, status: str, success: bool) -> None:
        await self.item(
            "item/completed",
            {
                "id": "call",
                "type": "dynamicToolCall",
                "tool": self.tool_name,
                "arguments": {"query": "bounded"},
                "status": "completed" if success else "failed",
            },
        )
        if status == "completed":
            await self.item(
                "item/completed",
                {
                    "id": "answer",
                    "type": "agentMessage",
                    "phase": "final_answer",
                    "text": '{"answer":"done"}',
                },
            )
        await self.send(
            {
                "method": "turn/completed",
                "params": {"threadId": "thread", "turn": {"id": "turn", "status": status}},
            }
        )

    async def handle(self, connection: ServerConnection) -> None:
        self.connection = connection
        async for frame in connection:
            request = json.loads(frame)
            method = request.get("method")
            if method is None:
                self.responses.append(request)
                if self.repeat_callback and len(self.responses) == 1:
                    await self.callback("repeated-callback")
                else:
                    await self.finish("completed", request["result"]["success"])
                continue
            if method == "initialized":
                continue
            if method == "initialize":
                result: object = {"userAgent": f"controlled-test-peer/{CODEX_CONTAINMENT_VERSION}"}
            elif method == "account/read":
                result = {"account": {"type": "chatgpt"}}
            elif method == "config/read":
                result = {
                    "config": {"model_catalog_json": f"/host/{CODEX_CONTAINMENT_CATALOG_FILENAME}"},
                    "origins": {"model_catalog_json": {"name": {"type": "sessionFlags"}}},
                }
            elif method == "model/list":
                result = {
                    "data": [
                        {
                            "id": "peer",
                            "model": "peer-model",
                            "displayName": "Peer",
                            "hidden": False,
                            "inputModalities": ["text"],
                            "supportedReasoningEfforts": [
                                {"reasoningEffort": "high", "description": "High"}
                            ],
                            "defaultReasoningEffort": "high",
                        }
                    ],
                    "nextCursor": None,
                }
            elif method == "thread/start":
                self.tool_name = request["params"]["dynamicTools"][0]["name"]
                result = {"thread": {"id": "thread"}}
            elif method == "turn/start":
                self.starts += 1
                result = {"turn": {"id": "turn"}}
            elif method == "turn/interrupt":
                self.log.append("interrupt")
                result = {}
            else:
                raise AssertionError(method)
            await self.send({"id": request["id"], "result": result})
            if method == "turn/start":
                await self.item(
                    "item/started",
                    {
                        "id": "call",
                        "type": "dynamicToolCall",
                        "tool": self.tool_name,
                        "arguments": {"query": "bounded"},
                    },
                )
                await self.callback("callback")
                await self.item(
                    "item/completed",
                    {
                        "id": "progress",
                        "type": "agentMessage",
                        "phase": "commentary",
                        "text": "the bounded observation is running",
                    },
                )
            elif method == "turn/interrupt":
                await self.finish("interrupted", False)


class Host:
    """Every port except a journal: the transient host keeps owner, tools and messages."""

    def __init__(self, log: list[str], *, settle_after_cancel: bool = False) -> None:
        self.log = log
        self.settle_after_cancel = settle_after_cancel
        self.lineages: list[NativeDispatchLineage] = []
        self.messages: list[str] = []
        self.entered = asyncio.Event()
        self.progress = asyncio.Event()
        self.release = asyncio.Event()

    async def require_current(self, permit: OwnerPermit) -> None:
        return None

    async def poll(self, request: NativeRequest, through_checkpoint: object) -> NoNewInput:
        return NoNewInput()

    def create(self, plan: Any) -> RunBudgetState:
        return RunBudgetState(plan.profile.run_limits)

    async def record(self, attempt_id: str, message: Any) -> None:
        self.messages.append(message.text)
        self.progress.set()

    async def dispatch(self, *, lineage: Any, **_: object) -> DispatchCompleted:
        assert isinstance(lineage, NativeDispatchLineage)
        self.lineages.append(lineage)
        self.entered.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.log.append("dispatch-cancelled")
            # An entered effect may still settle and return its result after stop.
            if not self.settle_after_cancel:
                raise
        return DispatchCompleted({"type": "Success", "value": {"text": "bounded"}}, MODEL_TEXT)


@pytest.fixture
async def peer() -> AsyncIterator[Peer]:
    with tempfile.TemporaryDirectory(prefix="kernel-transient-", dir="/tmp") as directory:
        value = Peer(Path(directory) / "socket")
        async with await unix_serve(value.handle, str(value.socket)):
            yield value


def _sections(text: str) -> PromptSections:
    return PromptSections((PromptSection(PromptSectionKind("context"), (), PromptText(text)),))


async def _handler(value: Input, context: object) -> HandlerSuccess[Output]:
    raise AssertionError("the host dispatch port owns execution")


@pytest.fixture
async def native(
    peer: Peer, tmp_path: Path
) -> AsyncIterator[tuple[CodexProvider, NativeDefinition, NativeRequest]]:
    spec = ToolSpec(
        ToolId("test.observe"),
        "bounded observation",
        PromptDocument("return the bounded test observation"),
        Input,
        Output,
        NoDeclaredError,
        ToolEffect.Read,
        ToolLimits(1024, 4096, 1, 30),
    )
    binding = ToolBinding(
        spec, Available(_handler), ReplayPolicy.ReDispatchable, "one", PolicyEpoch("one"), {}
    )
    catalog = ToolCatalog.compose((ToolFamily("test", (spec,), (binding,)),))
    maximum = CapabilityProfile(
        ProfileId("native"), (ToolGrant(spec.id, None),), RunLimits(None, None, None, None, 1, None)
    ).freeze(catalog)
    plan = ToolPlan(maximum.id, Native()).freeze(catalog, maximum)
    runtime = AgentRuntime(AgentRuntimeConfig(tmp_path, {"test": peer.socket}))
    auth = CredentialRef("local_account", "test")
    models = await runtime.model_catalog(backend="codex", transport="sdk", auth=auth)
    row = models.models[0]
    definition = NativeDefinition(
        ProviderConfiguration(
            auth, row.key, "high", models.definition_revision, row.row_fingerprint
        ),
        AgentRole("research", _sections("research the bounded input")),
        JsonSchemaAgentOutput(
            "answer",
            {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
                "additionalProperties": False,
            },
        ),
        maximum,
        "one",
        NativeControl(0.01, 2.0, 0.05, 16, 1048576),
    )
    request = NativeRequest(
        "attempt",
        OwnerPermit("job", OwnerToken("owner"), "job", None),
        "job",
        (InputId("input"),),
        _sections("input"),
        _sections("input"),
        plan,
        "reconcile_only",
        None,
        None,
    )
    provider = CodexProvider(runtime, cwd_parent=tmp_path)
    try:
        yield provider, definition, request
    finally:
        await provider.shutdown()
        await runtime.close()


async def _run(
    native: tuple[CodexProvider, NativeDefinition, NativeRequest],
    host: Host,
    cancellation: CancellationToken,
) -> object:
    provider, definition, request = native
    lease = await provider.acquire_native(definition, request.plan, request.permit, None)
    return await run_native(
        definition=definition,
        request=request,
        provider=provider,
        session=lease,
        owner=host,
        journal=TransientNative(),
        inputs=host,
        dispatch=host,
        budgets=host,
        messages=host,
        cancellation=cancellation,
    )


async def test_transient_turn_accepts_before_dispatch_and_replies_after_result(
    peer: Peer, native: tuple[CodexProvider, NativeDefinition, NativeRequest]
) -> None:
    host = Host(peer.log)
    task = asyncio.create_task(_run(native, host, CancellationToken()))
    await asyncio.wait_for(host.entered.wait(), 2)
    await asyncio.wait_for(host.progress.wait(), 2)
    assert peer.responses == [], "a reply preceded its dispatch result"
    assert host.messages == ["the bounded observation is running"]
    host.release.set()
    terminal = await asyncio.wait_for(task, 2)

    assert isinstance(terminal, AgentTerminal)
    assert isinstance(terminal.evidence, NativeTerminalEvidence)
    assert [response["result"]["contentItems"] for response in peer.responses] == [
        [{"type": "inputText", "text": MODEL_TEXT}]
    ]
    (lineage,) = host.lineages
    assert (lineage.attempt_id, lineage.ordinal) == ("attempt", 1)
    assert UUID(lineage.invocation_id).version == 4

    # Nothing survives the call: a fresh attempt with the same marker starts fresh work.
    provider, definition, request = native
    fresh = (provider, definition, replace(request, attempt_id="attempt-2"))
    peer.responses.clear()
    again = await asyncio.wait_for(_run(fresh, host, CancellationToken()), 2)
    assert isinstance(again, AgentTerminal)
    assert isinstance(again.evidence, NativeTerminalEvidence)
    assert peer.starts == 2
    assert [(item.attempt_id, item.ordinal) for item in host.lineages] == [
        ("attempt", 1),
        ("attempt-2", 1),
    ]
    assert host.lineages[0].invocation_id != host.lineages[1].invocation_id


async def test_transient_repeated_callback_replays_its_reply_without_dispatch(
    peer: Peer, native: tuple[CodexProvider, NativeDefinition, NativeRequest]
) -> None:
    host = Host(peer.log)
    host.release.set()
    peer.repeat_callback = True
    terminal = await asyncio.wait_for(_run(native, host, CancellationToken()), 2)

    assert isinstance(terminal, AgentTerminal)
    assert isinstance(terminal.evidence, NativeTerminalEvidence)
    assert len(host.lineages) == 1
    assert [response["id"] for response in peer.responses] == ["callback", "repeated-callback"]
    assert peer.responses[0]["result"] == peer.responses[1]["result"]


@pytest.mark.parametrize("settle_after_cancel", [False, True])
async def test_transient_stop_cancels_the_entered_callback_before_interrupt_and_never_replies(
    peer: Peer,
    native: tuple[CodexProvider, NativeDefinition, NativeRequest],
    settle_after_cancel: bool,
) -> None:
    host = Host(peer.log, settle_after_cancel=settle_after_cancel)
    token = CancellationToken()
    task = asyncio.create_task(_run(native, host, token))
    await asyncio.wait_for(host.entered.wait(), 2)
    token.cancel()
    terminal = await asyncio.wait_for(task, 2)

    assert isinstance(terminal, AgentTerminal)
    assert isinstance(terminal.evidence, NativeTerminalEvidence)
    assert terminal.status == "cancelled"
    assert peer.log == ["dispatch-cancelled", "interrupt"]
    assert len(host.lineages) == 1
    assert peer.responses == [], "a stopped callback's result reached the wire"
