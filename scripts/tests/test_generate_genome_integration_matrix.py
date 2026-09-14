from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "generate-genome-integration-matrix.py"
SPEC = importlib.util.spec_from_file_location("generate_genome_integration_matrix", SCRIPT)
assert SPEC and SPEC.loader
generator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generator)


class GenerateGenomeIntegrationMatrixTests(unittest.TestCase):
    def test_generated_outputs_are_current_and_claim_bounded(self) -> None:
        self.assertEqual(generator.main(["--check"]), 0)
        matrix = generator.generated_matrix()
        self.assertEqual(matrix["source_date"], "2026-08-18")
        self.assertIn("no execution", matrix["claim_ceiling"].lower())
        self.assertEqual({row["integration_id"] for row in matrix["entries"]}, {"native-genome-v1", "otel", "a2a", "mcp"})
        self.assertTrue(all("fixture" in row["claim_ceiling"].lower() or "synthetic" in row["claim_ceiling"].lower() for row in matrix["entries"]))


if __name__ == "__main__":
    unittest.main()
