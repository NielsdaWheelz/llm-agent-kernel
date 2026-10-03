"""Temporary sealed recovery proof across current definition changes."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any, cast

import pytest
from llm_tools import CapabilityProfile, ProfileId, ToolCatalog, ToolFamily, ToolId
from provider_runtime.agent_runtime import AgentTerminal, NativeTerminalEvidence
from test_native_integration import Host, Peer, run, setup
from test_native_integration import peer as peer

from llm_agent_kernel import CancellationToken, InputId, NativeDefect


class NoProvider:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"sealed recovery attempted provider I/O: {name}")


@pytest.mark.parametrize("change", ("definition", "maximum", "request", "owner"))
async def test_sealed_recovery_uses_original_evidence_and_current_owner(
    peer: Peer, tmp_path, change: str
) -> None:
    host = Host(tmp_path / "journal.db")
    runtime, provider, lease, definition, request = await setup(peer, host, tmp_path)
    host.release.set()
    try:
        terminal = await asyncio.wait_for(
            run(host, provider, lease, definition, request, CancellationToken()), 2
        )
        assert isinstance(terminal, AgentTerminal)
        assert isinstance(terminal.evidence, NativeTerminalEvidence)
        await provider.shutdown()
        await runtime.close()

        cold = Host(tmp_path / "journal.db")
        cold.request = request
        if change == "definition":
            definition = replace(definition, compatibility_revision="current-host-two")
        elif change == "maximum":
            binding = request.plan.catalog_view.binding(ToolId("test.observe"))
            catalog = ToolCatalog.compose((ToolFamily("test", (binding.spec,), (binding,)),))
            maximum = CapabilityProfile(
                ProfileId("current-no-tools"), (), definition.maximum_profile.run_limits
            ).freeze(catalog)
            definition = replace(definition, maximum_profile=maximum)
        elif change == "request":
            request = replace(request, input_ids=(InputId("altered-input"),))
        else:
            cold.fenced.set()

        if change in ("request", "owner"):
            with pytest.raises(NativeDefect if change == "request" else RuntimeError):
                await run(
                    cold, cast(Any, NoProvider()), None, definition, request, CancellationToken()
                )
        else:
            recovered = await run(
                cold, cast(Any, NoProvider()), None, definition, request, CancellationToken()
            )
            assert recovered == terminal
        assert peer.starts == 1
    finally:
        await provider.shutdown()
        await runtime.close()
