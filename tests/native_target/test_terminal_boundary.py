from __future__ import annotations

import sqlite3
from collections.abc import AsyncGenerator

import pytest

from llm_agent_kernel import CancellationToken
from llm_agent_kernel.generation import (
    GenerationCompleted,
    GenerationTerminal,
    GenerationTurn,
    run_generation,
)


class DurableProduct:
    def __init__(self, *, fail_product: bool = False, fail_cleanup: bool = False) -> None:
        self.db = sqlite3.connect(":memory:")
        self.db.execute("CREATE TABLE terminal (turn INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        self.provider_calls = 0
        self.fail_product = fail_product
        self.fail_cleanup = fail_cleanup

    async def stream(self, turn, *, arm, cancellation) -> AsyncGenerator:
        await arm()
        self.provider_calls += 1
        try:
            yield GenerationTerminal(0, "original-native-terminal")
        finally:
            if self.fail_cleanup:
                raise RuntimeError("secondary cleanup failure")

    async def arm(self, turn) -> None:
        pass

    async def record_terminal(self, turn, terminal) -> None:
        with self.db:
            self.db.execute("INSERT INTO terminal VALUES (?, ?)", (turn.ordinal, terminal.value))

    async def resolve_terminal(self, turn, terminal):
        if self.fail_product:
            raise ValueError("invalid product output")
        return terminal

    async def observe(self, event) -> None:
        pass

    def successor(self, continuation, results):
        raise AssertionError("no successor for final terminal")

    async def execute(self, source_ordinal, call):
        raise AssertionError("no tool for final terminal")

    async def open(self, continuation) -> None:
        raise AssertionError("no continuation for final terminal")

    async def run(self):
        return await run_generation(
            start=GenerationTurn(1, "canonical request"),
            driver=self,
            lifecycle=self,
            tools=self,
            observer=self,
            cancellation=CancellationToken(),
            max_turns=1,
        )


@pytest.mark.asyncio
async def test_native_terminal_is_committed_before_product_validation_failure() -> None:
    case = DurableProduct(fail_product=True)
    with pytest.raises(ValueError, match="invalid product"):
        await case.run()
    assert case.db.execute("SELECT value FROM terminal").fetchall() == [
        ("original-native-terminal",)
    ]
    assert case.provider_calls == 1


@pytest.mark.asyncio
async def test_cleanup_failure_after_native_terminal_cannot_erase_terminal() -> None:
    case = DurableProduct(fail_cleanup=True)
    result = await case.run()
    assert isinstance(result, GenerationCompleted)
    assert result.terminal == "original-native-terminal"
    assert case.db.execute("SELECT value FROM terminal").fetchall() == [
        ("original-native-terminal",)
    ]
    assert case.provider_calls == 1
