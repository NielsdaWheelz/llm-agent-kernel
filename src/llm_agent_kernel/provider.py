"""Contained Codex session lifecycle over the public AgentRuntime API."""

from __future__ import annotations

import asyncio
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from llm_tools import FrozenToolPlan, render_prompt
from provider_runtime.agent_runtime import (
    AgentRuntime,
    AgentSession,
    AgentTurn,
    AgentTurnControls,
    CodexCatalogSessionRequest,
    ContentPart,
    JsonSchemaAgentOutput,
    NewSession,
    TextContent,
    TurnRequest,
)
from provider_runtime.types import CancelSignal, TokenUsage

from .definitions import (
    CODEX_NATIVE_OPTIONS,
    CONTAINMENT_POLICY,
    KERNEL_BASE_INSTRUCTION,
    AgentDefinition,
    OwnerPermit,
    OwnerToken,
    ProviderUsage,
    SessionMode,
)
from .protocol import MODEL_STEP_OUTPUT_NAME, provider_wire_schema

if TYPE_CHECKING:
    from .native_contract import NativeDefinition


class ProviderDefect(RuntimeError):
    """The provider boundary violated a kernel invariant."""


class ProviderConfigurationError(ProviderDefect):
    """A definition cannot be represented by the v1 Codex containment request."""


class ProviderContainmentViolation(ProviderDefect):
    """The contained provider emitted native authority activity."""


class ProviderStreamDefect(ProviderDefect):
    """The provider event stream did not have one terminal final event."""


@dataclass(slots=True)
class _Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    turns: int = 0
    complete: bool = True

    def add(self, value: TokenUsage | None) -> None:
        self.turns += 1
        if value is None:
            self.complete = False
        elif self.complete:
            self.input_tokens += value.input_tokens
            self.output_tokens += value.output_tokens

    def value(self) -> ProviderUsage:
        if not self.turns or not self.complete:
            return ProviderUsage()
        return ProviderUsage(
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
        )


@dataclass(frozen=True, slots=True, eq=False)
class ProviderSessionLease:
    """One exclusive acquisition of a live native provider session."""

    session: AgentSession = field(repr=False)
    cwd: Path
    definition_fingerprint: str
    owner_token: OwnerToken | None = None
    _usage: _Usage = field(default_factory=_Usage, repr=False, compare=False)
    _diagnostics: list[str] = field(default_factory=list, repr=False, compare=False)

    @property
    def usage(self) -> ProviderUsage:
        return self._usage.value()

    def record_usage(self, usage: TokenUsage | None) -> None:
        """Record one observed turn's final invocation-local snapshot."""
        self._usage.add(usage)

    @property
    def diagnostics(self) -> tuple[str, ...]:
        return tuple(self._diagnostics)

    def record_diagnostics(self, diagnostics: tuple[str, ...]) -> None:
        self._diagnostics.extend(diagnostics)


class ProviderSessionPort(Protocol):
    """The exact stateful provider lifecycle consumed by the kernel."""

    async def open_isolated(self, definition: AgentDefinition) -> ProviderSessionLease: ...

    def prepare_observed_turn(
        self,
        lease: ProviderSessionLease,
        content: tuple[ContentPart, ...],
        cancellation: CancelSignal,
        *,
        attempt_id: str,
        input_id: str,
        timeout_seconds: float | None = None,
    ) -> AgentTurn: ...

    async def acquire_native(
        self,
        definition: NativeDefinition,
        plan: FrozenToolPlan,
        permit: OwnerPermit,
        previous: ProviderSessionLease | None,
    ) -> ProviderSessionLease: ...

    def prepare_native_turn(
        self,
        lease: ProviderSessionLease,
        content: tuple[ContentPart, ...],
        *,
        attempt_id: str,
        input_id: str,
        controls: AgentTurnControls,
        timeout_seconds: float | None,
    ) -> AgentTurn: ...

    async def accumulated_usage(self, lease: ProviderSessionLease) -> ProviderUsage: ...

    async def discard(self, lease: ProviderSessionLease) -> None: ...

    async def close(self, lease: ProviderSessionLease) -> None: ...


class CodexProvider:
    """Contained native sessions; live reuse requires exact plan and owner."""

    def __init__(
        self,
        runtime: AgentRuntime,
        *,
        cwd_parent: Path | None = None,
        share_cwd_with_group: bool = False,
    ) -> None:
        if cwd_parent is not None and (not cwd_parent.is_absolute() or not cwd_parent.is_dir()):
            raise ValueError("cwd_parent must be an existing absolute directory")
        if share_cwd_with_group and (
            cwd_parent is None or not cwd_parent.stat().st_mode & stat.S_ISGID
        ):
            raise ValueError("a group-shared cwd requires a setgid cwd_parent")
        self._runtime = runtime
        self._cwd_parent = cwd_parent
        self._share_cwd_with_group = share_cwd_with_group
        self._leases: set[ProviderSessionLease] = set()
        self._closed = False
        self._lock = asyncio.Lock()

    async def open_isolated(self, definition: AgentDefinition) -> ProviderSessionLease:
        if definition.session_mode is not SessionMode.isolated:
            raise ProviderConfigurationError("an isolated lease requires isolated session mode")
        async with self._lock:
            self._require_open()
            cwd = self._create_cwd()
            try:
                session = await self._runtime.open_session(self._session_request(definition, cwd))
            except BaseException:
                self._remove_cwd(cwd)
                raise
            return self._lease(session, cwd, definition.fingerprint)

    def prepare_observed_turn(
        self,
        lease: ProviderSessionLease,
        content: tuple[ContentPart, ...],
        cancellation: CancelSignal,
        *,
        attempt_id: str,
        input_id: str,
        timeout_seconds: float | None = None,
    ) -> AgentTurn:
        self._require_lease(lease)
        request = TurnRequest(input=content, timeout_seconds=timeout_seconds)
        turn = self._runtime.prepare_observed_turn(
            lease.session,
            request,
            attempt_id=attempt_id,
            input_id=input_id,
            controls=AgentTurnControls(15.0, 16, 1_048_576),
        )
        if cancellation.is_set():
            turn.revoke()
        return turn

    async def acquire_native(
        self,
        definition: NativeDefinition,
        plan: FrozenToolPlan,
        permit: OwnerPermit,
        previous: ProviderSessionLease | None,
    ) -> ProviderSessionLease:
        from provider_runtime.tool_adapter import ToolPublication, lower_tools

        from .native_contract import NATIVE_BASE_INSTRUCTION
        from .tools import require_native_plan

        require_native_plan(plan, definition.maximum_profile)
        fingerprint = definition.session_fingerprint(plan)
        if previous is not None:
            if (
                previous in self._leases
                and previous.definition_fingerprint == fingerprint
                and previous.owner_token == permit.owner_token
                and self._runtime.session_usable(previous.session)
            ):
                return previous
            await self.discard(previous)
        async with self._lock:
            self._require_open()
            cwd = self._create_cwd()
            provider = definition.provider
            try:
                session = await self._runtime.open_session(
                    CodexCatalogSessionRequest(
                        auth=provider.auth,
                        open=NewSession(),
                        cwd=os.fspath(cwd),
                        policy=provider.policy,
                        model_key=provider.model_key,
                        agent_definition_revision=provider.agent_definition_revision,
                        row_fingerprint=provider.row_fingerprint,
                        reasoning=provider.reasoning,
                        system=(
                            TextContent(NATIVE_BASE_INSTRUCTION),
                            *provider.system,
                            TextContent(render_prompt(definition.role.instructions)),
                        ),
                        developer=provider.developer,
                        additional_dirs=(),
                        mcp_servers=(),
                        output=definition.output,
                        native=provider.native,
                        tools=lower_tools(ToolPublication(plan, ())).tools,
                    )
                )
            except BaseException:
                self._remove_cwd(cwd)
                raise
            return self._lease(session, cwd, fingerprint, permit.owner_token)

    def prepare_native_turn(
        self,
        lease: ProviderSessionLease,
        content: tuple[ContentPart, ...],
        *,
        attempt_id: str,
        input_id: str,
        controls: AgentTurnControls,
        timeout_seconds: float | None,
    ) -> AgentTurn:
        self._require_lease(lease)
        return self._runtime.prepare_turn(
            lease.session,
            TurnRequest(input=content, timeout_seconds=timeout_seconds),
            attempt_id=attempt_id,
            input_id=input_id,
            controls=controls,
        )

    async def accumulated_usage(self, lease: ProviderSessionLease) -> ProviderUsage:
        return lease.usage

    async def discard(self, lease: ProviderSessionLease) -> None:
        async with self._lock:
            if lease not in self._leases:
                return
            self._leases.remove(lease)
        try:
            await self._runtime.close_session(lease.session)
        finally:
            self._remove_cwd(lease.cwd)

    async def close(self, lease: ProviderSessionLease) -> None:
        await self.discard(lease)

    async def shutdown(self) -> None:
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            sessions = tuple(self._leases)
        errors: list[BaseException] = []
        for lease in sessions:
            try:
                await self.discard(lease)
            except BaseException as error:
                errors.append(error)
        if errors:
            raise ProviderDefect("one or more provider sessions failed to close") from errors[0]

    def _lease(
        self,
        session: AgentSession,
        cwd: Path,
        definition_fingerprint: str,
        owner_token: OwnerToken | None = None,
    ) -> ProviderSessionLease:
        lease = ProviderSessionLease(
            session=session,
            cwd=cwd,
            definition_fingerprint=definition_fingerprint,
            owner_token=owner_token,
        )
        self._leases.add(lease)
        return lease

    @staticmethod
    def _session_request(
        definition: AgentDefinition,
        cwd: Path,
    ) -> CodexCatalogSessionRequest:
        provider = definition.provider
        if provider.policy != CONTAINMENT_POLICY or provider.native != CODEX_NATIVE_OPTIONS:
            raise ProviderConfigurationError("definition does not use the v1 containment posture")
        if provider.additional_dirs or provider.mcp_servers or provider.policy.environment:
            raise ProviderConfigurationError("definition exposes forbidden provider resources")
        return CodexCatalogSessionRequest(
            auth=provider.auth,
            open=NewSession(),
            cwd=os.fspath(cwd),
            policy=provider.policy,
            model_key=provider.model_key,
            agent_definition_revision=provider.agent_definition_revision,
            row_fingerprint=provider.row_fingerprint,
            reasoning=provider.reasoning,
            system=(TextContent(KERNEL_BASE_INSTRUCTION), *provider.system),
            developer=provider.developer,
            additional_dirs=(),
            mcp_servers=(),
            output=JsonSchemaAgentOutput(
                name=MODEL_STEP_OUTPUT_NAME,
                schema=provider_wire_schema(definition.output_contract),
            ),
            native=provider.native,
        )

    def _create_cwd(self) -> Path:
        cwd = Path(
            tempfile.mkdtemp(
                prefix="llm-agent-kernel-",
                dir=os.fspath(self._cwd_parent) if self._cwd_parent is not None else None,
            )
        )
        if not cwd.is_absolute() or any(cwd.iterdir()):
            self._remove_cwd(cwd)
            raise ProviderDefect("provider cwd was not empty and absolute")
        if self._share_cwd_with_group:
            parent = self._cwd_parent
            if parent is None or cwd.stat().st_gid != parent.stat().st_gid:
                self._remove_cwd(cwd)
                raise ProviderDefect("provider cwd did not inherit the configured group")
            cwd.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP)
        else:
            cwd.chmod(stat.S_IRUSR | stat.S_IXUSR)
        return cwd

    @staticmethod
    def _remove_cwd(cwd: Path) -> None:
        if not cwd.exists():
            return
        cwd.chmod(stat.S_IRWXU)
        shutil.rmtree(cwd)

    def _require_lease(self, lease: ProviderSessionLease) -> None:
        if lease not in self._leases:
            raise ProviderDefect("provider session lease is not active")

    def _require_open(self) -> None:
        if self._closed:
            raise ProviderDefect("provider adapter has been shut down")


__all__ = [
    "CodexProvider",
    "ProviderConfigurationError",
    "ProviderContainmentViolation",
    "ProviderDefect",
    "ProviderSessionLease",
    "ProviderSessionPort",
    "ProviderStreamDefect",
]
