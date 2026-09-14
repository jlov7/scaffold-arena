#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from pathlib import Path
from typing import Any

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "outputs/benchmark_runs"
RUN_SCHEMA_PATH = ROOT / "specs/run-artifact.schema.json"
STAT_AUDIT_PATH = ROOT / "outputs/statistical_audit.json"
STAT_REPORT_PATH = ROOT / "docs/reviews/statistical-audit-v0.1.md"
EXTERNAL_SCHEMA_PATH = ROOT / "specs/external-validation.schema.json"
EXTERNAL_LEDGER_PATH = ROOT / "outputs/external_validation.json"

REQUIRED_FAMILIES = {"extraction", "risk", "research", "tool_use", "privacy", "strategy"}
BOOTSTRAP_SEED = 20260523
BOOTSTRAP_SAMPLES = 2000


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def _mean(values: list[float]) -> float:
    return sum(values) / max(1, len(values))


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return statistics.stdev(values)


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = round(q * (len(ordered) - 1))
    return ordered[max(0, min(len(ordered) - 1, index))]


def _bootstrap_ci95(positive: list[float], negative: list[float]) -> dict[str, float]:
    if not positive or not negative:
        return {"low": 0.0, "high": 0.0}
    rng = random.Random(BOOTSTRAP_SEED)
    samples: list[float] = []
    for _ in range(BOOTSTRAP_SAMPLES):
        pos_sample = [rng.choice(positive) for _ in positive]
        neg_sample = [rng.choice(negative) for _ in negative]
        samples.append(_mean(pos_sample) - _mean(neg_sample))
    return {
        "low": round(_quantile(samples, 0.025), 2),
        "high": round(_quantile(samples, 0.975), 2),
    }


def _cohen_d(positive: list[float], negative: list[float]) -> float | None:
    if len(positive) < 2 or len(negative) < 2:
        return None
    pos_sd = _stdev(positive)
    neg_sd = _stdev(negative)
    denom_n = len(positive) + len(negative) - 2
    if denom_n <= 0:
        return None
    pooled = math.sqrt(((len(positive) - 1) * pos_sd**2 + (len(negative) - 1) * neg_sd**2) / denom_n)
    if pooled == 0:
        return None
    return round((_mean(positive) - _mean(negative)) / pooled, 3)


def _probability_superiority(positive: list[float], negative: list[float]) -> float:
    if not positive or not negative:
        return 0.0
    wins = 0.0
    total = 0
    for pos in positive:
        for neg in negative:
            total += 1
            if pos > neg:
                wins += 1.0
            elif pos == neg:
                wins += 0.5
    return round(wins / total, 4)


def _validate_fixture_artifacts() -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    runs: list[dict[str, Any]] = []
    schema = _load_json(RUN_SCHEMA_PATH)
    try:
        jsonschema.Draft7Validator.check_schema(schema)
    except jsonschema.SchemaError as exc:
        return [], [f"{RUN_SCHEMA_PATH.relative_to(ROOT)}: invalid schema: {exc.message}"]

    run_files = sorted(RUN_DIR.glob("*.json")) if RUN_DIR.exists() else []
    if len(run_files) < 54:
        errors.append(f"expected at least 54 fixture run artifacts, found {len(run_files)}")

    for path in run_files:
        artifact = _load_json(path)
        relative = str(path.relative_to(ROOT))
        try:
            jsonschema.validate(instance=artifact, schema=schema)
        except jsonschema.ValidationError as exc:
            errors.append(f"{relative}: schema validation failed: {exc.message}")
            continue

        if artifact.get("mode") != "fixture":
            errors.append(f"{relative}: benchmark_runs artifact must have mode=fixture")
        if artifact.get("evidence", [{}])[0].get("kind") != "fixture_control":
            errors.append(f"{relative}: fixture artifact must include fixture_control evidence")
        limitations = " ".join(str(item).lower() for item in artifact.get("limitations", []))
        if "not a live provider run" not in limitations or "live mode" not in limitations:
            errors.append(f"{relative}: limitations must explicitly separate fixture evidence from live mode")
        metrics = artifact.get("metrics", {})
        tokens = float(metrics.get("input_tokens", 0)) + float(metrics.get("output_tokens", 0))
        if tokens > 0 and float(metrics.get("cost_usd", 0)) <= 0:
            errors.append(f"{relative}: token usage is non-zero but cost_usd is not positive")
        if float(artifact.get("evaluation", {}).get("deterministic_weight", 0)) < 0.7:
            errors.append(f"{relative}: deterministic_weight is below the protocol floor")
        runs.append(artifact)

    return runs, errors


def _build_statistical_audit(runs: list[dict[str, Any]]) -> dict[str, Any]:
    families = sorted({str(run.get("task_family")) for run in runs})
    rows: list[dict[str, Any]] = []
    for family in families:
        family_runs = [run for run in runs if run.get("task_family") == family]
        positive = [
            float(run["evaluation"]["total_score"])
            for run in family_runs
            if run.get("expected_role") == "positive"
        ]
        negative = [
            float(run["evaluation"]["total_score"])
            for run in family_runs
            if run.get("expected_role") == "negative"
        ]
        separation = _mean(positive) - _mean(negative)
        ci95 = _bootstrap_ci95(positive, negative)
        rows.append(
            {
                "task_family": family,
                "positive_n": len(positive),
                "negative_n": len(negative),
                "positive_mean": round(_mean(positive), 2),
                "negative_mean": round(_mean(negative), 2),
                "separation_points": round(separation, 2),
                "bootstrap_ci95": ci95,
                "cohen_d": _cohen_d(positive, negative),
                "probability_superiority": _probability_superiority(positive, negative),
                "passes_minimum": separation >= 20 and ci95["low"] >= 20,
            }
        )

    return {
        "schema_version": "0.1",
        "generated_at": "2026-05-23T00:00:00Z",
        "mode": "fixture_statistical_audit",
        "run_count": len(runs),
        "task_families": families,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "bootstrap_samples": BOOTSTRAP_SAMPLES,
        "minimum_required_separation_points": 20,
        "all_families_pass": bool(rows) and all(row["passes_minimum"] for row in rows),
        "families": rows,
        "limitations": [
            "This is a statistical audit of deterministic fixture controls, not live provider/model performance.",
            "It checks whether known-good and known-bad artifacts are separable before live benchmark claims are allowed.",
        ],
    }


def _render_statistical_report(audit: dict[str, Any]) -> str:
    lines = [
        "# Statistical Audit v0.1",
        "",
        "Date: 2026-05-23",
        "",
        "This report audits deterministic fixture controls. It does not contain live provider benchmark results.",
        "",
        "## Summary",
        "",
        f"- Run artifacts: {audit['run_count']}",
        f"- Task families: {', '.join(audit['task_families'])}",
        f"- Bootstrap seed: {audit['bootstrap_seed']}",
        f"- Bootstrap samples per family: {audit['bootstrap_samples']}",
        f"- Minimum required separation: {audit['minimum_required_separation_points']} points",
        f"- All families pass: {'yes' if audit['all_families_pass'] else 'no'}",
        "",
        "## Fixture Separation",
        "",
        "| Task family | Positive n | Negative n | Positive mean | Negative mean | Separation | Bootstrap 95% CI | Probability superiority | Pass |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- |",
    ]
    for row in audit["families"]:
        ci = row["bootstrap_ci95"]
        lines.append(
            f"| {row['task_family']} | {row['positive_n']} | {row['negative_n']} | "
            f"{row['positive_mean']} | {row['negative_mean']} | {row['separation_points']} | "
            f"{ci['low']} to {ci['high']} | {row['probability_superiority']} | "
            f"{'yes' if row['passes_minimum'] else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Claim Boundary",
            "",
            "A pass here means the scoring machinery separates seeded fixture controls. It does not prove that any scaffold beats another scaffold in live model use. The strict frontier rubric remains capped until live provider runs, live ablations, human calibration, and independent reproduction exist.",
            "",
        ]
    )
    return "\n".join(lines)


def _validate_external_ledger() -> list[str]:
    errors: list[str] = []
    schema = _load_json(EXTERNAL_SCHEMA_PATH)
    ledger = _load_json(EXTERNAL_LEDGER_PATH)
    try:
        jsonschema.Draft7Validator.check_schema(schema)
        jsonschema.validate(instance=ledger, schema=schema)
    except jsonschema.ValidationError as exc:
        return [f"{EXTERNAL_LEDGER_PATH.relative_to(ROOT)}: schema validation failed: {exc.message}"]
    except jsonschema.SchemaError as exc:
        return [f"{EXTERNAL_SCHEMA_PATH.relative_to(ROOT)}: invalid schema: {exc.message}"]

    evidence_count = (
        len(ledger.get("independent_reproductions", []))
        + len(ledger.get("public_critiques", []))
        + len(ledger.get("human_annotation_batches", []))
    )
    if evidence_count == 0 and ledger.get("status") != "no_external_validation_completed":
        errors.append("external validation ledger claims completion with zero evidence records")
    if evidence_count > 0 and ledger.get("status") != "external_validation_completed":
        errors.append("external validation ledger contains evidence but status is not completed")
    return errors


def _write_outputs(audit: dict[str, Any]) -> None:
    STAT_AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    STAT_AUDIT_PATH.write_text(json.dumps(audit, indent=2) + "\n")
    STAT_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    STAT_REPORT_PATH.write_text(_render_statistical_report(audit))


def _check_outputs(audit: dict[str, Any]) -> list[str]:
    expected_json = json.dumps(audit, indent=2) + "\n"
    expected_md = _render_statistical_report(audit)
    errors: list[str] = []
    if not STAT_AUDIT_PATH.exists() or STAT_AUDIT_PATH.read_text() != expected_json:
        errors.append(f"{STAT_AUDIT_PATH.relative_to(ROOT)} is stale; rerun scripts/validate-research-integrity.py --write")
    if not STAT_REPORT_PATH.exists() or STAT_REPORT_PATH.read_text() != expected_md:
        errors.append(f"{STAT_REPORT_PATH.relative_to(ROOT)} is stale; rerun scripts/validate-research-integrity.py --write")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate benchmark research integrity surfaces.")
    parser.add_argument("--write", action="store_true", help="Regenerate statistical audit outputs.")
    args = parser.parse_args()

    runs, errors = _validate_fixture_artifacts()
    if runs:
        families = {str(run.get("task_family")) for run in runs}
        missing = REQUIRED_FAMILIES - families
        if missing:
            errors.append(f"benchmark artifacts missing task families: {sorted(missing)}")
    audit = _build_statistical_audit(runs)
    if not audit["all_families_pass"]:
        errors.append("statistical audit did not pass for every task family")
    errors.extend(_validate_external_ledger())

    if args.write:
        _write_outputs(audit)
    else:
        errors.extend(_check_outputs(audit))

    if errors:
        for error in errors:
            print(f"[research-integrity] FAIL: {error}", file=sys.stderr)
        return 1
    print(
        f"[research-integrity] checked {len(runs)} run artifacts; "
        f"statistical audit pass={audit['all_families_pass']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
