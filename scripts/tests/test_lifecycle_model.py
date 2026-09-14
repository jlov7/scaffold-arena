from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check-lifecycle-model.py"


class LifecycleModelScriptTests(unittest.TestCase):
    def test_checker_emits_a_bounded_claim_and_required_invariants(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--depth", "4", "--generations", "2"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["max_depth"], 4)
        self.assertIn("bounded engineering model", report["claim_ceiling"])
        self.assertIn("stale_generations_cannot_finalize_current_truth", report["invariants"])
        self.assertIn("budget_is_not_double_committed", report["invariants"])


if __name__ == "__main__":
    unittest.main()
