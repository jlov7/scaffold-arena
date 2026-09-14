from __future__ import annotations

import asyncio
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import jsonschema


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run-benchmark-pack.py"
CONTROL_OUTPUT_EVALUATION_SHA256 = "01b39100b29f946dce5083b61aafb03c3234f7c73c0051b5e3deb1e242740e62"
SPEC = importlib.util.spec_from_file_location("run_benchmark_pack_fixture_metrics", SCRIPT)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


class FailingProvider:
    def get_last_usage(self):
        return None

    async def complete(self, *args, **kwargs):
        raise AssertionError("fixture mode must not invoke a provider")

    async def generate(self, *args, **kwargs):
        raise AssertionError("fixture mode must not invoke a provider")


class FixtureMetricsTests(unittest.TestCase):
    def test_fixture_mode_uses_no_provider_and_preserves_control_results(self) -> None:
        def fail_get_provider(*args, **kwargs):
            raise AssertionError("fixture mode must not construct a provider")

        with tempfile.TemporaryDirectory() as directory:
            temporary_root = Path(directory)
            original_judge_setting = runner.settings.enable_llm_judge
            try:
                with (
                    patch.object(runner, "NoJudgeProvider", FailingProvider),
                    patch.object(runner, "get_provider", fail_get_provider),
                    patch.object(
                        subprocess,
                        "run",
                        side_effect=AssertionError(
                            "fixture mode must not invoke Git or another subprocess"
                        ),
                    ),
                    patch.object(runner, "OUTPUT_DIR", temporary_root),
                    patch.object(runner, "RUN_DIR", temporary_root / "benchmark_runs"),
                    patch.object(runner, "SUMMARY_PATH", temporary_root / "benchmark_summary.json"),
                    patch.object(runner, "SEPARATION_PATH", temporary_root / "baseline_separation_report.json"),
                    patch.object(runner, "RESULTS_MD_PATH", temporary_root / "benchmark-results-v0.1.md"),
                ):
                    asyncio.run(runner.run_fixture_mode())
            finally:
                runner.settings.enable_llm_judge = original_judge_setting

            artifacts = [
                json.loads(path.read_text())
                for path in sorted((temporary_root / "benchmark_runs").glob("*.json"))
            ]
            self.assertEqual(len(artifacts), 54)
            for artifact in artifacts:
                self.assertEqual(artifact["model_id"], runner.FIXTURE_MODEL_ID)
                self.assertEqual(
                    artifact["metrics"],
                    {
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cost_usd": 0.0,
                        "wall_time_ms": None,
                        "num_api_calls": 0,
                        "provider_usage_status": "known_none_no_provider_invoked",
                        "measurement_scope": "fixture_deterministic_controls",
                        "latency_status": "not_measured",
                    },
                )
            self.assertEqual(self._control_digest(artifacts), CONTROL_OUTPUT_EVALUATION_SHA256)

    def test_fixture_artifact_is_byte_deterministic(self) -> None:
        case = runner.all_cases()[0]
        first = asyncio.run(runner._evaluate_case(case, 1))
        second = asyncio.run(runner._evaluate_case(case, 1))
        self.assertEqual(self._canonical_bytes(first), self._canonical_bytes(second))

    def test_live_default_model_identity_is_unchanged(self) -> None:
        captured: dict[str, object] = {}

        async def fake_run_live_mode(**kwargs):
            captured.update(kwargs)

        with patch.object(runner, "run_live_mode", fake_run_live_mode), patch.object(
            sys, "argv", ["run-benchmark-pack.py", "--mode", "live"]
        ):
            self.assertEqual(runner.main(), 0)

        self.assertEqual(runner.LIVE_MODEL_ID, "claude-haiku-4-5")
        self.assertEqual(captured["model_id"], "claude-haiku-4-5")

    def test_schema_allows_null_latency_only_for_fixture_artifacts(self) -> None:
        schema = json.loads((ROOT / "specs/run-artifact.schema.json").read_text())
        fixture = asyncio.run(runner._evaluate_case(runner.all_cases()[0], 1))
        validator = jsonschema.Draft7Validator(schema)
        self.assertEqual(list(validator.iter_errors(fixture)), [])

        live = copy.deepcopy(fixture)
        live["mode"] = "live"
        live["model_id"] = runner.LIVE_MODEL_ID
        live["metrics"] = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": 0.0,
            "wall_time_ms": 0,
            "num_api_calls": 0,
        }
        self.assertEqual(list(validator.iter_errors(live)), [])

        live["metrics"]["wall_time_ms"] = None
        self.assertNotEqual(list(validator.iter_errors(live)), [])

    def _control_digest(self, artifacts: list[dict[str, object]]) -> str:
        controls = {
            str(artifact["run_id"]): {
                "output": artifact["output"],
                "evaluation": artifact["evaluation"],
            }
            for artifact in artifacts
        }
        return hashlib.sha256(
            json.dumps(controls, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def _canonical_bytes(self, artifact: dict[str, object]) -> bytes:
        return json.dumps(artifact, sort_keys=True, separators=(",", ":")).encode()


if __name__ == "__main__":
    unittest.main()
