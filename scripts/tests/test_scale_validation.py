from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "scale_validation", ROOT / "scripts/scale/validate_v1_scale.py"
)
assert SPEC and SPEC.loader
scale = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = scale
SPEC.loader.exec_module(scale)


class ScaleValidationTests(unittest.TestCase):
    def test_declared_arithmetic_and_boundaries(self) -> None:
        config = scale.ScaleConfig(50_000, 10_000_000, 1_000)
        report = scale.validate_scale(config)
        self.assertEqual(report["batching"]["attempt_batches"], 50)
        self.assertEqual(report["batching"]["event_batches"], 10_000)
        self.assertEqual(report["batching"]["events_per_attempt"], 200)
        self.assertEqual(scale.event_coordinates(config, 1), (0, 1))
        self.assertEqual(scale.event_coordinates(config, 200), (0, 200))
        self.assertEqual(scale.event_coordinates(config, 201), (1, 1))
        self.assertEqual(scale.event_coordinates(config, 10_000_000), (49_999, 200))

    def test_ceil_div_boundaries(self) -> None:
        self.assertEqual(scale.ceil_div(1, 1), 1)
        self.assertEqual(scale.ceil_div(1000, 1000), 1)
        self.assertEqual(scale.ceil_div(1001, 1000), 2)

    def test_malformed_inputs_are_rejected(self) -> None:
        for config in (
            scale.ScaleConfig(0, 1, 1),
            scale.ScaleConfig(-1, 1, 1),
            scale.ScaleConfig(True, 1, 1),
            scale.ScaleConfig(2, 3, 1),
            scale.ScaleConfig(1, scale.INT32_MAX + 1, 1),
        ):
            with self.subTest(config=config):
                with self.assertRaises(scale.ScaleValidationError):
                    scale.validate_config(config)
        with self.assertRaises(scale.ScaleValidationError):
            scale.event_coordinates(scale.ScaleConfig(2, 4, 1), 0)

    def test_indexes_and_plans_are_checked_against_metadata(self) -> None:
        report = scale.validate_scale(scale.ScaleConfig(10, 20, 4))
        self.assertTrue(report["index_contract"]["all_present_and_column_ordered"])
        plans = report["query_plans"]
        self.assertTrue(plans["attempt_event_pagination"]["uses_expected_index"])
        self.assertTrue(plans["execution_event_pagination"]["uses_expected_index"])
        self.assertTrue(plans["lease_filter"]["uses_expected_index"])
        self.assertFalse(plans["lease_filter"]["order_by_covered"])

    def test_report_is_json_serializable_and_has_claim_ceiling(self) -> None:
        report = scale.validate_scale(scale.ScaleConfig(10, 20, 4))
        encoded = json.dumps(report)
        self.assertIn("capacity model/schema validation only", encoded)

    def test_materialize_requires_new_path_and_batches(self) -> None:
        config = scale.ScaleConfig(5, 10, 3)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "projection.db"
            summary = scale._materialize(config, destination)
            self.assertEqual(summary["attempt_rows"], 5)
            self.assertEqual(summary["event_rows"], 10)
            self.assertEqual(summary["last_cursor"], 10)
            with self.assertRaises(scale.ScaleValidationError):
                scale._materialize(config, destination)


if __name__ == "__main__":
    unittest.main()
