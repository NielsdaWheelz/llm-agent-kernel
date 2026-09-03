"""Contained Codex session lifecycle over the public AgentRuntime API."""

from __future__ import annotations

import asyncio
import os
import shutil
import stat
import tempfile
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from provider_runtime.agent_runtime import (
    AgentEvent,
    AgentNative,
    AgentPermissionRequest,
    AgentRuntime,
    AgentSession,
    AgentSessionRef,
    AgentSessionRequest,
    AgentTerminal,
    AgentText,
    AgentToolUse,
    AgentUsage,
    ContentPart,
    JsonSchemaAgentOutput,
    NewSession,
    ResumeSession,
    SessionMismatch,
    SessionUnavailable,
    TurnNotStarted,
    TurnRequest,
)
from provider_runtime.types import CancelSignal, Present, TokenUsage

from .definitions import (
    CODEX_NATIVE_OPTIONS,
    CONTAINMENT_POLICY,
    AgentDefinition,
    ProviderUsage,
    SessionMode,
)
from .protocol import MODEL_STEP_OUTPUT_NAME, model_step_schema


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
    continuing: bool
    cold_bootstrap: bool
    fallback_used: bool
    _usage: _Usage = field(default_factory=_Usage, repr=False, compare=False)

    @property
    def usage(self) -> ProviderUsage:
        return self._usage.value()


class ProviderSessionPort(Protocol):
    """The exact stateful provider lifecycle consumed by the kernel."""

    async def acquire_continuing(
        self,
        definition: AgentDefinition,
        saved_ref: AgentSessionRef | None,
    ) -> ProviderSessionLease: ...

    async def open_isolated(self, definition: AgentDefinition) -> ProviderSessionLease: ...

    async def run_observed_turn(
        self,
        lease: ProviderSessionLease,
        content: tuple[ContentPart, ...],
        cancellation: CancelSignal,
        *,
        timeout_seconds: float | None = None,
    ) -> AgentTerminal: ...

    async def accumulated_usage(self, lease: ProviderSessionLease) -> ProviderUsage: ...

    async def release(self, lease: ProviderSessionLease) -> None: ...

    async def discard(self, lease: ProviderSessionLease) -> None: ...

    async def close(self, lease: ProviderSessionLease) -> None: ...

    async def discard_reference(
        self,
        definition_fingerprint: str,
        ref: AgentSessionRef,
    ) -> None: ...


@dataclass(slots=True)
class _LiveSession:
    session: AgentSession
    cwd: Path
    definition_fingerprint: str
    continuing: bool
    closed: bool = False


class CodexProvider:
    """Exact v1 AgentRuntime adapter with optional continuing-session caching."""

    def __init__(
        self,
        runtime: AgentRuntime,
        *,
        cwd_parent: Path | None = None,
        cache_continuing: bool = True,
    ) -> None:
        if cwd_parent is not None and (not cwd_parent.is_absolute() or not cwd_parent.is_dir()):
            raise ValueError("cwd_parent must be an existing absolute directory")
        self._runtime = runtime
        self._cwd_parent = cwd_parent
        self._cache_continuing = cache_continuing
        self._leases: dict[ProviderSessionLease, _LiveSession] = {}
        self._cache: dict[tuple[str, AgentSessionRef], _LiveSession] = {}
        self._closed = False
        self._lock = asyncio.Lock()

    async def acquire_continuing(
        self,
        definition: AgentDefinition,
        saved_ref: AgentSessionRef | None,
    ) -> ProviderSessionLease:
        if definition.session_mode is not SessionMode.continuing:
            raise ProviderConfigurationError("a continuing lease requires continuing session mode")
        async with self._lock:
            self._require_open()
            if saved_ref is not None:
                live = self._cache.pop((definition.fingerprint, saved_ref), None)
                if live is not None:
                    return self._lease(live, cold_bootstrap=False, fallback_used=False)
            try:
                live = await self._open(definition, saved_ref, continuing=True)
            except (SessionMismatch, SessionUnavailable):
                if saved_ref is None:
                    raise
                live = await self._open(definition, None, continuing=True)
                return self._lease(live, cold_bootstrap=True, fallback_used=True)
            return self._lease(
                live,
                cold_bootstrap=saved_ref is None,
                fallback_used=False,
            )

    async def open_isolated(self, definition: AgentDefinition) -> ProviderSessionLease:
        if definition.session_mode is not SessionMode.isolated:
            raise ProviderConfigurationError("an isolated lease requires isolated session mode")
        async with self._lock:
            self._require_open()
            live = await self._open(definition, None, continuing=False)
            return self._lease(live, cold_bootstrap=True, fallback_used=False)

    async def run_observed_turn(
        self,
        lease: ProviderSessionLease,
        content: tuple[ContentPart, ...],
        cancellation: CancelSignal,
        *,
        timeout_seconds: float | None = None,
    ) -> AgentTerminal:
        live = self._live(lease)
        request = TurnRequest(input=content, timeout_seconds=timeout_seconds)
        terminal: AgentTerminal | None = None
        observed_usage: TokenUsage | None = None
        try:
            stream: AsyncGenerator[AgentEvent, None] = self._runtime.stream_turn(
                live.session,
                request,
                approvals=None,
                cancel=cancellation,
            )
            try:
                async for event in stream:
                    if terminal is not None:
                        raise ProviderStreamDefect("provider emitted an event after its terminal")
                    if isinstance(event, AgentText | AgentNative):
                        continue
                    if isinstance(event, AgentUsage):
                        observed_usage = event.usage
                        continue
                    if isinstance(event, AgentToolUse | AgentPermissionRequest):
                        raise ProviderContainmentViolation(
                            "provider emitted native tool or permission activity"
                        )
                    if isinstance(event, AgentTerminal):
                        terminal = event
                        if event.session_ref != live.session.ref:
                            raise ProviderStreamDefect(
                                "provider terminal changed the live session reference"
                            )
                        continue
                    raise ProviderStreamDefect("provider emitted an unknown event kind")
            finally:
                await stream.aclose()
        except BaseException as error:
            if not isinstance(error, TurnNotStarted):
                self._record_usage(lease, terminal, observed_usage)
            await self._discard_after_error(lease, error)
            raise

        self._record_usage(lease, terminal, observed_usage)
        if terminal is None:
            error = ProviderStreamDefect("provider stream ended without a terminal")
            await self._discard_after_error(lease, error)
            raise error
        if terminal.status != "succeeded":
            await self.discard(lease)
        return terminal

    async def accumulated_usage(self, lease: ProviderSessionLease) -> ProviderUsage:
        return lease.usage

    async def release(self, lease: ProviderSessionLease) -> None:
        to_close: _LiveSession | None = None
        async with self._lock:
            live = self._leases.pop(lease, None)
            if live is None:
                return
            if not live.continuing or not self._cache_continuing:
                to_close = live
            else:
                key = (live.definition_fingerprint, live.session.ref)
                to_close = self._cache.get(key)
                self._cache[key] = live
        if to_close is not None:
            await self._close_live(to_close)

    async def discard(self, lease: ProviderSessionLease) -> None:
        async with self._lock:
            live = self._leases.pop(lease, None)
        if live is not None:
            await self._close_live(live)

    async def close(self, lease: ProviderSessionLease) -> None:
        await self.discard(lease)

    async def discard_reference(
        self,
        definition_fingerprint: str,
        ref: AgentSessionRef,
    ) -> None:
        async with self._lock:
            live = self._cache.pop((definition_fingerprint, ref), None)
        if live is not None:
            await self._close_live(live)

    async def shutdown(self) -> None:
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            sessions = tuple(
                {
                    id(live): live for live in (*self._leases.values(), *self._cache.values())
                }.values()
            )
            self._leases.clear()
            self._cache.clear()
        errors: list[BaseException] = []
        for live in sessions:
            try:
                await self._close_live(live)
            except BaseException as error:
                errors.append(error)
        if errors:
            raise ProviderDefect("one or more provider sessions failed to close") from errors[0]

    def _lease(
        self,
        live: _LiveSession,
        *,
        cold_bootstrap: bool,
        fallback_used: bool,
    ) -> ProviderSessionLease:
        lease = ProviderSessionLease(
            session=live.session,
            cwd=live.cwd,
            definition_fingerprint=live.definition_fingerprint,
            continuing=live.continuing,
            cold_bootstrap=cold_bootstrap,
            fallback_used=fallback_used,
        )
        self._leases[lease] = live
        return lease

    async def _open(
        self,
        definition: AgentDefinition,
        saved_ref: AgentSessionRef | None,
        *,
        continuing: bool,
    ) -> _LiveSession:
        cwd = self._create_cwd()
        try:
            request = self._session_request(definition, cwd, saved_ref)
            session = await self._runtime.open_session(request)
            return _LiveSession(
                session=session,
                cwd=cwd,
                definition_fingerprint=definition.fingerprint,
                continuing=continuing,
            )
        except BaseException:
            self._remove_cwd(cwd)
            raise

    @staticmethod
    def _session_request(
        definition: AgentDefinition,
        cwd: Path,
        saved_ref: AgentSessionRef | None,
    ) -> AgentSessionRequest:
        provider = definition.provider
        if provider.policy != CONTAINMENT_POLICY or provider.native != CODEX_NATIVE_OPTIONS:
            raise ProviderConfigurationError("definition does not use the v1 containment posture")
        if provider.additional_dirs or provider.mcp_servers or provider.policy.environment:
            raise ProviderConfigurationError("definition exposes forbidden provider resources")
        return AgentSessionRequest(
            backend="codex",
            transport="sdk",
            auth=provider.auth,
            open=NewSession() if saved_ref is None else ResumeSession(saved_ref),
            cwd=os.fspath(cwd),
            policy=provider.policy,
            model=provider.model,
            reasoning=provider.reasoning,
            system=provider.system,
            developer=provider.developer,
            additional_dirs=(),
            mcp_servers=(),
            output=JsonSchemaAgentOutput(
                name=MODEL_STEP_OUTPUT_NAME,
                schema=model_step_schema(definition.output_contract),
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
            raise ProviderDefect("private provider cwd was not empty and absolute")
        cwd.chmod(stat.S_IRUSR | stat.S_IXUSR)
        return cwd

    @staticmethod
    def _remove_cwd(cwd: Path) -> None:
        if not cwd.exists():
            return
        cwd.chmod(stat.S_IRWXU)
        shutil.rmtree(cwd)

    async def _close_live(self, live: _LiveSession) -> None:
        if live.closed:
            return
        live.closed = True
        try:
            await self._runtime.close_session(live.session)
        finally:
            self._remove_cwd(live.cwd)

    def _live(self, lease: ProviderSessionLease) -> _LiveSession:
        live = self._leases.get(lease)
        if live is None or live.closed:
            raise ProviderDefect("provider session lease is not active")
        return live

    @staticmethod
    def _record_usage(
        lease: ProviderSessionLease,
        terminal: AgentTerminal | None,
        observed: TokenUsage | None,
    ) -> None:
        usage = observed
        if terminal is not None and isinstance(terminal.usage, Present):
            usage = terminal.usage.value
        lease._usage.add(usage)

    async def _discard_after_error(
        self,
        lease: ProviderSessionLease,
        error: BaseException,
    ) -> None:
        try:
            await self.discard(lease)
        except BaseException as cleanup_error:
            if isinstance(error, ProviderContainmentViolation):
                raise ProviderContainmentViolation(
                    "provider emitted native authority activity and session cleanup failed"
                ) from cleanup_error
            raise ProviderDefect(
                "provider session cleanup failed after turn error"
            ) from cleanup_error

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
