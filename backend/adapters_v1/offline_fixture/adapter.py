"""Trusted replay of the repository-bundled offline-demo-v1 fixture only."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

from execution_v1.state import StateOracleDecision
from protocol_v1.canonical import canonical_json, sha256, sha256_bytes
from protocol_v1.models import HarnessSpec, TraceEvent

from ..base import HarnessAdapter
from ..models import (
    AdapterCapabilities,
    AdapterHealth,
    ArtifactRef,
    AttemptInput,
    PreparedAttempt,
    ProviderUsage,
    ResultBundle,
    validate_events_for_attempt,
    validate_result_for_attempt,
)
from ..preflight import preflight

OFFLINE_DEMO_ADAPTER_ID = "offline-demo-fixture"
_PACK_ROOT = Path(__file__).resolve().parent / "study_pack"
_FACTOR_IDS = ("planning", "verification", "recovery", "memory")
_EXPECTED_BUDGET = {
    "max_attempts": 80,
    "max_cost_usd": 0.0,
    "max_latency_seconds": 5.0,
    "max_tokens": 64,
    "max_tool_calls": 0,
    "max_context_tokens": 2048,
}
_EXPECTED_CONFIGURATION = {
    "fixture_mode": "offline-demo-v1",
    "fixture_truth_table_sha256": "92587ad86a7623b55b57fe1efcd5b4d84da907dd729e30be0ee719a7886c738d",
    "recorded_usage": {
        "authority": "bundled-offline-demo-v1",
        "evidence_source": "fixture_recorded",
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "context_tokens": 0,
        "tool_calls": 0,
        "actual_cost_usd": 0.0,
    },
}
_EXPECTED_CONFIGURATION_HASH = "5cb37b14885738185e80e26ea93ed8837f504bf4313b1e714a02d6459c70592a"
_FIXTURE_USAGE_DIGEST = "c334ec1911a39d529a00678e58ba734769fb41585588d3277cd8d76998b71952"
_TRUTH_TABLE_DIGEST = "92587ad86a7623b55b57fe1efcd5b4d84da907dd729e30be0ee719a7886c738d"
_SCENARIO_DIGESTS = {
    "candidate-clean": "20857eb16c48a9b603972f1a66f44cb89e00d1145842db685e372187305d91f1",
    "candidate-stress": "17cd9c7c282f70890d1f447fc2c2cb99b368f5e51836a2d04180fe1287db9369",
    "positive-control": "93cd552755fb35f4f19830353fbcb5d8a758fd1b329550f3a2d684d10a34cfbd",
    "negative-control": "24109464ffd258e02f9123472660ed0a26b6b96231f4d8ec82a7f7273bd7d8a7",
    "anti-cheat-control": "6b8cdd605809233394920214f2178aa1acdea19a9ad16d3b26e28acaa935d420",
}
_OUTPUT_FILES = {
    "candidate-clean.json": "71d34b3048d80958c26ffdbac13e24353a6a26f651b5699bf69242eb8069ec21",
    "candidate-stress.json": "71d34b3048d80958c26ffdbac13e24353a6a26f651b5699bf69242eb8069ec21",
    "candidate-mechanism-miss.json": "6a826c329debae6c4f6f4214d7d68423aa736a07f7e8b5bd345a6336fed3f184",
    "positive-control.json": "71d34b3048d80958c26ffdbac13e24353a6a26f651b5699bf69242eb8069ec21",
    "negative-control.json": "881f9e0ae6fdfbd596f6a4325d43b37aeb9d10f11f6e6592e029e09bdda1abfd",
    "anti-cheat-control.json": "3e6f480629aa6468e9853986993ae1a774be03c8ef15d24328f550984b204164",
}
_DECLARED_STATE_BY_SCENARIO = {
    "candidate-clean": "completed",
    "candidate-stress": "completed",
    "positive-control": "completed",
    "negative-control": "failed",
    "anti-cheat-control": "completed",
}
OFFLINE_DEMO_ADAPTER_DIGEST = sha256({
    "adapter": OFFLINE_DEMO_ADAPTER_ID,
    "version": "1.0.0",
    "configuration": _EXPECTED_CONFIGURATION,
    "scenario_digests": _SCENARIO_DIGESTS,
    "output_digests": _OUTPUT_FILES,
    "truth_table_digest": _TRUTH_TABLE_DIGEST,
})


def bundled_study_pack_root() -> Path:
    return _PACK_ROOT


class OfflineDemoFixtureAdapter(HarnessAdapter):
    """Replays only vetted repository fixtures; it never reads an uploaded result map."""

    def __init__(self) -> None:
        self._capabilities = AdapterCapabilities(
            adapter_id=OFFLINE_DEMO_ADAPTER_ID,
            adapter_digest=OFFLINE_DEMO_ADAPTER_DIGEST,
            adapter_kind="recorded",
            supported_isolation=("none",),
            claim_eligibility="fixture_only",
            supports_cancellation=True,
            supports_artifacts=True,
            capabilities={"state": True, "checkpoint": True, "memory": True, "usage": True},
        )
        self._fixtures = self._load_fixtures()
        self._truth_table = self._load_truth_table()
        self._attempts: dict[str, AttemptInput] = {}
        self._cancelled: set[str] = set()

    async def describe_capabilities(self) -> AdapterCapabilities:
        return self._capabilities

    async def healthcheck(self) -> AdapterHealth:
        self._load_fixtures()
        return AdapterHealth(healthy=True, checked_at=datetime.now(UTC), detail="bundled offline-demo-v1 fixtures verified")

    async def prepare_attempt(self, harness: HarnessSpec, input: AttemptInput) -> PreparedAttempt:
        input = AttemptInput.model_validate_json(canonical_json(input.model_dump(mode="json")))
        preflight(self._capabilities, harness, input)
        self._validate_binding(harness, input)
        self._attempts[input.attempt.attempt_id] = input
        return PreparedAttempt(
            attempt_id=input.attempt.attempt_id,
            adapter_id=OFFLINE_DEMO_ADAPTER_ID,
            prepared_at=datetime.now(UTC),
            timeout_seconds=harness.timeout_seconds,
            opaque_handle=input.attempt.attempt_id,
            input_digest=sha256(input.model_dump(mode="json")),
        )

    async def execute_attempt(self, prepared: PreparedAttempt) -> ResultBundle:
        input = self._attempt(prepared)
        if prepared.attempt_id in self._cancelled:
            return ResultBundle(attempt_id=prepared.attempt_id, terminal_outcome="cancelled", completed_at=datetime.now(UTC), detail="cancelled")
        entry = self._fixture_entry(input)
        content, digest = self._fixtures[entry["output_file"]]
        result = ResultBundle(
            attempt_id=prepared.attempt_id,
            terminal_outcome="completed",
            completed_at=datetime.now(UTC),
            response_hash=digest,
            response_artifact_id="response",
            artifacts=(ArtifactRef(artifact_id="response", media_type="application/json", sha256=digest, content=content),),
            usage=ProviderUsage(
                evidence_source="fixture_recorded",
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                context_tokens=0,
                tool_calls=0,
                actual_cost_usd=0.0,
                provider_usage_digest=_FIXTURE_USAGE_DIGEST,
            ),
            detail="bundled synthetic recorded fixture; no provider was invoked",
        )
        return validate_result_for_attempt(result, input.attempt)

    async def stream_events(self, prepared: PreparedAttempt) -> AsyncIterator[TraceEvent]:
        input = self._attempt(prepared)
        attempt = input.attempt
        scenario_id = input.scenario.scenario_id
        entry = self._fixture_entry(input)
        payloads: list[tuple[str, str, dict[str, object]]] = [
            ("harness", "request", {
                "event": "bundled_fixture_binding",
                "fixture_only": True,
                "scenario_id": scenario_id,
                "scenario_digest": input.scenario_digest,
                "binding_digest": input.binding_digest,
                "truth_table_digest": _TRUTH_TABLE_DIGEST,
                "fixture_rule": entry["fixture_rule"],
            }),
        ]
        for factor_id in _FACTOR_IDS:
            assignment = attempt.factor_assignments[factor_id]
            payloads.append(("harness", "state", {
                "event": "factor_fidelity",
                "fixture_only": True,
                "factor_id": factor_id,
                "expected_value": assignment,
                "observed_value": assignment,
                "passed": True,
                "compute_context_matched": True,
            }))
        payloads.extend((
            ("harness", "state", {
                "event": "bundled_fixture_state",
                "fixture_only": True,
                "case_state": entry["case_state"],
            }),
            ("harness", "response", {
                "event": "bundled_fixture_response",
                "fixture_only": True,
                "response_hash": self._fixtures[entry["output_file"]][1],
            }),
        ))
        now = datetime.now(UTC)
        events = tuple(
            TraceEvent(
                trace_id=f"offline-fixture-{attempt.attempt_id}",
                episode_id=attempt.episode_id,
                attempt_id=attempt.attempt_id,
                sequence=sequence,
                actor=actor,
                event_type=event_type,
                timestamp=now,
                monotonic_time=float(sequence),
                payload=payload,
                payload_hash=sha256(payload),
            )
            for sequence, (actor, event_type, payload) in enumerate(payloads)
        )
        for event in validate_events_for_attempt(events, attempt):
            yield event

    async def collect_artifacts(self, prepared: PreparedAttempt) -> tuple[ArtifactRef, ...]:
        input = self._attempt(prepared)
        content, digest = self._fixtures[self._fixture_entry(input)["output_file"]]
        return (ArtifactRef(artifact_id="response", media_type="application/json", sha256=digest, content=content),)

    async def cancel_attempt(self, prepared: PreparedAttempt) -> None:
        self._attempt(prepared)
        self._cancelled.add(prepared.attempt_id)

    async def cleanup_attempt(self, prepared: PreparedAttempt) -> None:
        self._attempt(prepared)

    def _attempt(self, prepared: PreparedAttempt) -> AttemptInput:
        if prepared.adapter_id != OFFLINE_DEMO_ADAPTER_ID or prepared.attempt_id not in self._attempts:
            raise ValueError("prepared attempt is not owned by the bundled offline fixture adapter")
        input = self._attempts[prepared.attempt_id]
        if prepared.input_digest != sha256(input.model_dump(mode="json")):
            raise ValueError("prepared attempt input binding mismatch")
        return input

    def _validate_binding(self, harness: HarnessSpec, input: AttemptInput) -> None:
        if (
            harness.harness_id != "offline-recorded"
            or harness.adapter != "recorded"
            or harness.adapter_identity != OFFLINE_DEMO_ADAPTER_ID
            or harness.adapter_digest != OFFLINE_DEMO_ADAPTER_DIGEST
            or harness.execution_mode != "recorded"
            or harness.isolation != "none"
            or harness.claim_eligibility != "fixture_only"
            or harness.configuration != _EXPECTED_CONFIGURATION
            or harness.effective_configuration_hash != _EXPECTED_CONFIGURATION_HASH
        ):
            raise ValueError("harness is not the exact bundled offline-demo-v1 fixture contract")
        if input.scenario.scenario_id not in _SCENARIO_DIGESTS or input.scenario_digest != _SCENARIO_DIGESTS[input.scenario.scenario_id]:
            raise ValueError("scenario is not an exact bundled offline-demo-v1 fixture scenario")
        attempt = input.attempt
        if (
            attempt.provider != "recorded"
            or attempt.provider_model != "offline-demo-v1"
            or attempt.endpoint_id != "recorded-fixture"
            or attempt.pinned_endpoint_digest != "5146f853f4be70353ce768cca1a57d7e653ef2a15da5bf26bccd7b8c2175080a"
        ):
            raise ValueError("bundled fixture adapter accepts only the offline-demo-v1 recorded endpoint")
        if attempt.budget.model_dump(mode="json") != _EXPECTED_BUDGET:
            raise ValueError("bundled fixture adapter accepts only the frozen offline-demo-v1 budget")
        if set(attempt.factor_assignments) != set(_FACTOR_IDS) or any(type(attempt.factor_assignments[factor_id]) is not bool for factor_id in _FACTOR_IDS):
            raise ValueError("bundled fixture adapter requires the exact P/V/R/M boolean assignments")
        self._fixture_entry(input)

    @staticmethod
    def _load_fixtures() -> dict[str, tuple[bytes, str]]:
        loaded: dict[str, tuple[bytes, str]] = {}
        for filename, expected_digest in _OUTPUT_FILES.items():
            content = (_PACK_ROOT / "fixtures" / "outputs" / filename).read_bytes()
            if sha256_bytes(content) != expected_digest:
                raise ValueError("bundled offline-demo-v1 output fixture digest mismatch")
            loaded[filename] = (content, expected_digest)
        return loaded

    @staticmethod
    def _load_truth_table() -> dict[tuple[str, tuple[bool, ...]], dict[str, object]]:
        path = _PACK_ROOT / "fixtures" / "runtime-truth-table.json"
        content = path.read_bytes()
        if sha256_bytes(content) != _TRUTH_TABLE_DIGEST:
            raise ValueError("bundled offline-demo-v1 fixture truth table digest mismatch")
        raw = json.loads(content)
        if not isinstance(raw, dict) or set(raw) != {"schema_version", "claim_ceiling", "factor_order", "rows"}:
            raise ValueError("bundled offline-demo-v1 fixture truth table schema mismatch")
        if raw["schema_version"] != "bundled-offline-demo-fixture-truth-table-v1" or raw["factor_order"] != list(_FACTOR_IDS):
            raise ValueError("bundled offline-demo-v1 fixture truth table version mismatch")
        rows = raw["rows"]
        if not isinstance(rows, list):
            raise TypeError("bundled offline-demo-v1 fixture truth table rows are invalid")
        table: dict[tuple[str, tuple[bool, ...]], dict[str, object]] = {}
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"scenario_id", "assignment", "output_file", "case_state", "fixture_rule", "fixture_enabled_mechanisms"}:
                raise ValueError("bundled offline-demo-v1 fixture truth table row is invalid")
            scenario_id = row["scenario_id"]
            assignment = row["assignment"]
            output_file = row["output_file"]
            case_state = row["case_state"]
            enabled = row["fixture_enabled_mechanisms"]
            if (
                not isinstance(scenario_id, str)
                or scenario_id not in _SCENARIO_DIGESTS
                or not isinstance(assignment, dict)
                or set(assignment) != set(_FACTOR_IDS)
                or any(type(assignment[factor_id]) is not bool for factor_id in _FACTOR_IDS)
                or not isinstance(output_file, str)
                or output_file not in _OUTPUT_FILES
                or case_state not in {"completed", "failed"}
                or not isinstance(enabled, list)
                or enabled != [factor_id for factor_id in _FACTOR_IDS if assignment[factor_id]]
            ):
                raise ValueError("bundled offline-demo-v1 fixture truth table binding is invalid")
            key = (scenario_id, tuple(assignment[factor_id] for factor_id in _FACTOR_IDS))
            if key in table:
                raise ValueError("bundled offline-demo-v1 fixture truth table has duplicate bindings")
            table[key] = row
        expected = {
            (scenario_id, tuple(bool(mask & (1 << (len(_FACTOR_IDS) - index - 1))) for index in range(len(_FACTOR_IDS))))
            for scenario_id in _SCENARIO_DIGESTS
            for mask in range(2 ** len(_FACTOR_IDS))
        }
        if set(table) != expected:
            raise ValueError("bundled offline-demo-v1 fixture truth table does not cover every scenario and P/V/R/M assignment")
        return table

    def _fixture_entry(self, input: AttemptInput) -> dict[str, object]:
        key = (
            input.scenario.scenario_id,
            tuple(input.attempt.factor_assignments[factor_id] for factor_id in _FACTOR_IDS),
        )
        try:
            return self._truth_table[key]
        except KeyError as exc:
            raise ValueError("bundled offline-demo-v1 fixture truth table has no attempt binding") from exc


class OfflineDemoFixtureStateOracle:
    """Trusted state context for the bundled fixture's declared deterministic controls."""

    def __init__(self) -> None:
        self._truth_table = OfflineDemoFixtureAdapter._load_truth_table()

    def evaluate(self, scenario, oracle, attempt, result) -> StateOracleDecision:
        scenario_id = scenario.scenario_id
        declared_state = _DECLARED_STATE_BY_SCENARIO.get(scenario_id)
        if declared_state is None or _SCENARIO_DIGESTS.get(scenario_id) != sha256(scenario.model_dump(mode="json")):
            raise ValueError("state oracle accepts only exact bundled offline-demo-v1 scenarios")
        if oracle.expected != {"case_state": declared_state}:
            raise ValueError("state oracle declaration differs from bundled fixture contract")
        key = (scenario_id, tuple(attempt.factor_assignments[factor_id] for factor_id in _FACTOR_IDS))
        try:
            case_state = self._truth_table[key]["case_state"]
        except KeyError as exc:
            raise ValueError("state oracle has no bundled fixture attempt binding") from exc
        return StateOracleDecision(
            terminal_outcome=result.terminal_outcome,
            detail="bundled_fixture_declared_state",
            evidence={
                "case_state": case_state,
                "fixture_only": True,
                "source": "bundled-offline-demo-v1",
                "claim_ceiling": "synthetic recorded fixture only",
            },
        )
