"""Temporary controlled-peer integration; no actual model/research claim."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from llm_tools import (
    Available,
    CapabilityProfile,
    ExecutionContext,
    HandlerSuccess,
    Native,
    NoDeclaredError,
    ParsedJson,
    PolicyEpoch,
    Principal,
    ProfileId,
    PromptDocument,
    PromptSection,
    PromptSectionKind,
    PromptSections,
    PromptText,
    ReplayPolicy,
    RunBudgetState,
    RunLimits,
    Scope,
    ToolBinding,
    ToolCatalog,
    ToolEffect,
    ToolExecutor,
    ToolFamily,
    ToolGrant,
    ToolId,
    ToolLimits,
    ToolPlan,
    ToolSpec,
)
from llm_tools.testing import InMemoryPositionRecorder, RecordingTelemetry
from provider_runtime.agent_runtime import (
    AgentControlReceipt,
    AgentRuntime,
    AgentRuntimeConfig,
    AgentTerminal,
    CredentialRef,
    JsonSchemaAgentOutput,
    NativeTerminalEvidence,
    attempt_from_json,
    attempt_to_json,
    terminal_from_json,
    terminal_to_json,
)
from pydantic import BaseModel, ConfigDict
from websockets.asyncio.server import ServerConnection, unix_serve

from llm_agent_kernel import (
    AgentRole,
    AppendInputs,
    CancellationToken,
    Checkpoint,
    CodexProvider,
    DispatchCompleted,
    HostInput,
    InputId,
    InvocationRecord,
    NativeControl,
    NativeDefect,
    NativeDefinition,
    NativeDelivery,
    NativeRecovery,
    NativeRequest,
    NoNewInput,
    OwnerPermit,
    OwnerToken,
    ProviderConfiguration,
    run_native,
)


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str


class Peer:
    def __init__(self, socket: Path) -> None:
        self.socket = socket
        self.starts = 0
        self.responses = []
        self.steering = asyncio.Event()
        self.hold_steer = False
        self.hold_start = False
        self.silent_start = False
        self.duplicate_after_steer = False
        self.record_before_steer_ack = False
        self.release_steer_ack = asyncio.Event()
        self.start_entered = asyncio.Event()
        self.start_request_id = None
        self.connection = None
        self.tool_name = ""
        self.arguments = {"query": "bounded"}

    async def send(self, value) -> None:
        assert self.connection is not None
        await self.connection.send(json.dumps(value))

    async def item(self, method, item) -> None:
        await self.send(
            {"method": method, "params": {"threadId": "thread", "turnId": "turn", "item": item}}
        )

    async def finish(self, status="completed") -> None:
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
                if self.duplicate_after_steer and len(self.responses) < 2:
                    continue
                if self.start_request_id is not None:
                    await self.send(
                        {"id": self.start_request_id, "result": {"turn": {"id": "turn"}}}
                    )
                    self.start_request_id = None
                await self.item(
                    "item/completed",
                    {
                        "id": "call",
                        "type": "dynamicToolCall",
                        "tool": self.tool_name,
                        "arguments": self.arguments,
                        "status": "completed" if request["result"]["success"] else "failed",
                    },
                )
                await self.item(
                    "item/completed",
                    {
                        "id": "answer",
                        "type": "agentMessage",
                        "phase": "final_answer",
                        "text": '{"answer":"done"}',
                    },
                )
                await self.finish()
                continue
            if method == "initialized":
                continue
            if method == "initialize":
                result = {"userAgent": "controlled-test-peer"}
            elif method == "account/read":
                result = {"account": {"type": "chatgpt"}}
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
                self.start_entered.set()
                result = {"turn": {"id": "turn"}}
            elif method == "turn/steer":
                self.steering.set()
                if self.hold_steer:
                    continue
                if self.record_before_steer_ack:
                    await self.item(
                        "item/completed",
                        {
                            "id": "new-input",
                            "type": "userMessage",
                            "clientId": request["params"]["clientUserMessageId"],
                        },
                    )
                    await self.release_steer_ack.wait()
                result = {"turnId": "turn"}
            elif method == "turn/interrupt":
                result = {}
            else:
                raise AssertionError(method)
            if method == "turn/start" and self.hold_start:
                self.start_request_id = request["id"]
            else:
                await self.send({"id": request["id"], "result": result})
            if method == "turn/start":
                if self.silent_start:
                    continue
                await self.item(
                    "item/started",
                    {
                        "id": "call",
                        "type": "dynamicToolCall",
                        "tool": self.tool_name,
                        "arguments": self.arguments,
                    },
                )
                await self.send(
                    {
                        "id": "callback",
                        "method": "item/tool/call",
                        "params": {
                            "threadId": "thread",
                            "turnId": "turn",
                            "callId": "call",
                            "tool": self.tool_name,
                            "arguments": self.arguments,
                        },
                    }
                )
                await self.item(
                    "item/completed",
                    {
                        "id": "progress",
                        "type": "agentMessage",
                        "phase": "commentary",
                        "text": "the bounded observation is running",
                    },
                )
            elif method == "turn/steer":
                if not self.record_before_steer_ack:
                    await self.item(
                        "item/completed",
                        {
                            "id": "new-input",
                            "type": "userMessage",
                            "clientId": request["params"]["clientUserMessageId"],
                        },
                    )
                if self.duplicate_after_steer:
                    await self.send(
                        {
                            "id": "duplicate-callback",
                            "method": "item/tool/call",
                            "params": {
                                "threadId": "thread",
                                "turnId": "turn",
                                "callId": "call",
                                "tool": self.tool_name,
                                "arguments": self.arguments,
                            },
                        }
                    )
            elif method == "turn/interrupt":
                await self.item(
                    "item/completed",
                    {
                        "id": "call",
                        "type": "dynamicToolCall",
                        "tool": self.tool_name,
                        "arguments": {"query": "bounded"},
                        "status": "failed",
                    },
                )
                await self.finish("interrupted")


@pytest.fixture
async def peer() -> AsyncIterator[Peer]:
    with tempfile.TemporaryDirectory(prefix="kernel-native-", dir="/tmp") as directory:
        value = Peer(Path(directory) / "socket")
        async with await unix_serve(value.handle, str(value.socket)):
            yield value


class Host:
    def __init__(self, path: Path) -> None:
        self.db = sqlite3.connect(path)
        self.db.executescript(
            "CREATE TABLE IF NOT EXISTS journal (id TEXT PRIMARY KEY, fingerprint TEXT, definition TEXT, provider_attempt TEXT, terminal TEXT, fenced INTEGER NOT NULL DEFAULT 0); CREATE TABLE IF NOT EXISTS invocation (id TEXT PRIMARY KEY, ordinal INTEGER NOT NULL, reply TEXT); CREATE TABLE IF NOT EXISTS message (id TEXT PRIMARY KEY, text TEXT); CREATE TABLE IF NOT EXISTS delivery (id TEXT PRIMARY KEY, state TEXT); CREATE TABLE IF NOT EXISTS control (id TEXT PRIMARY KEY, operation TEXT, disposition TEXT)"
        )
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.progress = asyncio.Event()
        self.fenced = asyncio.Event()
        self.steered = asyncio.Event()
        self.invocations = {}
        self.results = InMemoryPositionRecorder(durable=False)
        self.executor = ToolExecutor()
        self.calls = 0
        self.append = False
        self.request = None

    async def require_current(self, permit) -> None:
        if self.fenced.is_set():
            raise RuntimeError("stale owner")

    async def recover(self, attempt_id):
        row = self.db.execute(
            "SELECT definition, provider_attempt, terminal, fingerprint FROM journal WHERE id=?",
            (attempt_id,),
        ).fetchone()
        if row is None or row[2] is None:
            return None
        assert self.request is not None
        if self.request.fingerprint != row[3]:
            raise NativeDefect("changed durable request")
        return NativeRecovery(
            self.request,
            row[0],
            attempt_from_json(json.loads(row[1])),
            terminal_from_json(json.loads(row[2])),
        )

    async def arm(self, request, attempt, *, definition_fingerprint, submitted_request) -> None:
        self.request = request
        with self.db:
            self.db.execute(
                "INSERT INTO journal(id,fingerprint,definition,provider_attempt) VALUES (?,?,?,?)",
                (
                    request.attempt_id,
                    request.fingerprint,
                    definition_fingerprint,
                    json.dumps(attempt_to_json(attempt)),
                ),
            )

    async def bind(self, attempt_id, native_turn) -> None:
        pass

    async def record_invocation(self, proposal):
        identity = proposal.call_id
        existing = self.invocations.get(identity)
        if existing is not None:
            return existing
        record = InvocationRecord(identity, len(self.invocations) + 1, proposal, None)
        self.invocations[identity] = record
        with self.db:
            self.db.execute("INSERT INTO invocation VALUES (?,?,NULL)", (identity, record.ordinal))
        return record

    async def record_reply(self, invocation_id, receipt) -> None:
        from dataclasses import replace

        self.invocations[invocation_id] = replace(self.invocations[invocation_id], reply=receipt)
        with self.db:
            self.db.execute(
                "UPDATE invocation SET reply=? WHERE id=?", (receipt.text, invocation_id)
            )

    async def record_delivery(self, delivery: NativeDelivery) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO delivery VALUES (?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state",
                (delivery.delivery_id, delivery.state),
            )
        if delivery.mode == "steer" and delivery.state == "recorded":
            self.steered.set()

    async def record_outcome(self, attempt_id, evidence) -> None:
        from provider_runtime.agent_runtime import AgentTerminal

        if isinstance(evidence, AgentControlReceipt):
            with self.db:
                self.db.execute(
                    "INSERT INTO control VALUES (?,?,?)",
                    (evidence.request_id, evidence.operation, evidence.disposition),
                )
        elif isinstance(evidence, AgentTerminal) and isinstance(
            evidence.evidence, NativeTerminalEvidence
        ):
            with self.db:
                self.db.execute(
                    "UPDATE journal SET terminal=? WHERE id=?",
                    (json.dumps(terminal_to_json(evidence)), attempt_id),
                )

    async def fence(self, attempt_id, reason) -> None:
        with self.db:
            self.db.execute("UPDATE journal SET fenced=1 WHERE id=?", (attempt_id,))
        self.fenced.set()

    async def record(self, attempt_id, message) -> None:
        with self.db:
            self.db.execute("INSERT INTO message VALUES (?,?)", (message.message_id, message.text))
        self.progress.set()

    async def poll(self, request, through_checkpoint):
        if self.append:
            self.append = False
            return AppendInputs(
                (HostInput(InputId("new"), _sections("new task"), datetime.now(UTC)),),
                Checkpoint("two"),
                datetime.now(UTC),
            )
        return NoNewInput()

    def create(self, plan):
        return RunBudgetState(plan.profile.run_limits)

    async def handler(self, value, context):
        self.calls += 1
        self.entered.set()
        await self.release.wait()
        return HandlerSuccess(Output(text=value.query), 1)

    async def dispatch(self, *, binding, validated_input, plan, budgets, cancellation, lineage):
        assert self.db.execute("SELECT COUNT(*) FROM invocation").fetchone()[0] == 1
        result = await self.executor.execute(
            binding,
            ParsedJson(validated_input.model_dump()),
            ExecutionContext(
                plan,
                plan.grant(binding.spec.id),
                plan.catalog_view,
                lineage.position,
                self.results,
                None,
                budgets,
                Principal("owner"),
                Scope("job"),
                cancellation,
                RecordingTelemetry(),
            ),
        )
        return DispatchCompleted(result)


def _sections(text):
    return PromptSections((PromptSection(PromptSectionKind("context"), (), PromptText(text)),))


async def setup(peer, host, tmp_path):
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
        spec, Available(host.handler), ReplayPolicy.ReDispatchable, "one", PolicyEpoch("one"), {}
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
    permit = OwnerPermit("job", OwnerToken("owner"), "job", None)
    request = NativeRequest(
        "attempt",
        permit,
        "job",
        (InputId("input"),),
        _sections("input"),
        _sections("input"),
        plan,
        "reconcile_only",
        None,
        None,
    )
    host.request = request
    provider = CodexProvider(runtime, cwd_parent=tmp_path)
    lease = await provider.acquire_native(definition, plan, permit, None)
    return runtime, provider, lease, definition, request


async def run(host, provider, lease, definition, request, cancellation):
    return await run_native(
        definition=definition,
        request=request,
        provider=provider,
        session=lease,
        owner=host,
        journal=host,
        inputs=host,
        dispatch=host,
        budgets=host,
        messages=host,
        cancellation=cancellation,
    )


async def test_live_transport_and_progress_while_real_executor_waits(peer, tmp_path) -> None:
    host = Host(tmp_path / "journal.db")
    runtime, provider, lease, definition, request = await setup(peer, host, tmp_path)
    try:
        task = asyncio.create_task(
            run(host, provider, lease, definition, request, CancellationToken())
        )
        await asyncio.wait_for(host.entered.wait(), 1)
        await asyncio.wait_for(host.progress.wait(), 1)
        assert (
            host.db.execute("SELECT text FROM message").fetchone()[0]
            == "the bounded observation is running"
        )
        assert not task.done()
        host.release.set()
        terminal = await asyncio.wait_for(task, 2)
        assert isinstance(terminal, AgentTerminal)
        assert isinstance(terminal.evidence, NativeTerminalEvidence)
        assert host.calls == peer.starts == 1
        assert host.db.execute("SELECT reply FROM invocation").fetchone()[0] is not None

        # Own sealed evidence supports local recovery without another provider call.
        class NoProvider:
            def __getattr__(self, name):
                raise AssertionError(f"native recovery attempted provider I/O: {name}")

        cold_host = Host(tmp_path / "journal.db")
        cold_host.request = request
        reopened = await run(
            cold_host, cast(Any, NoProvider()), None, definition, request, CancellationToken()
        )
        assert reopened == terminal
        assert peer.starts == 1
    finally:
        await provider.shutdown()
        await runtime.close()


async def test_known_invalid_callback_has_durable_rejection_and_no_executor_entry(
    peer, tmp_path
) -> None:
    host = Host(tmp_path / "journal.db")
    peer.arguments = {"query": 7}
    runtime, provider, lease, definition, request = await setup(peer, host, tmp_path)
    try:
        terminal = await asyncio.wait_for(
            run(host, provider, lease, definition, request, CancellationToken()), 1
        )
        assert isinstance(terminal, AgentTerminal)
        assert isinstance(terminal.evidence, NativeTerminalEvidence)
        assert host.calls == 0
        text = host.db.execute("SELECT reply FROM invocation").fetchone()[0]
        assert json.loads(text)["code"] == "invalid_arguments"
        assert peer.responses[0]["result"]["success"] is False
    finally:
        await provider.shutdown()
        await runtime.close()


async def test_callback_before_start_rpc_ack_does_not_deadlock(peer, tmp_path) -> None:
    host = Host(tmp_path / "journal.db")
    host.release.set()
    peer.hold_start = True
    runtime, provider, lease, definition, request = await setup(peer, host, tmp_path)
    try:
        terminal = await asyncio.wait_for(
            run(host, provider, lease, definition, request, CancellationToken()), 1
        )
        assert isinstance(terminal, AgentTerminal)
        assert isinstance(terminal.evidence, NativeTerminalEvidence)
        assert host.calls == peer.starts == len(peer.responses) == 1
    finally:
        await provider.shutdown()
        await runtime.close()


async def test_stop_fences_promptly_while_steer_ack_is_unresolved(peer, tmp_path) -> None:
    host = Host(tmp_path / "journal.db")
    peer.hold_steer = True
    runtime, provider, lease, definition, request = await setup(peer, host, tmp_path)
    token = CancellationToken()
    task = asyncio.create_task(run(host, provider, lease, definition, request, token))
    try:
        await asyncio.wait_for(host.entered.wait(), 1)
        host.append = True
        await asyncio.wait_for(peer.steering.wait(), 1)
        token.cancel()
        await asyncio.wait_for(host.fenced.wait(), 0.2)
        terminal = await asyncio.wait_for(task, 1)
        assert isinstance(terminal, AgentTerminal)
        assert terminal.evidence.origin in ("native", "local_stop")
        assert host.calls == 1
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await provider.shutdown()
        await runtime.close()


async def test_stop_fences_promptly_before_submission_ack_or_native_events(peer, tmp_path) -> None:
    host = Host(tmp_path / "journal.db")
    peer.hold_start = peer.silent_start = True
    runtime, provider, lease, definition, request = await setup(peer, host, tmp_path)
    token = CancellationToken()
    task = asyncio.create_task(run(host, provider, lease, definition, request, token))
    try:
        await asyncio.wait_for(peer.start_entered.wait(), 1)
        token.cancel()
        await asyncio.wait_for(host.fenced.wait(), 0.2)
        terminal = await asyncio.wait_for(task, 3)
        assert isinstance(terminal, AgentTerminal)
        assert terminal.evidence.origin == "local_stop"
        assert host.calls == 0
        assert peer.starts == 1
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await provider.shutdown()
        await runtime.close()


async def test_same_callback_after_recorded_steer_reuses_original_reply_and_lineage(
    peer, tmp_path
) -> None:
    host = Host(tmp_path / "journal.db")
    peer.duplicate_after_steer = True
    runtime, provider, lease, definition, request = await setup(peer, host, tmp_path)
    task = asyncio.create_task(run(host, provider, lease, definition, request, CancellationToken()))
    try:
        await asyncio.wait_for(host.entered.wait(), 1)
        host.append = True
        await asyncio.wait_for(host.steered.wait(), 1)
        host.release.set()
        terminal = await asyncio.wait_for(task, 2)
        assert isinstance(terminal, AgentTerminal)
        assert terminal.evidence.origin == "native"
        assert host.calls == 1
        assert len(peer.responses) == 2
        assert peer.responses[0]["result"] == peer.responses[1]["result"]
        assert host.invocations["call"].proposal.input_ids == request.input_ids
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await provider.shutdown()
        await runtime.close()


async def test_input_recording_before_steer_ack_retains_both_independent_facts(
    peer, tmp_path
) -> None:
    host = Host(tmp_path / "journal.db")
    peer.record_before_steer_ack = True
    runtime, provider, lease, definition, request = await setup(peer, host, tmp_path)
    task = asyncio.create_task(run(host, provider, lease, definition, request, CancellationToken()))
    try:
        await asyncio.wait_for(host.entered.wait(), 1)
        host.append = True
        await asyncio.wait_for(host.steered.wait(), 1)
        peer.release_steer_ack.set()
        await asyncio.sleep(0.05)
        assert host.db.execute("SELECT state FROM delivery WHERE state='recorded'").fetchone()
        assert host.db.execute(
            "SELECT disposition FROM control WHERE operation='steer'"
        ).fetchone() == ("accepted",)
        host.release.set()
        terminal = await asyncio.wait_for(task, 2)
        assert isinstance(terminal, AgentTerminal)
        assert terminal.evidence.origin == "native"
        assert host.calls == 1
    finally:
        peer.release_steer_ack.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await provider.shutdown()
        await runtime.close()
