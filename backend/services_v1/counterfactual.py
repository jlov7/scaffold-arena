"""Provider-free custody services for Counterfactual Replay and Harness CI.

The services only calculate over caller-supplied, already-recorded references.
They do not construct a runtime, fetch a target, or start a provider.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import ValidationError
from sqlalchemy import insert, select

from artifacts_v1 import ArtifactIntegrityError, ArtifactStore
from persistence_v1 import ArenaRepository
from persistence_v1.schema import artifacts, counterfactual_replays, harness_ci_reports, projects
from protocol_v1.canonical import canonical_json
from replay_v1 import (
    CounterfactualReplayReport,
    CounterfactualReplayRequest,
    HarnessCIReport,
    HarnessCIRequest,
    ReplayPair,
)


_REPLAY_MEDIA_TYPE = "application/vnd.scaffold-arena.counterfactual-replay-report+json"
_CI_MEDIA_TYPE = "application/vnd.scaffold-arena.harness-ci-report+json"
_FIXTURE_CEILING = "Fixture replay validates contract mechanics only; it is not causal or model-performance evidence."
_RECORDED_CEILING = "Bounded paired recorded replay is not causal proof, generalized performance evidence, or independent validation."
_LIVE_CEILING = "No live provider was started; this declared live replay is HOLD, not execution evidence."
_CI_CEILING = "Harness CI is a bounded policy check over recorded evidence; PASS is not causal, deployment, or independent-assurance approval."
_FIDELITY_ORDER = {name: index for index, name in enumerate((
    "declared", "assigned", "available", "triggered", "applied", "activated", "observed", "downstream_pathway_detected",
))}
_MATURITY_ORDER = {name: index for index, name in enumerate((
    "temporal_correlation", "diagnostic_divergence", "paired_replay", "replicated_intervention", "confirmatory_eligibility",
))}
_SEMANTIC_PACKS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("context_compaction", ("context compact", "context_compact", "compaction", "summari", "context window"), "context-survival-v1"),
    ("retry_stopping", ("retry", "backoff", "max_attempt", "max attempts", "stopping", "stop condition"), "recovery-faults-v1"),
    ("permission_handling", ("permission", "allowlist", "denylist", "authorization", "authz"), "permission-boundaries-v1"),
)


class CounterfactualError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class HarnessCIError(CounterfactualError):
    pass


def _bare(value: str, *, code: str, message: str) -> str:
    value = value.removeprefix("sha256:")
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise CounterfactualError(code, message)
    return value


def _prefixed(value: str) -> str:
    return f"sha256:{value}"


def _canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _mean(values: Sequence[float]) -> float:
    return math.fsum(values) / len(values)


def _estimate(metric: str, base: Sequence[float] | None, candidate: Sequence[float] | None, reason: str) -> dict[str, Any]:
    if base is None or candidate is None or not base or len(base) != len(candidate):
        return {"metric": metric, "state": "unknown", "point_estimate": None, "ci95_low": None, "ci95_high": None, "base_mean": None, "candidate_mean": None, "paired_samples": 0 if base is None else len(base), "reason": reason}
    deltas = [right - left for left, right in zip(base, candidate, strict=True)]
    mean = _mean(deltas)
    common = {"metric": metric, "state": "observed", "point_estimate": mean, "base_mean": _mean(base), "candidate_mean": _mean(candidate), "paired_samples": len(deltas)}
    if len(deltas) == 1:
        return {**common, "ci95_low": None, "ci95_high": None, "reason": "One paired observation has no repeat-based uncertainty interval."}
    variance = math.fsum((value - mean) ** 2 for value in deltas) / (len(deltas) - 1)
    half = 1.96 * math.sqrt(variance / len(deltas))
    return {**common, "ci95_low": mean - half, "ci95_high": mean + half, "reason": "Normal-approximation 95% interval over recorded paired differences; not a causal estimate."}


def _cost_values(pairs: Sequence[ReplayPair]) -> tuple[list[float], list[float]] | None:
    outcomes = [outcome for pair in pairs for outcome in (pair.base, pair.candidate)]
    if any(outcome.usage.state != "observed" or outcome.usage.cost_usd is None for outcome in outcomes):
        return None
    return ([float(pair.base.usage.cost_usd) for pair in pairs], [float(pair.candidate.usage.cost_usd) for pair in pairs])


def _latency_values(pairs: Sequence[ReplayPair]) -> tuple[list[float], list[float]] | None:
    outcomes = [outcome for pair in pairs for outcome in (pair.base, pair.candidate)]
    if any(outcome.latency_state != "observed" or outcome.latency_ms is None for outcome in outcomes):
        return None
    return ([float(pair.base.latency_ms) for pair in pairs], [float(pair.candidate.latency_ms) for pair in pairs])


def _maturity(request: CounterfactualReplayRequest) -> tuple[str, list[dict[str, str]]]:
    divergence = any(pair.base.quality_score != pair.candidate.quality_score for pair in request.pairs)
    repeated = len(request.pairs) >= 2 and len(request.pairs) >= request.analysis_plan.planned_repetitions
    eligible = repeated and request.analysis_plan.confirmatory_holdout_declared
    ladder = [
        {"maturity": "temporal_correlation", "state": "observed", "reason": "Ordered outcomes are observation only, never causal evidence."},
        {"maturity": "diagnostic_divergence", "state": "observed" if divergence else "unknown", "reason": "A score difference is diagnostic-only and does not identify a cause." if divergence else "No recorded primary-endpoint divergence was detected."},
        {"maturity": "paired_replay", "state": "observed", "reason": "Both branches share the declared common pre-divergence binding."},
        {"maturity": "replicated_intervention", "state": "observed" if repeated else "unknown", "reason": "Predeclared repeated paired branches were recorded." if repeated else "The predeclared repeat count has not been reached."},
        {"maturity": "confirmatory_eligibility", "state": "observed" if eligible else "ineligible", "reason": "Holdout and repeated-intervention prerequisites are declared; eligibility is not a confirmatory result." if eligible else "Confirmatory eligibility requires replication plus a separately declared holdout."},
    ]
    return ("confirmatory_eligibility" if eligible else "replicated_intervention" if repeated else "paired_replay", ladder)


def _fidelity(pairs: Sequence[ReplayPair]) -> str | None:
    levels = [outcome.fidelity_level for pair in pairs for outcome in (pair.base, pair.candidate)]
    if any(level is None for level in levels):
        return None
    return min((level for level in levels if level is not None), key=lambda level: _FIDELITY_ORDER[level])


class CounterfactualReplayService:
    def __init__(self, repository: ArenaRepository, artifact_store: ArtifactStore, *, personal_project_id: str | None = None) -> None:
        self.repository = repository
        self.artifact_store = artifact_store
        self.personal_project_id = personal_project_id

    def _project(self, project_id: str | None) -> str:
        project = project_id or self.personal_project_id
        if not project:
            raise CounterfactualError("project_context_required", "An explicit project context is required.")
        with self.repository.engine.connect() as conn:
            exists = conn.execute(select(projects.c.id).where(projects.c.id == project)).scalar_one_or_none()
        if exists is None:
            raise CounterfactualError("unknown_project", "The supplied project does not exist.", status_code=404)
        return project

    @staticmethod
    def _request(payload: Mapping[str, Any]) -> CounterfactualReplayRequest:
        try:
            return CounterfactualReplayRequest.model_validate(payload)
        except (TypeError, ValidationError, ValueError) as exc:
            raise CounterfactualError("counterfactual_contract_invalid", "A strict checkpointed paired replay contract is required.") from exc

    @staticmethod
    def _raw(request: CounterfactualReplayRequest) -> tuple[dict[str, Any], str]:
        request_digest = _canonical_digest(request)
        binding_digest = _canonical_digest(request.binding)
        costs, latency = _cost_values(request.pairs), _latency_values(request.pairs)
        effects = [
            _estimate("quality", [pair.base.quality_score for pair in request.pairs], [pair.candidate.quality_score for pair in request.pairs], "Quality is derived from recorded blinded evaluator outputs."),
            _estimate("cost_usd", *(costs if costs is not None else (None, None)), "Cost is unknown because no complete provider-usage evidence is bound."),
            _estimate("latency_ms", *(latency if latency is not None else (None, None)), "Latency is unknown because no complete runtime timing evidence is bound."),
        ]
        maturity, ladder = _maturity(request)
        usage_state = "observed" if all(outcome.usage.state == "observed" for pair in request.pairs for outcome in (pair.base, pair.candidate)) else "unknown"
        fidelity = _fidelity(request.pairs)
        safety_states = {outcome.process_safety for pair in request.pairs for outcome in (pair.base, pair.candidate)}
        process_safety = "fail" if "fail" in safety_states else "unknown" if "unknown" in safety_states else "pass"
        base_failures = {failure for pair in request.pairs for failure in pair.base.severe_failure_codes}
        candidate_failures = {failure for pair in request.pairs for failure in pair.candidate.severe_failure_codes}
        severe = sorted(candidate_failures - base_failures)
        if request.mode == "live":
            verdict = "HOLD"
        elif severe or process_safety == "fail":
            verdict = "FAIL"
        elif usage_state == "unknown" or fidelity is None or _FIDELITY_ORDER[fidelity] < _FIDELITY_ORDER["applied"] or process_safety == "unknown" or len(request.pairs) < request.analysis_plan.planned_repetitions:
            verdict = "HOLD"
        else:
            verdict = "PASS"
        ceiling = _FIXTURE_CEILING if request.mode == "fixture" else _LIVE_CEILING if request.mode == "live" else _RECORDED_CEILING
        limitations = [
            "Recorded references are custody bindings, not raw traces or outcome verification.",
            "Replay is not causal proof, model-performance evidence, or independent validation.",
        ]
        conditional_measures = [
            {"measure": "intention_to_treat", "state": "ineligible", "value": None, "reason": "Paired replay is not a randomized assignment estimate."},
            {"measure": "opportunity", "state": "ineligible", "value": None, "reason": "No intervention-opportunity denominator is bound to this replay."},
            {"measure": "activation", "state": "ineligible", "value": None, "reason": "No observed activation estimator is bound to this replay."},
            {"measure": "fidelity_failure", "state": "ineligible", "value": None, "reason": "The replay records minimum fidelity, not a fidelity-failure estimator."},
            {"measure": "treatment_on_the_treated", "state": "ineligible", "value": None, "reason": "No randomized assignment and observed treatment uptake are bound."},
        ]
        if usage_state == "unknown":
            limitations.append("Unknown provider usage and cost remain unknown and are never converted to zero.")
        if request.mode == "live":
            limitations.append("This service never starts a provider; live execution remains outside this report.")
        raw = {
            "schema_version": "scaffold-arena.counterfactual-replay-report/1",
            "request_digest": _prefixed(request_digest), "binding_digest": _prefixed(binding_digest), "mode": request.mode,
            "verdict": verdict, "evidence_maturity": maturity, "maturity_ladder": ladder,
            "pair_count": len(request.pairs), "planned_repetitions": request.analysis_plan.planned_repetitions,
            "pair_references": [{"pair_id": pair.pair_id, "task_item_digest": pair.task_item_digest, "base_result_digest": pair.base.result_digest, "candidate_result_digest": pair.candidate.result_digest, "base_trace_digest": pair.base.trace_digest, "candidate_trace_digest": pair.candidate.trace_digest, "base_usage_state": pair.base.usage.state, "candidate_usage_state": pair.candidate.usage.state} for pair in request.pairs],
            "intervention": request.intervention.model_dump(mode="json"), "semantic_diff": request.semantic_diff.model_dump(mode="json"),
            "effects": effects, "conditional_measures": conditional_measures, "new_severe_failures": severe, "usage_state": usage_state, "fidelity_level": fidelity,
            "process_safety": process_safety, "claim_ceiling": ceiling, "limitations": limitations,
            "provider_execution_started": False, "execution_started": False, "network_requested": False,
        }
        return raw, request_digest

    @staticmethod
    def _public(raw: Mapping[str, Any], *, digest: str, idempotent: bool) -> dict[str, Any]:
        value = {**raw, "report_id": f"replay-{digest[:24]}", "report_digest": _prefixed(digest), "report_artifact_digest": _prefixed(digest), "idempotent_replay": idempotent}
        try:
            return CounterfactualReplayReport.model_validate(value).model_dump(mode="json")
        except ValidationError as exc:
            raise CounterfactualError("counterfactual_report_invalid", "The bounded replay report could not be validated.", status_code=500) from exc

    def local_report(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        raw, _ = self._raw(self._request(payload))
        return self._public(raw, digest=hashlib.sha256(canonical_json(raw)).hexdigest(), idempotent=False)

    def create(self, payload: Mapping[str, Any], *, project_id: str | None) -> dict[str, Any]:
        project, request = self._project(project_id), self._request(payload)
        raw, request_digest = self._raw(request)
        content = canonical_json(raw)
        digest = hashlib.sha256(content).hexdigest()
        stored = self.artifact_store.put_bytes(content, media_type=_REPLAY_MEDIA_TYPE, metadata={"kind": "counterfactual-replay-report", "request_digest": request_digest})
        if stored != digest:
            raise CounterfactualError("counterfactual_artifact_integrity", "The replay report could not be stored content-addressably.", status_code=500)
        with self.repository.transaction(immediate=True) as conn:
            prior = conn.execute(select(counterfactual_replays).where(counterfactual_replays.c.project_id == project, counterfactual_replays.c.request_digest == request_digest)).mappings().one_or_none()
            if prior is not None:
                if prior["report_artifact_digest"] != digest:
                    raise CounterfactualError("counterfactual_report_conflict", "An immutable replay report already exists for this contract.", status_code=409)
                return self._public(raw, digest=digest, idempotent=True)
            if conn.execute(select(artifacts.c.digest).where(artifacts.c.digest == digest)).scalar_one_or_none() is None:
                conn.execute(insert(artifacts).values(digest=digest, size_bytes=len(content), storage_uri=self.artifact_store.uri_for(digest), media_type=_REPLAY_MEDIA_TYPE, metadata_json={"kind": "counterfactual-replay-report", "request_digest": request_digest}))
            conn.execute(insert(counterfactual_replays).values(id=uuid.uuid4().hex, project_id=project, request_digest=request_digest, binding_digest=_bare(raw["binding_digest"], code="counterfactual_binding_invalid", message="A replay binding digest is required."), report_artifact_digest=digest, verdict=raw["verdict"], evidence_maturity=raw["evidence_maturity"], claim_ceiling=raw["claim_ceiling"]))
        return self._public(raw, digest=digest, idempotent=False)

    def _raw_for_report(self, digest: str, *, project: str) -> tuple[dict[str, str], str]:
        bare = _bare(digest, code="counterfactual_digest_invalid", message="A lowercase SHA-256 replay report digest is required.")
        with self.repository.engine.connect() as conn:
            row = conn.execute(select(counterfactual_replays).where(counterfactual_replays.c.project_id == project, counterfactual_replays.c.report_artifact_digest == bare)).mappings().one_or_none()
        if row is None:
            raise CounterfactualError("counterfactual_report_not_found", "The requested replay report was not found.", status_code=404)
        try:
            content = self.artifact_store.get_bytes(row["report_artifact_digest"])
            if hashlib.sha256(content).hexdigest() != row["report_artifact_digest"]:
                raise ValueError("digest mismatch")
            raw = json.loads(content)
            if not isinstance(raw, dict):
                raise ValueError("object required")
        except (ArtifactIntegrityError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise CounterfactualError("counterfactual_custody_unavailable", "The replay report cannot be verified.", status_code=409) from exc
        return raw, row["report_artifact_digest"]

    def report(self, digest: str, *, project_id: str | None) -> dict[str, Any]:
        raw, artifact_digest = self._raw_for_report(digest, project=self._project(project_id))
        return self._public(raw, digest=artifact_digest, idempotent=False)


def semantic_code_to_mechanisms(changes: Sequence[Any]) -> dict[str, Any]:
    """Classify bounded source diffs in memory; source text is never persisted."""
    fragments: list[str] = []
    for change in changes:
        source = str(change.diff_text)
        changed_lines = [
            line[1:]
            for line in source.splitlines()
            if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
        ]
        # A caller may provide a compact semantic excerpt rather than unified
        # diff syntax. Preserve it, but do not classify unchanged diff context.
        fragments.append("\n".join(changed_lines) if changed_lines else source)
    text = "\n".join(fragments).lower()
    affected, packs = [], []
    for mechanism, keywords, pack in _SEMANTIC_PACKS:
        if any(keyword in text for keyword in keywords):
            affected.append(mechanism)
            packs.append(pack)
    return {"affected_mechanisms": affected, "recommended_packs": packs, "classification_state": "unknown" if not affected else "observed" if len(affected) == 1 else "multiple"}


def _check(name: str, verdict: str, detail: str) -> dict[str, str]:
    return {"check_id": name, "verdict": verdict, "detail": detail}


class HarnessCIService:
    def __init__(self, repository: ArenaRepository, artifact_store: ArtifactStore, *, personal_project_id: str | None = None, replay_service: CounterfactualReplayService | None = None) -> None:
        self.repository = repository
        self.artifact_store = artifact_store
        self.personal_project_id = personal_project_id
        self.replays = replay_service or CounterfactualReplayService(repository, artifact_store, personal_project_id=personal_project_id)

    def _project(self, project_id: str | None) -> str:
        return self.replays._project(project_id)

    @staticmethod
    def _request(payload: Mapping[str, Any]) -> HarnessCIRequest:
        try:
            return HarnessCIRequest.model_validate(payload)
        except (TypeError, ValidationError, ValueError) as exc:
            raise HarnessCIError("harness_ci_request_invalid", "A strict base-versus-candidate Harness CI request is required.") from exc

    @staticmethod
    def _checks(replay: CounterfactualReplayReport, request: HarnessCIRequest) -> list[dict[str, str]]:
        policy, semantic = request.policy, semantic_code_to_mechanisms(request.source_changes)
        normalized = re.sub(r"[^a-z0-9]+", "_", replay.intervention.mechanism_id).strip("_")
        checks: list[dict[str, str]] = []
        if semantic["classification_state"] == "multiple":
            checks.append(_check("single_mechanism", "FAIL", "Semantic diff indicates multiple mechanism classes."))
        elif semantic["classification_state"] != "observed" or semantic["affected_mechanisms"] != [normalized]:
            checks.append(_check("single_mechanism", "HOLD", "Semantic diff does not establish exactly the declared intervention."))
        else:
            checks.append(_check("single_mechanism", "PASS", "Semantic diff matches exactly one declared intervention."))
        checks.append(_check("new_severe_failures", "FAIL" if replay.new_severe_failures and policy.fail_on_new_severe_failures else "HOLD" if replay.new_severe_failures else "PASS", "New severe failures: " + ", ".join(replay.new_severe_failures) if replay.new_severe_failures else "No newly recorded severe failures."))
        effects = {effect.metric: effect for effect in replay.effects}
        quality = effects["quality"]
        checks.append(_check("quality_regression", "HOLD" if quality.point_estimate is None else "FAIL" if quality.point_estimate < -policy.max_quality_regression else "PASS", "Quality effect is unknown." if quality.point_estimate is None else "Candidate quality regression exceeds the ceiling." if quality.point_estimate < -policy.max_quality_regression else "Quality is within the configured regression ceiling."))
        unknown = "FAIL" if policy.unknown_usage == "fail" else "HOLD"
        cost = effects["cost_usd"]
        if replay.usage_state == "unknown" or cost.point_estimate is None:
            checks.extend((_check("usage", unknown, "Usage and cost are unknown; unknown is never treated as zero."), _check("cost_ceiling", unknown, "Cost ceiling cannot be evaluated without complete provider usage.")))
        else:
            ratio = math.inf if cost.base_mean == 0 and cost.point_estimate > 0 else cost.point_estimate / (cost.base_mean or 1)
            checks.extend((_check("usage", "PASS", "Complete provider usage and price-catalog bindings are present."), _check("cost_ceiling", "FAIL" if ratio > policy.max_cost_increase_ratio else "PASS", "Candidate cost increase exceeds the ceiling." if ratio > policy.max_cost_increase_ratio else "Cost increase is within the configured ceiling.")))
        latency = effects["latency_ms"]
        if latency.point_estimate is None:
            checks.append(_check("latency_ceiling", "HOLD", "Latency ceiling cannot be evaluated from incomplete timing evidence."))
        else:
            ratio = math.inf if latency.base_mean == 0 and latency.point_estimate > 0 else latency.point_estimate / (latency.base_mean or 1)
            checks.append(_check("latency_ceiling", "FAIL" if ratio > policy.max_latency_increase_ratio else "PASS", "Candidate latency increase exceeds the ceiling." if ratio > policy.max_latency_increase_ratio else "Latency increase is within the configured ceiling."))
        checks.append(_check("required_cohorts", "HOLD" if "holdout" in policy.required_cohorts else "PASS", "No holdout result is promoted from a declaration." if "holdout" in policy.required_cohorts else "Declared development paired items satisfy the policy."))
        mature = _MATURITY_ORDER[replay.evidence_maturity] >= _MATURITY_ORDER[policy.required_evidence_maturity]
        checks.append(_check("evidence_maturity", "HOLD" if not mature or (replay.mode == "fixture" and not policy.allow_fixture_evidence) else "PASS", "Evidence maturity does not satisfy policy." if not mature else "Fixture evidence is disallowed by policy." if replay.mode == "fixture" and not policy.allow_fixture_evidence else "Evidence maturity satisfies the bounded policy."))
        checks.append(_check("statistical_adequacy", "HOLD" if replay.pair_count < policy.minimum_paired_repetitions or quality.ci95_low is None else "PASS", "Repeat-based paired uncertainty is unavailable." if replay.pair_count < policy.minimum_paired_repetitions or quality.ci95_low is None else "Repeat-based paired uncertainty is available."))
        checks.append(_check("fidelity", "HOLD" if replay.fidelity_level is None or _FIDELITY_ORDER[replay.fidelity_level] < _FIDELITY_ORDER[policy.minimum_fidelity] else "PASS", "Intervention fidelity is missing or below policy." if replay.fidelity_level is None or _FIDELITY_ORDER[replay.fidelity_level] < _FIDELITY_ORDER[policy.minimum_fidelity] else "Fidelity meets policy."))
        checks.append(_check("process_safety", "FAIL" if policy.require_process_safety and replay.process_safety == "fail" else "HOLD" if policy.require_process_safety and replay.process_safety == "unknown" else "PASS", "A process-safety control failed." if replay.process_safety == "fail" else "Process-safety evidence is unknown." if replay.process_safety == "unknown" else "Process-safety controls satisfy policy."))
        return checks

    @staticmethod
    def _raw(replay: CounterfactualReplayReport, request: HarnessCIRequest) -> dict[str, Any]:
        if replay.report_digest != request.replay_report_digest:
            raise HarnessCIError("harness_ci_replay_mismatch", "Harness CI must bind the exact replay report being evaluated.")
        checks = HarnessCIService._checks(replay, request)
        verdict = "FAIL" if any(check["verdict"] == "FAIL" for check in checks) else "HOLD" if any(check["verdict"] == "HOLD" for check in checks) else "PASS"
        semantic = semantic_code_to_mechanisms(request.source_changes)
        command = "arena counterfactual-replay --input <replay-contract.json> && arena harness-ci --replay <replay-contract.json> --base <base.json> --candidate <candidate.json> --policy <policy.json>"
        summary = "\n".join((f"## Harness CI — {verdict}", "", f"- Replay: `{replay.report_digest}`", f"- Evidence maturity: `{replay.evidence_maturity}`", f"- Usage: `{replay.usage_state}`", f"- Fidelity: `{replay.fidelity_level or 'unknown'}`", "", "| Check | Verdict | Detail |", "| --- | --- | --- |", *(f"| {check['check_id']} | {check['verdict']} | {check['detail']} |" for check in checks), "", f"Reproduce: `{command}`", "", "Fixture and recorded reports are bounded evidence, not causal proof or model-performance claims."))
        return {"schema_version": "scaffold-arena.harness-ci-report/1", "replay_report_digest": replay.report_digest, "verdict": verdict, "checks": checks, "effects": [effect.model_dump(mode="json") for effect in replay.effects], "severe_failures": replay.new_severe_failures, "usage_state": replay.usage_state, "fidelity_level": replay.fidelity_level, "evidence_maturity": replay.evidence_maturity, "semantic_diff": semantic, "reproduction_command": command, "step_summary": summary, "pr_comment_body": summary, "claim_ceiling": _CI_CEILING, "provider_execution_started": False, "execution_started": False, "network_requested": False}

    @staticmethod
    def _public(raw: Mapping[str, Any], *, digest: str, idempotent: bool) -> dict[str, Any]:
        value = {**raw, "report_id": f"hci-{digest[:24]}", "report_digest": _prefixed(digest), "report_artifact_digest": _prefixed(digest), "idempotent_replay": idempotent}
        try:
            return HarnessCIReport.model_validate(value).model_dump(mode="json")
        except ValidationError as exc:
            raise HarnessCIError("harness_ci_report_invalid", "The Harness CI report could not be validated.", status_code=500) from exc

    def local_report(self, replay_payload: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
        replay = CounterfactualReplayReport.model_validate(self.replays.local_report(replay_payload))
        request = self._request({**payload, "replay_report_digest": replay.report_digest})
        raw = self._raw(replay, request)
        return self._public(raw, digest=hashlib.sha256(canonical_json(raw)).hexdigest(), idempotent=False)

    def create(self, payload: Mapping[str, Any], *, project_id: str | None) -> dict[str, Any]:
        project, request = self._project(project_id), self._request(payload)
        replay = CounterfactualReplayReport.model_validate(self.replays.report(request.replay_report_digest, project_id=project))
        raw = self._raw(replay, request)
        content, request_digest = canonical_json(raw), _canonical_digest(request)
        digest = hashlib.sha256(content).hexdigest()
        stored = self.artifact_store.put_bytes(content, media_type=_CI_MEDIA_TYPE, metadata={"kind": "harness-ci-report", "request_digest": request_digest})
        if stored != digest:
            raise HarnessCIError("harness_ci_artifact_integrity", "The Harness CI report could not be stored content-addressably.", status_code=500)
        with self.repository.transaction(immediate=True) as conn:
            prior = conn.execute(select(harness_ci_reports).where(harness_ci_reports.c.project_id == project, harness_ci_reports.c.request_digest == request_digest)).mappings().one_or_none()
            if prior is not None:
                if prior["report_artifact_digest"] != digest:
                    raise HarnessCIError("harness_ci_report_conflict", "An immutable Harness CI report already exists for this request.", status_code=409)
                return self._public(raw, digest=digest, idempotent=True)
            if conn.execute(select(artifacts.c.digest).where(artifacts.c.digest == digest)).scalar_one_or_none() is None:
                conn.execute(insert(artifacts).values(digest=digest, size_bytes=len(content), storage_uri=self.artifact_store.uri_for(digest), media_type=_CI_MEDIA_TYPE, metadata_json={"kind": "harness-ci-report", "request_digest": request_digest}))
            conn.execute(insert(harness_ci_reports).values(id=uuid.uuid4().hex, project_id=project, request_digest=request_digest, replay_report_digest=_bare(request.replay_report_digest, code="harness_ci_replay_invalid", message="A replay report digest is required."), report_artifact_digest=digest, verdict=raw["verdict"], claim_ceiling=raw["claim_ceiling"]))
        return self._public(raw, digest=digest, idempotent=False)

    def report(self, digest: str, *, project_id: str | None) -> dict[str, Any]:
        project = self._project(project_id)
        bare = _bare(digest, code="harness_ci_digest_invalid", message="A lowercase SHA-256 Harness CI report digest is required.")
        with self.repository.engine.connect() as conn:
            row = conn.execute(select(harness_ci_reports).where(harness_ci_reports.c.project_id == project, harness_ci_reports.c.report_artifact_digest == bare)).mappings().one_or_none()
        if row is None:
            raise HarnessCIError("harness_ci_report_not_found", "The requested Harness CI report was not found.", status_code=404)
        try:
            content = self.artifact_store.get_bytes(row["report_artifact_digest"])
            if hashlib.sha256(content).hexdigest() != row["report_artifact_digest"]:
                raise ValueError("digest mismatch")
            raw = json.loads(content)
            if not isinstance(raw, dict):
                raise ValueError("object required")
        except (ArtifactIntegrityError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise HarnessCIError("harness_ci_custody_unavailable", "The Harness CI report cannot be verified.", status_code=409) from exc
        return self._public(raw, digest=row["report_artifact_digest"], idempotent=False)
