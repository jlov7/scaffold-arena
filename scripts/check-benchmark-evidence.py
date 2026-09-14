#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "outputs/benchmark_runs"
SUMMARY_PATH = ROOT / "outputs/benchmark_summary.json"
SEPARATION_PATH = ROOT / "outputs/baseline_separation_report.json"
RESULTS_MD_PATH = ROOT / "docs/reviews/benchmark-results-v0.1.md"
SCENARIO_SCHEMA_PATH = ROOT / "specs/scenario.schema.json"
SCENARIO_PACK_PATH = ROOT / "docs/benchmarking/scenario_pack_v0.1.json"

REQUIRED_FAMILIES = {"extraction", "risk", "research", "tool_use", "privacy", "strategy"}
REQUIRED_ABLATIONS = {"bare", "schema_only", "plan_only", "retry_only", "full_scaffold"}
MIN_SCENARIOS_PER_FAMILY = 3


def _load(path: Path):
    return json.loads(path.read_text())


def _validate_scenario_pack(run_files: list[Path]) -> list[str]:
    errors: list[str] = []
    if not SCENARIO_PACK_PATH.exists():
        return [f"missing scenario pack: {SCENARIO_PACK_PATH.relative_to(ROOT)}"]
    if not SCENARIO_SCHEMA_PATH.exists():
        return [f"missing scenario schema: {SCENARIO_SCHEMA_PATH.relative_to(ROOT)}"]

    schema = _load(SCENARIO_SCHEMA_PATH)
    pack = _load(SCENARIO_PACK_PATH)
    scenarios = pack.get("scenarios", [])
    if pack.get("status") != "fixture_scenario_contract_not_live_provider_results":
        errors.append("scenario pack status must state that it is not live provider evidence")
    if not isinstance(scenarios, list):
        return errors + ["scenario pack scenarios must be a list"]

    scenario_ids: set[str] = set()
    family_counts = {family: 0 for family in REQUIRED_FAMILIES}
    positive_by_family = {family: 0 for family in REQUIRED_FAMILIES}
    negative_by_family = {family: 0 for family in REQUIRED_FAMILIES}
    for index, scenario in enumerate(scenarios):
        try:
            jsonschema.validate(instance=scenario, schema=schema)
        except jsonschema.ValidationError as exc:
            errors.append(f"scenario_pack_v0.1.json scenario[{index}]: {exc.message}")
            continue

        scenario_id = str(scenario.get("scenario_id", ""))
        task_family = str(scenario.get("task_family", ""))
        if scenario_id in scenario_ids:
            errors.append(f"duplicate scenario id: {scenario_id}")
        scenario_ids.add(scenario_id)
        if task_family in family_counts:
            family_counts[task_family] += 1
            gold = scenario.get("gold_reference", {})
            control_type = gold.get("control_type") if isinstance(gold, dict) else None
            if control_type == "positive":
                positive_by_family[task_family] += 1
            elif control_type == "negative":
                negative_by_family[task_family] += 1

        metric_weight = sum(
            float(metric.get("weight", 0))
            for metric in scenario.get("deterministic_metrics", [])
            if isinstance(metric, dict)
        )
        if metric_weight < 0.7:
            errors.append(f"{scenario_id}: deterministic metric weight below 0.70")
        if metric_weight > 1.000001:
            errors.append(f"{scenario_id}: deterministic metric weights sum above 1.0")

        limitations = " ".join(str(item).lower() for item in scenario.get("limitations", []))
        if "not a live provider result" not in limitations:
            errors.append(f"{scenario_id}: limitations must state that it is not a live provider result")

    missing_families = REQUIRED_FAMILIES - set(family_counts)
    if missing_families:
        errors.append(f"scenario pack missing task families: {sorted(missing_families)}")
    for family in REQUIRED_FAMILIES:
        if family_counts[family] < MIN_SCENARIOS_PER_FAMILY:
            errors.append(f"{family}: scenario pack needs at least {MIN_SCENARIOS_PER_FAMILY} scenarios")
        if positive_by_family[family] < 1:
            errors.append(f"{family}: scenario pack needs at least one positive control")
        if negative_by_family[family] < 2:
            errors.append(f"{family}: scenario pack needs at least two negative controls")

    run_scenario_ids = {str(_load(path).get("scenario_id", "")) for path in run_files}
    missing_run_scenarios = run_scenario_ids - scenario_ids
    if missing_run_scenarios:
        errors.append(f"scenario pack missing run scenario ids: {sorted(missing_run_scenarios)}")

    return errors


def main() -> int:
    errors: list[str] = []
    run_files = sorted(RUN_DIR.glob("*.json")) if RUN_DIR.exists() else []
    if len(run_files) < 54:
        errors.append(f"expected at least 54 benchmark run artifacts, found {len(run_files)}")
    for path in [SUMMARY_PATH, SEPARATION_PATH, RESULTS_MD_PATH, SCENARIO_PACK_PATH]:
        if not path.exists():
            errors.append(f"missing benchmark evidence file: {path.relative_to(ROOT)}")

    if not errors:
        summary = _load(SUMMARY_PATH)
        separation = _load(SEPARATION_PATH)
        families = set(summary.get("task_families", []))
        ablations = set(summary.get("scaffolds_or_ablation_labels", []))
        if REQUIRED_FAMILIES - families:
            errors.append(f"summary missing task families: {sorted(REQUIRED_FAMILIES - families)}")
        if REQUIRED_ABLATIONS - ablations:
            errors.append(f"summary missing ablation labels: {sorted(REQUIRED_ABLATIONS - ablations)}")
        if int(summary.get("repeat_count", 0)) < 3:
            errors.append("summary repeat_count must be at least 3")
        if "score_ci95" not in summary:
            errors.append("summary missing score_ci95")
        if not separation.get("all_families_pass"):
            errors.append("baseline separation report did not pass for all families")
        for row in separation.get("families", []):
            if float(row.get("separation_points", 0)) < 20:
                errors.append(f"{row.get('task_family')}: separation below 20 points")
        errors.extend(_validate_scenario_pack(run_files))

    if errors:
        for error in errors:
            print(f"[benchmark-evidence] FAIL: {error}", file=sys.stderr)
        return 1
    scenario_count = len(_load(SCENARIO_PACK_PATH).get("scenarios", []))
    print(f"[benchmark-evidence] checked {len(run_files)} benchmark run artifacts and {scenario_count} scenario contracts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
