from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from adapters_v1 import (
    AdapterCapabilities,
    AdapterHealth,
    ArtifactRef,
    AttemptInput,
    HarnessAdapter,
    PreparedAttempt,
    ResultBundle,
)
from factors_v1 import (
    FactorAdapterError,
    FactorExecutionReport,
    FactorizedHarnessAdapter,
    FactorizedRecipeRouterAdapter,
    FactorRuntimeSession,
    RecoveryObservation,
    compile_recipe,
    enumerate_flagship_recipes,
)
from factors_v1.memory import append_memory, new_episode_memory
from factors_v1.models import (
    EvidencePointer,
    FailureEvent,
    FinalizationCandidate,
    MemoryItem,
    RecoveryDecision,
    RecoveryPolicy,
    TreatmentBudget,
    VerificationArtifact,
    VerificationCheck,
)
from factors_v1.planning import create_plan, transition_plan_step
from protocol_v1.canonical import sha256, sha256_bytes
from protocol_v1.models import (
    AttemptEnvelope,
    BudgetSpec,
    ExecutionProvenance,
    HarnessSpec,
    ScenarioSpec,
    TraceEvent,
)

HASH = "a" * 64
NOW = datetime.now(UTC)


def evidence(source_id: str = "source-one") -> EvidencePointer:
    return EvidencePointer(source_id=source_id, uri=f"fixture://{source_id}", content_hash=HASH)


def attempt(number: int, assignment: dict[str, bool]) -> AttemptInput:
    envelope = AttemptEnvelope(
        attempt_id=f"attempt-{number}", episode_id=f"episode-{number}", ordinal=1,
        provider_model="fixture-model", provider="fixture", harness_id="harness-one",
        factor_assignments=assignment,
        budget=BudgetSpec(max_attempts=1, max_cost_usd=1, max_latency_seconds=5, max_tokens=100, max_tool_calls=0, max_context_tokens=100),
        provenance=ExecutionProvenance(
            code_revision="fixture", code_hash=HASH, runtime_image="fixture", runtime_image_hash=HASH,
            environment_hash=HASH, prompt_hash=HASH, context_hash=HASH, tool_hash=HASH,
            source_refs=({"source_uri": "fixture://source", "content_hash": HASH},), captured_at=NOW,
        ),
        request_hash=HASH, status="queued", queued_at=NOW,
    )
    return AttemptInput.bind(ScenarioSpec(scenario_id=f"scenario-{number}", title="Synthetic", task_family="fixture", prompt="Synthetic fixture."), envelope)


def harness(capabilities: dict[str, bool] | None = None) -> HarnessSpec:
    return HarnessSpec(
        harness_id="harness-one", version="1", adapter="recorded", adapter_identity="memory-one", adapter_digest=HASH,
        timeout_seconds=5, capabilities=capabilities or {"state": True, "checkpoint": True, "memory": True},
    )


class InMemoryHarness(HarnessAdapter):
    """Deterministic conforming harness; it never performs provider work."""

    def __init__(self, *, capabilities: dict[str, bool] | None = None) -> None:
        self.capabilities = AdapterCapabilities(
            adapter_id="memory-one", adapter_digest=HASH, adapter_kind="recorded", supported_isolation=("none",),
            claim_eligibility="fixture_only", supports_cancellation=True, supports_artifacts=True,
            capabilities=capabilities or {"state": True, "checkpoint": True, "memory": True},
        )
        self.prepares = self.executes = self.cancels = self.cleanups = 0
        self.prepared: dict[str, AttemptInput] = {}

    async def describe_capabilities(self) -> AdapterCapabilities:
        return self.capabilities

    async def healthcheck(self) -> AdapterHealth:
        return AdapterHealth(healthy=True, checked_at=NOW, detail="in-memory fixture")

    async def prepare_attempt(self, spec: HarnessSpec, input: AttemptInput) -> PreparedAttempt:
        self.prepares += 1
        self.prepared[input.attempt.attempt_id] = input
        return PreparedAttempt(
            attempt_id=input.attempt.attempt_id, adapter_id="memory-one", prepared_at=NOW,
            timeout_seconds=spec.timeout_seconds, opaque_handle=input.attempt.attempt_id,
            input_digest=sha256(input.model_dump(mode="json")),
        )

    async def execute_attempt(self, prepared: PreparedAttempt) -> ResultBundle:
        self.executes += 1
        output = b"factor fixture response"
        return ResultBundle(
            attempt_id=prepared.attempt_id, terminal_outcome="completed", completed_at=NOW,
            response_hash=sha256_bytes(output), response_artifact_id="assistant-output",
            artifacts=(ArtifactRef(artifact_id="assistant-output", media_type="text/plain", sha256=sha256_bytes(output), content=output),),
        )

    async def stream_events(self, prepared: PreparedAttempt):
        input = self.prepared[prepared.attempt_id]
        payload = {"event": "fixture"}
        yield TraceEvent(
            trace_id="trace-one", episode_id=input.attempt.episode_id, attempt_id=input.attempt.attempt_id,
            sequence=0, actor="harness", event_type="state", timestamp=NOW, monotonic_time=0,
            payload=payload, payload_hash=sha256(payload),
        )

    async def collect_artifacts(self, prepared: PreparedAttempt) -> tuple[ArtifactRef, ...]:
        output = b"factor fixture response"
        return (ArtifactRef(artifact_id="assistant-output", media_type="text/plain", sha256=sha256_bytes(output), content=output),)

    async def cancel_attempt(self, prepared: PreparedAttempt) -> None:
        self.cancels += 1

    async def cleanup_attempt(self, prepared: PreparedAttempt) -> None:
        self.cleanups += 1


class InMemoryFactorRuntime:
    def __init__(self, *, fidelity_ok: bool = True, mutate: bool = False, verify: bool = True, invalid_recovery: bool = False) -> None:
        self.fidelity_ok = fidelity_ok
        self.mutate = mutate
        self.verify = verify
        self.invalid_recovery = invalid_recovery
        self.cancels = self.cleanups = 0

    async def start(self, recipe, input: AttemptInput) -> FactorRuntimeSession:
        if self.mutate:
            input.attempt.factor_assignments["planning"] = not input.attempt.factor_assignments["planning"]
        report = FactorExecutionReport(
            observed_assignment=dict(recipe.assignment),
            observed_budgets={mechanism.factor_id: mechanism.treatment_budget for mechanism in recipe.mechanisms},
            evidence=(evidence(),),
            plan_history=self._plan(input) if recipe.assignment["planning"] else (),
            memory=self._memory(input) if recipe.assignment["memory"] else None,
        )
        if not self.fidelity_ok:
            report = FactorExecutionReport(
                observed_assignment=dict(recipe.assignment),
                observed_budgets={**report.observed_budgets, "planning": TreatmentBudget(compute_units=99, context_bytes=0)},
                evidence=report.evidence, plan_history=report.plan_history, memory=report.memory,
            )
        return FactorRuntimeSession(token=object(), initial_report=report)

    async def finalize(self, recipe, input: AttemptInput, session: FactorRuntimeSession, result: ResultBundle) -> FactorExecutionReport:
        report = session.initial_report
        verification = None
        if recipe.assignment["verification"] and self.verify:
            check = VerificationCheck(check_id="check-one", status="passed", detail="fixture pre-finalization check", evidence=(evidence(),))
            candidate = FinalizationCandidate(episode_id=input.attempt.episode_id, response_hash=result.response_hash or HASH)
            verification = VerificationArtifact(
                episode_id=input.attempt.episode_id, candidate_response_hash=candidate.response_hash,
                final_response_hash=candidate.response_hash, checks=(check,), repairs_used=0, finalization_allowed=True,
            )
        recovery = ()
        if recipe.assignment["recovery"] and self.invalid_recovery:
            failure = FailureEvent(episode_id=input.attempt.episode_id, attempt_id=input.attempt.attempt_id, failure_id="not-declared", failure_class="transient", detail="fixture")
            recovery = (RecoveryObservation(
                failure=failure, checkpoint=None, policy=RecoveryPolicy(max_retries=1), retries_used=0,
                idempotency_key="retry-one", observed_checkpoint_sequences=frozenset(),
                decision=RecoveryDecision(allowed=True, reason="forged", retry_number=1, idempotency_key="retry-one", checkpoint_id="checkpoint-one"),
            ),)
        return FactorExecutionReport(
            observed_assignment=report.observed_assignment, observed_budgets=report.observed_budgets,
            evidence=report.evidence, plan_history=report.plan_history, verification=verification,
            recovery=recovery, memory=report.memory,
        )

    async def cancel(self, recipe, input, session) -> None:
        self.cancels += 1

    async def cleanup(self, recipe, input, session) -> None:
        self.cleanups += 1

    @staticmethod
    def _plan(input: AttemptInput):
        plan = create_plan(episode_id=input.attempt.episode_id, plan_id="plan-one", steps=(("step-one", "Synthetic plan step"),))
        started = transition_plan_step(plan, step_id="step-one", state="in_progress")
        return (plan, started, transition_plan_step(started, step_id="step-one", state="completed", evidence=evidence()))

    @staticmethod
    def _memory(input: AttemptInput):
        memory = new_episode_memory(episode_id=input.attempt.episode_id, max_items=2, max_bytes=400)
        for item_id, content in (("item-one", "a" * 100), ("item-two", "b" * 100), ("item-three", "c" * 100)):
            memory = append_memory(memory, MemoryItem(item_id=item_id, episode_id=input.attempt.episode_id, content=content, source_pointers=(evidence(item_id),)))
        return memory


@pytest.mark.asyncio
async def test_all_sixteen_recipes_complete_one_bound_adapter_lifecycle() -> None:
    terminals: list[str] = []
    for number, recipe in enumerate(enumerate_flagship_recipes(), start=1):
        inner = InMemoryHarness()
        runtime = InMemoryFactorRuntime()
        adapter = FactorizedHarnessAdapter(adapter=inner, recipe=recipe, runtime=runtime)
        source = attempt(number, recipe.assignment)
        prepared = await adapter.prepare_attempt(harness(), source)
        result = await adapter.execute_attempt(prepared)
        assert await adapter.execute_attempt(prepared) == result
        assert await adapter.collect_artifacts(prepared) == result.artifacts
        assert result.response_artifact_id == "assistant-output"
        events = [event async for event in adapter.stream_events(prepared)]
        assert [event.sequence for event in events] == list(range(len(events)))
        assert events[0].payload["input_digest"] == prepared.input_digest
        assert len([event for event in events if event.payload.get("event") == "factor_terminal"]) == 1
        assert all(event.payload.get("passed") is True for event in events if event.payload.get("event") == "factor_fidelity")
        assert all(item.delivered for item in adapter.fidelity[prepared.attempt_id])
        await adapter.cancel_attempt(prepared)
        await adapter.cancel_attempt(prepared)
        await adapter.cleanup_attempt(prepared)
        await adapter.cleanup_attempt(prepared)
        assert (inner.cancels, inner.cleanups, runtime.cancels, runtime.cleanups) == (1, 1, 1, 1)
        assert source.attempt.factor_assignments == recipe.assignment
        assert inner.prepared[prepared.attempt_id].attempt.factor_assignments == recipe.assignment
        terminals.append(result.terminal_outcome)
    assert terminals == ["completed"] * 16


@pytest.mark.asyncio
async def test_single_trusted_router_reaches_all_sixteen_bound_recipes() -> None:
    """One durable harness identity must not choose a plugin per treatment."""
    inner = InMemoryHarness()
    router = FactorizedRecipeRouterAdapter(adapter=inner, runtime=InMemoryFactorRuntime())
    terminals: list[str] = []
    for number, recipe in enumerate(enumerate_flagship_recipes(), start=40):
        prepared = await router.prepare_attempt(harness(), attempt(number, recipe.assignment))
        terminals.append((await router.execute_attempt(prepared)).terminal_outcome)
        events = [event async for event in router.stream_events(prepared)]
        assert events[-1].payload["event"] == "factor_terminal"
        await router.cleanup_attempt(prepared)
    assert terminals == ["completed"] * 16
    assert inner.prepares == inner.executes == inner.cleanups == 16


@pytest.mark.asyncio
async def test_capability_mismatch_mutation_and_fidelity_failure_stop_before_provider_execution() -> None:
    recipe = compile_recipe({"planning": True, "verification": False, "recovery": False, "memory": False})
    missing = InMemoryHarness(capabilities={"checkpoint": True, "memory": True})
    with pytest.raises(FactorAdapterError, match="lacks required"):
        await FactorizedHarnessAdapter(adapter=missing, recipe=recipe, runtime=InMemoryFactorRuntime()).prepare_attempt(harness(), attempt(20, recipe.assignment))
    assert missing.prepares == 0

    for number, runtime in ((21, InMemoryFactorRuntime(mutate=True)), (22, InMemoryFactorRuntime(fidelity_ok=False))):
        inner = InMemoryHarness()
        with pytest.raises(FactorAdapterError):
            await FactorizedHarnessAdapter(adapter=inner, recipe=recipe, runtime=runtime).prepare_attempt(harness(), attempt(number, recipe.assignment))
        assert inner.prepares == inner.executes == 0


@pytest.mark.asyncio
async def test_recipe_assignment_is_canonical_snapshot_immutable_after_adapter_construction() -> None:
    recipe = compile_recipe({"planning": True, "verification": False, "recovery": False, "memory": False})
    adapter = FactorizedHarnessAdapter(adapter=InMemoryHarness(), recipe=recipe, runtime=InMemoryFactorRuntime())
    recipe.assignment["planning"] = False
    adapter.recipe.assignment["planning"] = False
    prepared = await adapter.prepare_attempt(harness(), attempt(25, {"planning": True, "verification": False, "recovery": False, "memory": False}))
    assert (await adapter.execute_attempt(prepared)).terminal_outcome == "completed"
    assert adapter.recipe.assignment["planning"] is True


@pytest.mark.asyncio
async def test_stream_first_waits_for_final_fidelity_and_single_terminal_event() -> None:
    recipe = compile_recipe({"planning": True, "verification": True, "recovery": True, "memory": True})
    adapter = FactorizedHarnessAdapter(adapter=InMemoryHarness(), recipe=recipe, runtime=InMemoryFactorRuntime())
    prepared = await adapter.prepare_attempt(harness(), attempt(26, recipe.assignment))

    async def collect() -> list[TraceEvent]:
        return [event async for event in adapter.stream_events(prepared)]

    stream = asyncio.create_task(collect())
    await asyncio.sleep(0)
    assert not stream.done()
    first = await adapter.execute_attempt(prepared)
    assert await adapter.execute_attempt(prepared) == first
    events = await asyncio.wait_for(stream, timeout=1)

    assert first.terminal_outcome == "completed"
    assert [event.sequence for event in events] == list(range(len(events)))
    assert all(event.attempt_id == prepared.attempt_id for event in events)
    assert {event.episode_id for event in events} == {"episode-26"}
    fidelity = [event for event in events if event.payload.get("event") == "factor_fidelity"]
    assert len(fidelity) == 4
    assert all(event.payload["passed"] is True for event in fidelity)
    assert all(event.payload.get("reason") != "no finalized fidelity report" for event in fidelity)
    terminal = [event for event in events if event.payload.get("event") == "factor_terminal"]
    assert len(terminal) == 1
    assert terminal[0].payload == {"event": "factor_terminal", "outcome": "completed", "fidelity_observed": True}
    cached_events = await asyncio.wait_for(collect(), timeout=1)
    assert [event.payload.get("event") for event in cached_events].count("factor_terminal") == 1


@pytest.mark.asyncio
async def test_verification_and_undeclared_recovery_fail_closed_after_execution() -> None:
    verification_recipe = compile_recipe({"planning": False, "verification": True, "recovery": False, "memory": False})
    verification = FactorizedHarnessAdapter(adapter=InMemoryHarness(), recipe=verification_recipe, runtime=InMemoryFactorRuntime(verify=False))
    prepared = await verification.prepare_attempt(harness(), attempt(30, verification_recipe.assignment))
    assert (await verification.execute_attempt(prepared)).terminal_outcome == "incomplete"
    verification_events = [event async for event in verification.stream_events(prepared)]
    verification_fidelity = [event for event in verification_events if event.payload.get("event") == "factor_fidelity"]
    assert len(verification_fidelity) == 4
    assert all(event.payload["passed"] is False for event in verification_fidelity)
    assert verification_events[-1].payload == {"event": "factor_terminal", "outcome": "incomplete", "fidelity_observed": False}
    assert prepared.attempt_id not in verification.fidelity

    recovery_recipe = compile_recipe({"planning": False, "verification": False, "recovery": True, "memory": False})
    recovery = FactorizedHarnessAdapter(adapter=InMemoryHarness(), recipe=recovery_recipe, runtime=InMemoryFactorRuntime(invalid_recovery=True))
    prepared = await recovery.prepare_attempt(harness(), attempt(31, recovery_recipe.assignment))
    assert (await recovery.execute_attempt(prepared)).terminal_outcome == "incomplete"
    recovery_events = [event async for event in recovery.stream_events(prepared)]
    recovery_fidelity = [event for event in recovery_events if event.payload.get("event") == "factor_fidelity"]
    assert len(recovery_fidelity) == 4
    assert all(event.payload["passed"] is False for event in recovery_fidelity)
    assert recovery_events[-1].payload == {"event": "factor_terminal", "outcome": "incomplete", "fidelity_observed": False}
    assert prepared.attempt_id not in recovery.fidelity
