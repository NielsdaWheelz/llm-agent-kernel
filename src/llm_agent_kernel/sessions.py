"""Generation-checked choreography for disposable continuing sessions."""

from __future__ import annotations

from dataclasses import dataclass, replace

from provider_runtime.agent_runtime import (
    AgentSessionRef,
    AgentTerminal,
    ContentPart,
    SessionMismatch,
    SessionUnavailable,
)
from provider_runtime.types import CancelSignal

from .coordination import (
    DiscardedSessionRef,
    SessionRefPort,
    SessionRefStateDefect,
    StaleSessionRef,
    StoredSessionRef,
)
from .definitions import AgentDefinition, ProviderUsage, SessionMode, ThreadId
from .provider import ProviderSessionLease, ProviderSessionPort


class StaleSessionReference(SessionRefStateDefect):
    """Another owner changed session-reference state at a CAS boundary."""


class ColdBootstrapUnavailable(SessionRefStateDefect):
    """A continuing run is not eligible for another cold bootstrap."""


@dataclass(frozen=True, slots=True)
class ContinuingSessionState:
    """One thread run's live lease and next expected reference generation."""

    thread_id: ThreadId
    definition: AgentDefinition
    lease: ProviderSessionLease
    expected_generation: int | None
    stored_ref: AgentSessionRef | None
    cold_bootstrap: bool
    fallback_available: bool


class SessionCoordinator:
    """Keep disposable provider state aligned with generation-CAS host state."""

    def __init__(self, provider: ProviderSessionPort, references: SessionRefPort) -> None:
        self._provider = provider
        self._references = references

    async def acquire_continuing(
        self,
        thread_id: ThreadId,
        definition: AgentDefinition,
        *,
        recovering: bool = False,
    ) -> ContinuingSessionState:
        if definition.session_mode is not SessionMode.continuing:
            raise TypeError("continuing session coordination requires continuing mode")
        stored = await self._references.load(thread_id, definition.fingerprint)
        if stored is not None and not isinstance(stored, StoredSessionRef):
            raise SessionRefStateDefect("session reference load returned an unknown result")
        expected_generation = stored.generation if stored is not None else None
        saved_ref = stored.ref if stored is not None else None

        if recovering and stored is not None:
            try:
                result = await self._references.discard(
                    thread_id,
                    definition.fingerprint,
                    stored.generation,
                )
            except BaseException:
                await self._provider.discard_reference(definition.fingerprint, stored.ref)
                raise
            if isinstance(result, StaleSessionRef):
                await self._provider.discard_reference(definition.fingerprint, stored.ref)
                raise StaleSessionReference(
                    "session reference changed while recovery discarded speculative history"
                )
            if not isinstance(result, DiscardedSessionRef):
                await self._provider.discard_reference(definition.fingerprint, stored.ref)
                raise SessionRefStateDefect("session reference discard returned an unknown result")
            await self._provider.discard_reference(definition.fingerprint, stored.ref)
            expected_generation = None
            saved_ref = None

        lease = await self._provider.acquire_continuing(definition, saved_ref)
        return ContinuingSessionState(
            thread_id=thread_id,
            definition=definition,
            lease=lease,
            expected_generation=expected_generation,
            stored_ref=saved_ref,
            cold_bootstrap=lease.cold_bootstrap,
            fallback_available=not lease.cold_bootstrap and not lease.fallback_used,
        )

    async def store_terminal_ref(
        self,
        state: ContinuingSessionState,
        terminal: AgentTerminal,
    ) -> ContinuingSessionState:
        if terminal.status != "succeeded":
            raise SessionRefStateDefect("only a successful provider terminal advances its ref")
        if terminal.session_ref != state.lease.session.ref:
            await self._provider.discard(state.lease)
            raise SessionRefStateDefect("provider terminal does not belong to the live session")
        try:
            stored = await self._references.compare_and_set(
                state.thread_id,
                state.definition.fingerprint,
                state.expected_generation,
                terminal.session_ref,
            )
        except BaseException:
            await self._provider.discard(state.lease)
            raise
        if isinstance(stored, StaleSessionRef):
            await self._discard_for_stale(state)
            raise StaleSessionReference("session reference generation is stale")
        if not isinstance(stored, StoredSessionRef):
            await self._provider.discard(state.lease)
            raise SessionRefStateDefect("session reference CAS returned an unknown result")
        if stored.ref != terminal.session_ref:
            await self._provider.discard(state.lease)
            raise SessionRefStateDefect("session reference store returned a different ref")
        expected_generation = (
            1 if state.expected_generation is None else state.expected_generation + 1
        )
        if stored.generation != expected_generation:
            await self._provider.discard(state.lease)
            raise SessionRefStateDefect("session reference store did not advance one generation")
        return replace(
            state,
            expected_generation=stored.generation,
            stored_ref=stored.ref,
            fallback_available=False,
        )

    async def run_observed_turn(
        self,
        state: ContinuingSessionState,
        content: tuple[ContentPart, ...],
        cancellation: CancelSignal,
        *,
        timeout_seconds: float | None = None,
    ) -> AgentTerminal:
        return await self._provider.run_observed_turn(
            state.lease,
            content,
            cancellation,
            timeout_seconds=timeout_seconds,
        )

    async def accumulated_usage(self, state: ContinuingSessionState) -> ProviderUsage:
        return await self._provider.accumulated_usage(state.lease)

    async def cold_fallback(
        self,
        state: ContinuingSessionState,
        error: SessionMismatch | SessionUnavailable,
    ) -> ContinuingSessionState:
        if not isinstance(error, SessionMismatch | SessionUnavailable):
            raise TypeError("cold fallback requires a resume incompatibility")
        if not state.fallback_available:
            raise ColdBootstrapUnavailable("the one safe cold bootstrap is not available")

        if state.expected_generation is not None:
            try:
                result = await self._references.discard(
                    state.thread_id,
                    state.definition.fingerprint,
                    state.expected_generation,
                )
            except BaseException:
                await self._provider.discard(state.lease)
                raise
            if isinstance(result, StaleSessionRef):
                await self._discard_for_stale(state)
                raise StaleSessionReference(
                    "session reference changed while preparing a cold bootstrap"
                )
            if not isinstance(result, DiscardedSessionRef):
                await self._provider.discard(state.lease)
                raise SessionRefStateDefect("session reference discard returned an unknown result")
        await self._provider.discard(state.lease)
        lease = await self._provider.acquire_continuing(state.definition, None)
        return replace(
            state,
            lease=lease,
            expected_generation=None,
            stored_ref=None,
            cold_bootstrap=True,
            fallback_available=False,
        )

    async def discard_before_replay(self, state: ContinuingSessionState) -> None:
        """Discard every ref that may name speculative provider history."""

        if state.expected_generation is not None:
            try:
                result = await self._references.discard(
                    state.thread_id,
                    state.definition.fingerprint,
                    state.expected_generation,
                )
            except BaseException:
                await self._provider.discard(state.lease)
                raise
            if isinstance(result, StaleSessionRef):
                await self._discard_for_stale(state)
                raise StaleSessionReference(
                    "session reference changed while discarding speculative history"
                )
            if not isinstance(result, DiscardedSessionRef):
                await self._provider.discard(state.lease)
                raise SessionRefStateDefect("session reference discard returned an unknown result")
        await self._provider.discard(state.lease)

    async def release(self, state: ContinuingSessionState) -> None:
        if state.stored_ref == state.lease.session.ref:
            await self._provider.release(state.lease)
        else:
            await self._provider.discard(state.lease)

    async def discard(self, state: ContinuingSessionState) -> None:
        await self._provider.discard(state.lease)

    async def _discard_for_stale(self, state: ContinuingSessionState) -> None:
        try:
            await self._provider.discard(state.lease)
        except BaseException as error:
            raise StaleSessionReference(
                "session reference is stale and its live session failed to close"
            ) from error


__all__ = [
    "ColdBootstrapUnavailable",
    "ContinuingSessionState",
    "SessionCoordinator",
    "StaleSessionReference",
]
