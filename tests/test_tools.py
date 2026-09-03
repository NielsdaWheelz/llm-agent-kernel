from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from llm_tools import (
    Available,
    BudgetState,
    CapabilityProfile,
    EffectId,
    ExecutionContext,
    FrozenToolPlan,
    HandlerSuccess,
    HostTable,
    InvocationPosition,
    Native,
    NoDeclaredError,
    ParsedJson,
    PlanCatalogView,
    PolicyEpoch,
    PositionState,
    Principal,
    ProfileId,
    PromptDocument,
    RecoveryRequired,
    ReplayPolicy,
    Reservation,
    RunLimits,
    Scope,
    Settlement,
    ToolBinding,
    ToolCatalog,
    ToolEffect,
    ToolExecutor,
    ToolFamily,
    ToolGrant,
    ToolId,
    ToolLimits,
    ToolPlan,
    ToolResult,
    ToolSpec,
    render_prompt,
)
from pydantic import BaseModel, ConfigDict

from llm_agent_kernel.definitions import CallToolStep
from llm_agent_kernel.tools import (
    PlanValidationError,
    ToolProposalError,
    publish_host_plan,
    require_host_plan,
    require_read_only_plan,
    validate_tool_call,
)


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str


class Success(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str


class ChangedInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int


TOOL_LIMITS = ToolLimits(1_024, 2_048, 2, 2.0)
RUN_LIMITS = RunLimits(4, 4, 16_384, 16_384, 1, 20.0)


async def _first_handler(value: object, context: object) -> object:
    raise AssertionError(f"validation must not dispatch: {value!r}, {context!r}")


async def _replacement_handler(value: object, context: object) -> object:
    raise AssertionError(f"replacement must not dispatch: {value!r}, {context!r}")


def _binding(
    *,
    effect: ToolEffect = ToolEffect.Read,
    replay_policy: ReplayPolicy = ReplayPolicy.ReDispatchable,
    implementation_revision: str = "test-handler-v1",
    handler: Any = _first_handler,
    input_type: type[BaseModel] = Input,
) -> ToolBinding[Any, Success, NoDeclaredError]:
    spec = ToolSpec(
        id=ToolId("test.inspect"),
        summary="Inspect text",
        documentation=PromptDocument("Inspect one bounded text value."),
        input_type=input_type,
        success_type=Success,
        error_type=NoDeclaredError,
        effect=effect,
        limits=TOOL_LIMITS,
    )
    return ToolBinding(
        spec=spec,
        execute=Available(handler),
        replay_policy=replay_policy,
        implementation_revision=implementation_revision,
        policy_epoch=PolicyEpoch("v1"),
        policy_inputs={},
    )


def _catalog(binding: ToolBinding[Any, Any, Any]) -> ToolCatalog:
    return ToolCatalog.compose((ToolFamily("test", (binding.spec,), (binding,)),))


def _plan(binding: ToolBinding[Any, Any, Any], *, limits: RunLimits = RUN_LIMITS):
    catalog = _catalog(binding)
    profile = CapabilityProfile(
        ProfileId("maximum"),
        (ToolGrant(binding.spec.id, None),),
        limits,
    ).freeze(catalog)
    return ToolPlan(profile.id, HostTable()).freeze(catalog, profile), profile


def test_host_plan_proof_precedes_exact_dependency_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = _binding()
    plan, maximum = _plan(binding)
    publications = 0

    from llm_agent_kernel import tools

    real_publish = tools.publish_host_table

    def counted(candidate: FrozenToolPlan):
        nonlocal publications
        publications += 1
        return real_publish(candidate)

    monkeypatch.setattr(tools, "publish_host_table", counted)
    published = publish_host_plan(plan, maximum)

    assert publications == 1
    assert published.kind == "host_table"
    assert '"implementation_revision":"test-handler-v1"' in render_prompt(published)

    replacement = ToolBinding(
        spec=binding.spec,
        execute=Available(_replacement_handler),
        replay_policy=binding.replay_policy,
        implementation_revision="test-handler-v2",
        policy_epoch=binding.policy_epoch,
        policy_inputs=binding.policy_inputs,
    )
    forged = replace(
        plan,
        catalog_view=PlanCatalogView.from_catalog(_catalog(replacement), (replacement.spec.id,)),
    )
    assert forged.profile.is_tightening_of(maximum)
    assert not forged.is_tightening_of(maximum)
    with pytest.raises(PlanValidationError, match="inconsistent"):
        publish_host_plan(forged, maximum)
    assert publications == 1


def test_cross_catalog_handler_implementation_substitution_fails_freeze_and_proof() -> None:
    authorized = _binding()
    authorized_catalog = _catalog(authorized)
    maximum = CapabilityProfile(
        ProfileId("maximum"),
        (ToolGrant(authorized.spec.id, None),),
        RUN_LIMITS,
    ).freeze(authorized_catalog)
    replacement = ToolBinding(
        spec=authorized.spec,
        execute=Available(_replacement_handler),
        replay_policy=authorized.replay_policy,
        implementation_revision="test-handler-v2",
        policy_epoch=authorized.policy_epoch,
        policy_inputs=authorized.policy_inputs,
    )

    with pytest.raises(ValueError, match="implementation"):
        ToolPlan(maximum.id, HostTable()).freeze(_catalog(replacement), maximum)

    valid = ToolPlan(maximum.id, HostTable()).freeze(authorized_catalog, maximum)
    forged = replace(
        valid,
        catalog_view=PlanCatalogView.from_catalog(_catalog(replacement), (replacement.spec.id,)),
    )
    assert not forged.is_tightening_of(maximum)
    with pytest.raises(PlanValidationError, match="inconsistent"):
        require_host_plan(forged, maximum)


@pytest.mark.parametrize(
    "replacement_kind",
    ["effect", "schema", "replay_policy", "implementation_revision"],
)
def test_cross_catalog_authority_substitution_never_reaches_a_kernel_run(
    replacement_kind: str,
) -> None:
    authorized = _binding()
    authorized_catalog = _catalog(authorized)
    maximum = CapabilityProfile(
        ProfileId("maximum"),
        (ToolGrant(authorized.spec.id, None),),
        RUN_LIMITS,
    ).freeze(authorized_catalog)
    valid = ToolPlan(maximum.id, HostTable()).freeze(authorized_catalog, maximum)
    if replacement_kind == "effect":
        replacement = _binding(effect=ToolEffect.Write)
    elif replacement_kind == "schema":
        replacement = _binding(input_type=ChangedInput)
    else:
        replacement = ToolBinding(
            spec=authorized.spec,
            execute=Available(
                _replacement_handler
                if replacement_kind == "implementation_revision"
                else _first_handler
            ),
            replay_policy=(
                ReplayPolicy.BilledOnce
                if replacement_kind == "replay_policy"
                else authorized.replay_policy
            ),
            implementation_revision=(
                "test-handler-v2"
                if replacement_kind == "implementation_revision"
                else authorized.implementation_revision
            ),
            policy_epoch=authorized.policy_epoch,
            policy_inputs=authorized.policy_inputs,
        )

    with pytest.raises(ValueError):
        ToolPlan(maximum.id, HostTable()).freeze(_catalog(replacement), maximum)
    forged = replace(
        valid,
        catalog_view=PlanCatalogView.from_catalog(_catalog(replacement), (replacement.spec.id,)),
    )
    assert not forged.is_tightening_of(maximum)
    with pytest.raises(PlanValidationError):
        require_host_plan(forged, maximum)


def test_plan_must_be_host_exposed_and_strictly_serial() -> None:
    binding = _binding()
    catalog = _catalog(binding)
    parallel_limits = replace(RUN_LIMITS, max_in_flight=2)
    maximum = CapabilityProfile(
        ProfileId("maximum"),
        (ToolGrant(binding.spec.id, None),),
        parallel_limits,
    ).freeze(catalog)
    parallel = ToolPlan(maximum.id, HostTable()).freeze(catalog, maximum)
    native = ToolPlan(maximum.id, Native()).freeze(catalog, maximum)

    with pytest.raises(PlanValidationError, match="max_in_flight"):
        require_host_plan(parallel, maximum)
    with pytest.raises(PlanValidationError, match="HostTable"):
        require_host_plan(native, maximum)


def test_tool_validation_is_pure_strict_and_uses_the_plan_owned_binding() -> None:
    binding = _binding()
    plan, _maximum = _plan(binding)

    validated = validate_tool_call(
        CallToolStep(ToolId("test.inspect"), {"text": "hello"}),
        plan,
    )

    assert validated.binding is binding
    assert validated.arguments == Input(text="hello")
    with pytest.raises(ToolProposalError):
        validate_tool_call(
            CallToolStep(ToolId("test.inspect"), {"text": 7}),
            plan,
        )


def test_isolated_plan_rejects_write_but_accepts_read() -> None:
    read, _maximum = _plan(_binding())
    write, _maximum_write = _plan(_binding(effect=ToolEffect.Write))

    require_read_only_plan(read)
    with pytest.raises(PlanValidationError, match="Write"):
        require_read_only_plan(write)


class _Budget:
    def __init__(self) -> None:
        self.limits = RUN_LIMITS
        self.remaining_elapsed_seconds = 20.0
        self.reservation: Reservation | None = None
        self.settlement: Settlement | None = None

    async def reserve(
        self,
        position: InvocationPosition,
        reservation: Reservation,
    ) -> bool:
        assert position == InvocationPosition("effect-1")
        if self.reservation is None:
            self.reservation = reservation
        else:
            assert self.reservation == reservation
        return True

    async def settle(
        self,
        position: InvocationPosition,
        settlement: Settlement,
    ) -> None:
        assert position == InvocationPosition("effect-1")
        self.settlement = settlement


class _Recorder:
    """Test-only durable-protocol double; not a production durability claim."""

    durable = True

    def __init__(self) -> None:
        self.occupied: tuple[object, ...] | None = None
        self.reservation: Reservation | None = None
        self.in_flight = False
        self.actual_attempts = 0
        self.dispatches = 0
        self.terminal_result: ToolResult | None = None

    async def occupy(
        self,
        *,
        position: InvocationPosition,
        tool_id: ToolId,
        tool_contract_revision: str,
        policy_revision: str,
        plan_revision: str,
        input_digest: str,
        replay_policy: ReplayPolicy,
    ) -> PositionState:
        invocation = (
            position,
            tool_id,
            tool_contract_revision,
            policy_revision,
            plan_revision,
            input_digest,
            replay_policy,
        )
        if self.occupied is None:
            self.occupied = invocation
        else:
            assert self.occupied == invocation
        return PositionState(
            terminal_result=self.terminal_result,
            uncertain=self.in_flight,
            actual_attempts=self.actual_attempts,
        )

    async def reserve(
        self,
        *,
        position: InvocationPosition,
        budgets: BudgetState,
        reservation: Reservation,
    ) -> bool:
        assert isinstance(budgets, _Budget)
        if self.reservation is None:
            self.reservation = reservation
            return await budgets.reserve(position, reservation)
        assert self.reservation == reservation
        return True

    async def dispatch_started(
        self,
        *,
        position: InvocationPosition,
        replay_policy: ReplayPolicy,
    ) -> PositionState:
        assert position == InvocationPosition("effect-1")
        assert replay_policy is ReplayPolicy.ReDispatchable
        assert not self.in_flight
        self.in_flight = True
        self.dispatches += 1
        return PositionState(None, False, self.actual_attempts)

    async def dispatch_abandoned(
        self,
        *,
        position: InvocationPosition,
        replay_policy: ReplayPolicy,
        actual_attempts: int,
        lease_recovered: bool,
    ) -> None:
        assert position == InvocationPosition("effect-1")
        assert replay_policy is ReplayPolicy.ReDispatchable
        if not lease_recovered:
            raise ValueError("host has not reconciled the abandoned dispatch")
        assert self.in_flight
        self.in_flight = False
        self.actual_attempts += actual_attempts

    async def uncertain(self, *, position: InvocationPosition) -> None:
        raise AssertionError(f"ReDispatchable timeout must not be terminally uncertain: {position}")

    async def terminalize_and_settle(
        self,
        *,
        position: InvocationPosition,
        budgets: BudgetState,
        result: ToolResult,
        settlement: Settlement,
    ) -> ToolResult:
        assert isinstance(budgets, _Budget)
        await budgets.settle(position, settlement)
        self.terminal_result = result
        self.in_flight = False
        return result


class _Cancellation:
    cancelled = False


class _Telemetry:
    def event(self, name: str, attributes: dict[str, object]) -> None:
        raise AssertionError(f"unexpected telemetry: {name}, {attributes!r}")


@pytest.mark.asyncio
async def test_redispatchable_write_timeout_requires_host_reconciliation_before_retry() -> None:
    calls = 0
    seen_attempt_limits: list[int] = []

    async def timeout_then_succeed(
        value: Input,
        context: ExecutionContext,
    ) -> HandlerSuccess[Success]:
        nonlocal calls
        calls += 1
        seen_attempt_limits.append(context.grant.limits.max_attempts)
        if calls == 1:
            raise TimeoutError("external outcome is unknown")
        return HandlerSuccess(Success(text=value.text), actual_attempts=1)

    binding = _binding(
        effect=ToolEffect.Write,
        handler=timeout_then_succeed,
    )
    plan, _maximum = _plan(binding)
    position = InvocationPosition("effect-1")
    recorder = _Recorder()
    budgets = _Budget()
    context = ExecutionContext(
        plan=plan,
        grant=plan.grant(binding.spec.id),
        catalog_view=plan.catalog_view,
        position=position,
        recorder=recorder,
        effect_id=EffectId("effect-1"),
        budgets=budgets,
        principal=Principal("owner"),
        scope=Scope("thread"),
        cancellation=_Cancellation(),
        telemetry=_Telemetry(),
    )
    raw = ParsedJson({"text": "hello"})

    with pytest.raises(RecoveryRequired, match="requires reconciliation") as first:
        await ToolExecutor.execute(binding, raw, context)
    assert isinstance(first.value.__cause__, TimeoutError)
    assert recorder.in_flight is True
    assert recorder.dispatches == calls == 1
    assert budgets.settlement is None

    with pytest.raises(RecoveryRequired, match="uncertain"):
        await ToolExecutor.execute(binding, raw, context)
    assert recorder.dispatches == calls == 1

    with pytest.raises(ValueError, match="not reconciled"):
        await recorder.dispatch_abandoned(
            position=position,
            replay_policy=ReplayPolicy.ReDispatchable,
            actual_attempts=1,
            lease_recovered=False,
        )
    await recorder.dispatch_abandoned(
        position=position,
        replay_policy=ReplayPolicy.ReDispatchable,
        actual_attempts=1,
        lease_recovered=True,
    )

    assert await ToolExecutor.execute(binding, raw, context) == {
        "type": "Success",
        "value": {"text": "hello"},
    }
    assert recorder.dispatches == calls == 2
    assert seen_attempt_limits == [2, 1]
    assert budgets.settlement is not None
    assert budgets.settlement.actual_attempts == 2
