from __future__ import annotations

import copy
import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check-live-benchmark-readiness.py"
SPEC = importlib.util.spec_from_file_location("live_benchmark_readiness", SCRIPT)
assert SPEC and SPEC.loader
readiness = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = readiness
SPEC.loader.exec_module(readiness)


class LiveBenchmarkReadinessTests(unittest.TestCase):
    def test_fixture_controls_do_not_create_a_free_live_cost_estimate(self) -> None:
        preflight = readiness.build_preflight()
        estimate = preflight["fixture_usage_estimate"]

        self.assertEqual(estimate["status"], "unavailable_no_provider_usage")
        self.assertIsNone(estimate["estimated_input_tokens"])
        self.assertIsNone(estimate["estimated_output_tokens"])
        self.assertIsNone(estimate["estimated_cost_usd"])
        self.assertIn("no observed provider usage", estimate["source"].lower())
        self.assertEqual(readiness._validate_preflight(preflight), [])

        missing_cost = copy.deepcopy(preflight)
        del missing_cost["fixture_usage_estimate"]["estimated_cost_usd"]
        self.assertTrue(
            any(
                "estimated_cost_usd must be null" in error
                for error in readiness._validate_preflight(missing_cost)
            )
        )


if __name__ == "__main__":
    unittest.main()
