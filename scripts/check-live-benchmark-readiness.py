#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from config.models import MODEL_REGISTRY, get_model

OUTPUT_PATH = ROOT / "outputs/live_benchmark_preflight.json"
FIXTURE_RUN_DIR = ROOT / "outputs/benchmark_runs"
DEFAULT_MODEL_ID = "claude-haiku-4-5"
DEFAULT_TASKS = ["extraction", "risk", "research", "tool_use", "privacy", "strategy"]
DEFAULT_SCAFFOLDS = ["bare", "plan_execute_verify", "tool_error_recovery", "memory_critique"]
DEFAULT_REPEATS = 3
PROVIDER_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


def _load_run_benchmark_module() -> Any:
    path = ROOT / "scripts/run-benchmark-pack.py"
    spec = importlib.util.spec_from_file_location("run_benchmark_pack", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path.relative_to(ROOT)}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_benchmark_pack"] = module
    spec.loader.exec_module(module)
    return module


def _dump_json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, sort_keys=False) + "\n"


def _fixture_usage_estimate() -> dict[str, Any]:
    run_files = sorted(FIXTURE_RUN_DIR.glob("*.json")) if FIXTURE_RUN_DIR.exists() else []
    return {
        "source": "Deterministic fixture controls have no observed provider usage and cannot estimate live cost.",
        "status": "unavailable_no_provider_usage",
        "fixture_run_count": len(run_files),
        "estimated_input_tokens": None,
        "estimated_output_tokens": None,
        "estimated_cost_usd": None,
        "limitations": [
            "Deterministic fixture controls invoke no provider, so they contain no observed provider usage.",
            "Live token and cost estimates are unavailable until provider-backed measurements exist.",
        ],
    }


def build_preflight() -> dict[str, Any]:
    module = _load_run_benchmark_module()
    tasks = module.task_pack()
    scaffolds = module.scaffold_pack()
    selected_tasks = [task for task in DEFAULT_TASKS if task in tasks]
    selected_scaffolds = [scaffold for scaffold in DEFAULT_SCAFFOLDS if scaffold in scaffolds]
    missing_tasks = sorted(set(DEFAULT_TASKS) - set(selected_tasks))
    missing_scaffolds = sorted(set(DEFAULT_SCAFFOLDS) - set(selected_scaffolds))
    model = get_model(DEFAULT_MODEL_ID)
    expected_run_count = len(selected_tasks) * len(selected_scaffolds) * DEFAULT_REPEATS
    provider_key_env = PROVIDER_KEY_ENV[model.provider]
    command = [
        "uv",
        "run",
        "--project",
        "backend",
        "python",
        "scripts/run-benchmark-pack.py",
        "--mode",
        "live",
        "--model-id",
        DEFAULT_MODEL_ID,
        "--tasks",
        ",".join(selected_tasks),
        "--scaffolds",
        ",".join(selected_scaffolds),
        "--repeats",
        str(DEFAULT_REPEATS),
    ]
    blockers = []
    if missing_tasks:
        blockers.append(f"Missing task ids: {', '.join(missing_tasks)}")
    if missing_scaffolds:
        blockers.append(f"Missing scaffold ids: {', '.join(missing_scaffolds)}")
    blockers.extend(
        [
            f"Set a valid {provider_key_env}; static preflight does not verify key validity.",
            "Run the live benchmark command and commit raw outputs/live_benchmark_runs artifacts.",
            "Inspect outputs/live_benchmark_summary.json for repeated-trial variance and confidence intervals.",
            "Follow with independent human annotations and external reproduction before lifting strict rubric caps.",
        ]
    )
    return {
        "schema_version": "0.1",
        "generated_at": "2026-05-23T00:00:00Z",
        "status": "static_live_benchmark_preflight_not_live_evidence",
        "model": {
            "model_id": model.id,
            "label": model.label,
            "provider": model.provider,
            "provider_key_env": provider_key_env,
            "pricing_source": "backend/config/models.py",
        },
        "task_ids": selected_tasks,
        "scaffold_ids": selected_scaffolds,
        "repeat_count": DEFAULT_REPEATS,
        "expected_run_count": expected_run_count,
        "expected_outputs": {
            "run_dir": "outputs/live_benchmark_runs",
            "summary": "outputs/live_benchmark_summary.json",
        },
        "command": command,
        "command_display": " ".join(command),
        "fixture_usage_estimate": _fixture_usage_estimate(),
        "model_registry_size": len(MODEL_REGISTRY),
        "blockers_before_95": blockers,
        "claim_boundary": (
            "This preflight proves that the live benchmark plan is wired and reproducible. "
            "It is not live model evidence and does not remove the strict frontier rubric cap."
        ),
        "limitations": [
            "No provider request is made by this static check.",
            "Provider key presence and validity are intentionally not written into this release artifact.",
            "Live benchmark results must be generated separately and labeled mode=live.",
        ],
    }


def _validate_preflight(preflight: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if preflight.get("status") != "static_live_benchmark_preflight_not_live_evidence":
        errors.append("preflight status must state that it is not live evidence")
    task_ids = preflight.get("task_ids", [])
    scaffold_ids = preflight.get("scaffold_ids", [])
    expected = len(task_ids) * len(scaffold_ids) * int(preflight.get("repeat_count", 0))
    if preflight.get("expected_run_count") != expected:
        errors.append("expected_run_count does not match tasks * scaffolds * repeats")
    if expected < 72:
        errors.append(f"expected at least 72 live run artifacts, found plan for {expected}")
    usage_estimate = preflight.get("fixture_usage_estimate", {})
    if usage_estimate.get("status") != "unavailable_no_provider_usage":
        errors.append("fixture usage estimate must state unavailable_no_provider_usage")
    for field in ["estimated_input_tokens", "estimated_output_tokens", "estimated_cost_usd"]:
        if field not in usage_estimate or usage_estimate[field] is not None:
            errors.append(f"fixture usage estimate {field} must be null without provider usage")
    if "no observed provider usage" not in str(usage_estimate.get("source", "")).lower():
        errors.append("fixture usage estimate source must state that provider usage was not observed")
    command_display = str(preflight.get("command_display", ""))
    for required in ["--mode live", "--repeats 3", "--model-id claude-haiku-4-5"]:
        if required not in command_display:
            errors.append(f"live command missing {required}")
    text = json.dumps(preflight).lower()
    if "not live evidence" not in text and "not live model evidence" not in text:
        errors.append("preflight must preserve the non-evidence claim boundary")
    if "api_key" in text and "provider_key_env" not in text:
        errors.append("preflight must not contain raw API key fields")
    return errors


def _check_file() -> list[str]:
    expected = _dump_json(build_preflight())
    current = OUTPUT_PATH.read_text() if OUTPUT_PATH.exists() else ""
    if current != expected:
        return [f"{OUTPUT_PATH.relative_to(ROOT)} is stale"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or check static live benchmark readiness.")
    parser.add_argument("--write", action="store_true", help="Write the preflight artifact.")
    parser.add_argument("--check", action="store_true", help="Fail if the preflight artifact is stale.")
    args = parser.parse_args()

    preflight = build_preflight()
    if args.write:
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(_dump_json(preflight))
        print(f"[live-preflight] wrote {OUTPUT_PATH.relative_to(ROOT)}")
        return 0

    errors = _validate_preflight(preflight)
    if args.check:
        errors.extend(_check_file())

    if errors:
        for error in errors:
            print(f"[live-preflight] FAIL: {error}", file=sys.stderr)
        return 1

    print(
        "[live-preflight] checked "
        f"{preflight['expected_run_count']} planned live runs; provider={preflight['model']['provider']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
