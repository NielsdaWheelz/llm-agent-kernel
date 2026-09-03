"""Cooperative cancellation shared by provider and tool boundaries."""

from __future__ import annotations

import asyncio


class CancellationToken:
    """One process-local cooperative cancellation signal."""

    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = asyncio.Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def is_set(self) -> bool:
        return self._event.is_set()

    async def wait(self) -> bool:
        return await self._event.wait()

    def cancel(self) -> None:
        self._event.set()


__all__ = ["CancellationToken"]
