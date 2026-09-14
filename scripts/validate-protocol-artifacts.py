#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import jsonschema

ROOT = Path(__file__).resolve().parents[1]

ARTIFACTS = [
    ("specs/scenario.schema.json", "docs/benchmarking/sample_scenario.json"),
    ("specs/run-artifact.schema.json", "docs/benchmarking/sample_run_artifact.json"),
    ("specs/eval-card.schema.json", "docs/benchmarking/sample_eval_card.json"),
    ("specs/scaffold-card.schema.json", "docs/benchmarking/sample_scaffold_card.json"),
    ("specs/failure-taxonomy.schema.json", "docs/benchmarking/failure_taxonomy.json"),
    # The 1-5 sample is retained only as a Protocol-v0.1 compatibility fixture.
    ("specs/annotation.schema.json", "docs/benchmarking/sample_annotation.json"),
    ("specs/external-validation.schema.json", "outputs/external_validation.json"),
]
V1_SCHEMAS = [
    "specs/v1/review-v1-calibration-annotation-result.schema.json",
    "specs/v1/review-v1-calibration-adjudication-result.schema.json",
]


def _load_json(relative_path: str) -> Any:
    return json.loads((ROOT / relative_path).read_text())


def _validate_weight_sum(artifact_path: str, artifact: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    metrics = artifact.get("metrics") or artifact.get("deterministic_metrics") or []
    if not isinstance(metrics, list):
        return errors
    total = sum(float(metric.get("weight", 0)) for metric in metrics if isinstance(metric, dict))
    if total > 1.000001:
        errors.append(f"{artifact_path}: metric weights sum to {total:.3f}, expected <= 1.0")
    return errors


def _validate_run_cost(artifact_path: str, artifact: dict[str, Any]) -> list[str]:
    metrics = artifact.get("metrics")
    if not isinstance(metrics, dict):
        return []
    tokens = float(metrics.get("input_tokens", 0)) + float(metrics.get("output_tokens", 0))
    cost = float(metrics.get("cost_usd", 0))
    if tokens > 0 and cost <= 0:
        return [f"{artifact_path}: token usage is non-zero but cost_usd is not positive"]
    return []


def main() -> int:
    errors: list[str] = []
    for schema_path, artifact_path in ARTIFACTS:
        schema = _load_json(schema_path)
        artifact = _load_json(artifact_path)
        try:
            jsonschema.Draft7Validator.check_schema(schema)
            jsonschema.validate(instance=artifact, schema=schema)
        except jsonschema.ValidationError as exc:
            errors.append(f"{artifact_path}: {exc.message}")
        except jsonschema.SchemaError as exc:
            errors.append(f"{schema_path}: invalid schema: {exc.message}")
        if isinstance(artifact, dict):
            errors.extend(_validate_weight_sum(artifact_path, artifact))
            errors.extend(_validate_run_cost(artifact_path, artifact))

    for schema_path in V1_SCHEMAS:
        try:
            jsonschema.Draft202012Validator.check_schema(_load_json(schema_path))
        except jsonschema.SchemaError as exc:
            errors.append(f"{schema_path}: invalid Protocol-v1 schema: {exc.message}")

    if errors:
        for error in errors:
            print(f"[protocol] FAIL: {error}", file=sys.stderr)
        return 1

    print(f"[protocol] validated {len(ARTIFACTS)} protocol artifacts and {len(V1_SCHEMAS)} Protocol-v1 review schemas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
