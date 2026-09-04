from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from inspect import signature
from types import SimpleNamespace
from typing import Any

import pytest
from llm_tools import (
    WEB_READ_SPEC,
    WEB_SEARCH_SPEC,
    Available,
    CapabilityProfile,
    HostTable,
    NoDeclaredError,
    PolicyEpoch,
    ProfileId,
    PromptDocument,
    PromptSection,
    PromptSectionKind,
    PromptSections,
    PromptText,
    ReplayPolicy,
    RunLimits,
    SafeWebReader,
    SchemaDecodeError,
    ToolBinding,
    ToolCatalog,
    ToolEffect,
    ToolFamily,
    ToolGrant,
    ToolId,
    ToolLimits,
    ToolPlan,
    ToolSpec,
    WebSearchProvider,
    WebSearchRequest,
    WebSearchResponse,
    bind_brave_web_search,
    bind_web_read,
    publish_host_table,
    render_prompt,
    validate_tool_input,
    web_family,
)
from provider_runtime.agent_runtime import (
    CredentialRef,
    PermissionPolicy,
    ReasoningSpec,
    TextContent,
)
from pydantic import BaseModel, ConfigDict

from llm_agent_kernel import ToolBudgetFactoryPort
from llm_agent_kernel.coordination import (
    AdmissionRequest,
    AdmissionToken,
    AppendInputs,
)
from llm_agent_kernel.definitions import (
    AgentDefinition,
    AgentRole,
    Checkpoint,
    ClaimId,
    ConversationalOutput,
    DefinitionId,
    DispatchLineage,
    HostInput,
    InputClaim,
    InputId,
    KernelLimits,
    ProviderConfiguration,
    RunId,
    SessionMode,
    StructuredOutput,
    ThreadId,
)
from llm_agent_kernel.kernel import run_one_shot, run_thread


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int


class Success(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: bool


class Result(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str


class OptionalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    note: str | None = None


class OpenResult(BaseModel):
    answer: str


class CompatibleWebSearchProvider:
    async def search(
        self,
        request: WebSearchRequest,
        *,
        attempt_started: Callable[[], None] | None = None,
    ) -> WebSearchResponse:
        raise AssertionError(f"contract canary performed Web I/O: {request!r}, {attempt_started!r}")


class StaticWebResolver:
    async def resolve(self, hostname: str, port: int) -> tuple[str, ...]:
        del hostname, port
        return ("8.8.8.8",)


class MemoryWebWriter:
    def __init__(self) -> None:
        self.requests: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.requests.append(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        return None

    async def wait_closed(self) -> None:
        return None


class MemoryWebConnector:
    def __init__(self, body: bytes, content_type: str) -> None:
        self.body = body
        self.content_type = content_type

    async def connect(
        self,
        address: str,
        port: int,
        *,
        hostname: str,
        tls: bool,
        timeout_seconds: float,
    ) -> Any:
        del port, hostname, tls, timeout_seconds
        reader = asyncio.StreamReader()
        reader.feed_data(
            b"HTTP/1.1 200 OK\r\n"
            + f"Content-Type: {self.content_type}; charset=utf-8\r\n".encode()
            + f"Content-Length: {len(self.body)}\r\n".encode()
            + b"Connection: close\r\n\r\n"
            + self.body
        )
        reader.feed_eof()
        return SimpleNamespace(
            reader=reader,
            writer=MemoryWebWriter(),
            peer_address=address,
        )


async def _must_not_run(value: object, context: object) -> object:
    raise AssertionError(f"pure validation performed dispatch: {value!r}, {context!r}")


def _catalog_and_profile(*, implementation_revision: str = "implementation-v1"):
    spec = ToolSpec(
        id=ToolId("test.count"),
        summary="Count",
        documentation=PromptDocument("Count one value."),
        input_type=Input,
        success_type=Success,
        error_type=NoDeclaredError,
        effect=ToolEffect.Read,
        limits=ToolLimits(1_024, 1_024, 1, 5.0),
    )
    binding = ToolBinding(
        spec=spec,
        execute=Available(_must_not_run),
        replay_policy=ReplayPolicy.ReDispatchable,
        implementation_revision=implementation_revision,
        policy_epoch=PolicyEpoch("v1"),
        policy_inputs={},
    )
    catalog = ToolCatalog.compose((ToolFamily("test", (spec,), (binding,)),))
    profile = CapabilityProfile(
        id=ProfileId("maximum"),
        grants=(ToolGrant(spec.id, None),),
        run_limits=RunLimits(4, 4, 4_096, 4_096, 1, 30.0),
    ).freeze(catalog)
    return catalog, profile, binding


def _sections(text: str) -> PromptSections:
    return PromptSections((PromptSection(PromptSectionKind("context"), (), PromptText(text)),))


def _definition(**provider_changes: object) -> AgentDefinition:
    _, profile, _ = _catalog_and_profile()
    provider_values = {
        "auth": CredentialRef("local_account", "personal"),
        "model": "gpt-5",
        **provider_changes,
    }
    return AgentDefinition(
        definition_id=DefinitionId("assistant"),
        role=AgentRole("assistant", _sections("Help the user.")),
        stable_context=_sections("Stable application context."),
        session_mode=SessionMode.continuing,
        output_contract=ConversationalOutput(),
        maximum_profile=profile,
        provider=ProviderConfiguration(**provider_values),
        session_compatibility_revision="contract-test-v1",
    )


def _claim():
    catalog, profile, _ = _catalog_and_profile()
    plan = ToolPlan(profile.id, HostTable()).freeze(catalog, profile)
    host_input = HostInput(InputId("input-1"), _sections("hello"), datetime.now(UTC))
    return InputClaim(
        ClaimId("claim-1"),
        (host_input,),
        Checkpoint("checkpoint-1"),
        datetime.now(UTC),
        plan,
        1,
    )


def test_dependency_pure_validation_and_host_table_publication() -> None:
    catalog, profile, binding = _catalog_and_profile()
    plan = ToolPlan(profile.id, HostTable()).freeze(catalog, profile)

    assert validate_tool_input(binding, {"count": 2}) == Input(count=2)
    with pytest.raises(SchemaDecodeError):
        validate_tool_input(binding, {"count": "2"})
    assert publish_host_table(plan).kind == PromptSectionKind("host_table")


def test_dependency_rejects_cross_catalog_implementation_substitution() -> None:
    _, profile, _ = _catalog_and_profile(implementation_revision="implementation-v1")
    substituted_catalog, _, _ = _catalog_and_profile(implementation_revision="implementation-v2")

    with pytest.raises(ValueError, match="implementation"):
        ToolPlan(profile.id, HostTable()).freeze(substituted_catalog, profile)


def test_dependency_web_search_operation_deadline_api_is_revisioned() -> None:
    public_parameters = signature(WebSearchProvider.search).parameters
    callback = public_parameters["attempt_started"]
    assert callback.kind.name == "KEYWORD_ONLY"
    assert callback.default is None

    default = bind_brave_web_search(CompatibleWebSearchProvider())
    tightened = bind_brave_web_search(
        CompatibleWebSearchProvider(), operation_deadline_seconds=11.5
    )
    unavailable = web_family().bindings[0]

    assert WEB_SEARCH_SPEC.limits.deadline_seconds == 15.0
    assert (
        WEB_SEARCH_SPEC.tool_contract_revision
        == "c46877ad7f12d672c2717fd0895f5bd95983dd5f6ffb6e6c9c4a2c22c573b78e"
    )
    assert default.implementation_revision == "llm-tools-web-search-v2"
    assert default.policy_epoch == PolicyEpoch("web-search-v2")
    assert (
        default.policy_revision
        == "5717aea83625adff48bf1c870a46eb3086c0f166e6ad2088abe9efbe21445933"
    )
    assert default.policy_inputs == {
        "locale": "US/en",
        "max_results": 10,
        "operation_deadline_seconds": 12.0,
        "safe_search": "moderate",
    }
    assert unavailable.policy_revision == default.policy_revision
    assert tightened.policy_inputs["operation_deadline_seconds"] == 11.5
    assert tightened.policy_revision != default.policy_revision
    with pytest.raises(ValueError, match="operation_deadline_seconds"):
        bind_brave_web_search(CompatibleWebSearchProvider(), operation_deadline_seconds=12.001)


def test_dependency_web_read_revision_refreezes_exact_host_table_plan() -> None:
    available = bind_web_read(SafeWebReader())
    unavailable = web_family().bindings[1]

    assert (
        WEB_READ_SPEC.tool_contract_revision
        == "a5de4258e043dd25f47cad2768ff1f5d9db4b93ac4a90347022d030a916bad1b"
    )
    assert WEB_READ_SPEC.limits.max_attempts == 8
    assert WEB_READ_SPEC.limits.deadline_seconds == 20.0
    assert available.implementation_revision == "llm-tools-web-read-v2"
    assert unavailable.implementation_revision == "llm-tools-web-read-v2"
    assert available.policy_epoch == PolicyEpoch("web-read-v1")
    assert available.policy_inputs == {
        "accepted_media": (
            "application/json",
            "application/xhtml+xml",
            "text/html",
            "text/plain",
        ),
        "mode": "direct",
    }
    assert (
        available.policy_revision
        == "587bfe6151dc8ad6880aea5414edb974fdf159da4148cdd1c9ffa2420dd74084"
    )
    assert unavailable.policy_revision == available.policy_revision

    catalog = ToolCatalog.compose((web_family(read=available),))
    maximum = CapabilityProfile(
        ProfileId("kernel-web-read-v2"),
        (ToolGrant(WEB_READ_SPEC.id, None),),
        RunLimits(1, 8, 24_616, 512 * 1_024, 1, 30.0),
    ).freeze(catalog)
    plan = ToolPlan(maximum.id, HostTable()).freeze(catalog, maximum)
    published = render_prompt(publish_host_table(plan))

    assert maximum.profile_revision == (
        "1c2957e53e23d277e8f58c9d7f3ceecf11dbe6b8a1a2f2be3c185fe91328f7e5"
    )
    assert plan.plan_revision == "7f88eea84fa31631677b7499d468281f5e4e1dcdfa761f50e236246dfabeb749"
    assert '"implementation_revision":"llm-tools-web-read-v2"' in published


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "content_type", "expected_text", "expected_extraction"),
    [
        (
            b"literal &amp; <b>plain</b>",
            "text/plain",
            "literal &amp; <b>plain</b>",
            "plain-text-v2",
        ),
        (
            b"<p>nested &amp;amp; encoded &amp;lt;script&amp;gt;</p>",
            "text/html",
            "nested &amp; encoded &lt;script&gt;",
            "html-visible-text-v2",
        ),
    ],
)
async def test_dependency_web_read_v2_extraction_locators_are_exact(
    body: bytes,
    content_type: str,
    expected_text: str,
    expected_extraction: str,
) -> None:
    result = await SafeWebReader(
        resolver=StaticWebResolver(),
        connector=MemoryWebConnector(body, content_type),
    ).read("http://web-read-canary.test/")

    assert result.value.text == expected_text
    assert json.loads(result.value.evidence.locator)["extraction"] == expected_extraction


def test_entry_points_require_the_exported_plan_aware_budget_factory() -> None:
    assert ToolBudgetFactoryPort.__name__ == "ToolBudgetFactoryPort"
    for entry_point in (run_thread, run_one_shot):
        parameters = signature(entry_point).parameters
        assert "budget_factory" in parameters
        assert "budgets" not in parameters


def test_definition_is_frozen_and_fingerprint_covers_provider_configuration() -> None:
    first = _definition()
    same = _definition()
    changed = _definition(model="gpt-5-high")

    assert first.fingerprint == same.fingerprint
    assert first.fingerprint != changed.fingerprint
    assert len(first.fingerprint) == 64
    with pytest.raises(FrozenInstanceError):
        first.fingerprint = "tampered"  # type: ignore[misc]


def test_structured_wire_compilation_has_a_deterministic_definition_fingerprint() -> None:
    first = replace(
        _definition(),
        output_contract=StructuredOutput("answer", OptionalResult),
    )
    same = replace(
        _definition(),
        output_contract=StructuredOutput("answer", OptionalResult),
    )
    different = replace(
        _definition(),
        output_contract=StructuredOutput("answer", Result),
    )

    assert first.fingerprint == same.fingerprint
    assert first.fingerprint != different.fingerprint


def test_definition_fingerprint_rotates_for_every_configurable_session_scope() -> None:
    first = _definition()
    _, changed_profile, _ = _catalog_and_profile(implementation_revision="implementation-v2")
    variants = (
        replace(first, definition_id=DefinitionId("other")),
        replace(first, role=AgentRole("other", first.role.instructions)),
        replace(first, role=AgentRole(first.role.role_id, _sections("Other role."))),
        replace(first, session_compatibility_revision="contract-test-v2"),
        replace(first, stable_context=_sections("Other stable context.")),
        replace(first, session_mode=SessionMode.isolated),
        replace(first, output_contract=StructuredOutput("answer", Result)),
        replace(first, maximum_profile=changed_profile),
        replace(
            first, provider=replace(first.provider, auth=CredentialRef("local_account", "other"))
        ),
        replace(first, provider=replace(first.provider, model="gpt-5-other")),
        replace(first, provider=replace(first.provider, reasoning=ReasoningSpec("high"))),
        replace(first, provider=replace(first.provider, system=(TextContent("system"),))),
        replace(first, provider=replace(first.provider, developer=(TextContent("developer"),))),
        replace(first, limits=replace(first.limits, max_provider_turns=9)),
    )

    assert all(candidate.fingerprint != first.fingerprint for candidate in variants)
    assert len({candidate.fingerprint for candidate in variants}) == len(variants)


def test_session_compatibility_revision_is_required_and_rotates_the_fingerprint() -> None:
    first = _definition()

    with pytest.raises(ValueError, match="compatibility revision"):
        replace(first, session_compatibility_revision="")
    with pytest.raises(ValueError, match="compatibility revision"):
        replace(first, session_compatibility_revision="   ")

    rotated = replace(first, session_compatibility_revision="contract-test-v2")
    assert rotated.fingerprint != first.fingerprint


def test_provider_configuration_rejects_authority_widening() -> None:
    with pytest.raises(ValueError, match="containment"):
        ProviderConfiguration(
            auth=CredentialRef("local_account", "personal"),
            model="gpt-5",
            policy=PermissionPolicy(
                filesystem="read_only",
                network="disabled",
                approval="deny",
            ),
        )


def test_structured_output_requires_a_closed_object() -> None:
    assert StructuredOutput("answer", Result).schema["additionalProperties"] is False
    with pytest.raises(ValueError, match="closed object"):
        StructuredOutput("answer", OpenResult)


@pytest.mark.parametrize(
    "change",
    [
        {"max_provider_turns": 0},
        {"max_protocol_repairs": -1},
        {"max_no_progress_attempts": 0},
        {"max_cooperative_seconds": float("inf")},
        {"max_provider_input_tokens": 0},
        {"max_provider_output_tokens": 0},
        {"max_new_context_bytes": 0},
    ],
)
def test_kernel_limits_are_finite_and_bounded(change: dict[str, object]) -> None:
    with pytest.raises((TypeError, ValueError)):
        KernelLimits(**change)  # type: ignore[arg-type]


def test_claim_and_append_batches_are_non_empty() -> None:
    claim = _claim()
    with pytest.raises(ValueError, match="non-empty"):
        InputClaim(
            claim.claim_id,
            (),
            claim.through_checkpoint,
            claim.as_of,
            claim.plan,
            claim.attempt_number,
        )
    with pytest.raises(ValueError, match="must not be empty"):
        AppendInputs((), Checkpoint("checkpoint-2"), datetime.now(UTC))


def test_only_an_isolated_admission_may_share_a_parent_slot() -> None:
    parent = AdmissionToken(RunId("root"), "window", "epoch", 8, 100, 100, True)
    with pytest.raises(ValueError, match="thread admission cannot share"):
        AdmissionRequest(
            RunId("child"),
            ThreadId("thread"),
            1,
            1,
            1,
            1,
            parent,
        )


def test_thread_dispatch_lineage_is_complete_and_immutable() -> None:
    lineage = DispatchLineage(
        ClaimId("claim-1"),
        Checkpoint("checkpoint-2"),
        (InputId("input-1"), InputId("input-2")),
        3,
    )

    assert lineage.input_ids == (InputId("input-1"), InputId("input-2"))
    with pytest.raises(FrozenInstanceError):
        lineage.model_step_ordinal = 4  # type: ignore[misc]
