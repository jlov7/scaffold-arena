from __future__ import annotations

import importlib.util
import json
import shutil
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "generate-protocol-v1-schemas.py"
SPEC = importlib.util.spec_from_file_location("generate_protocol_v1_schemas", SCRIPT)
assert SPEC and SPEC.loader
generator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generator)


class GenerateProtocolV1SchemasTests(unittest.TestCase):
    def test_generated_schemas_are_clean_and_valid(self) -> None:
        output_directory = ROOT / "specs" / "v1"
        self.assertEqual(generator.main(["--check", "--output-dir", str(output_directory)]), 0)
        self.assertEqual(set(generator.generated_schemas()), {path.name for path in output_directory.glob("*.schema.json")})

    def test_active_contract_schemas_have_unambiguous_filenames(self) -> None:
        schemas = generator.generated_schemas()
        self.assertIn("analysis-v1-decision-admission-request.schema.json", schemas)
        self.assertIn("evidence-v1-evidence-receipt.schema.json", schemas)
        self.assertIn("evidence-v1-reproduction-receipt.schema.json", schemas)
        self.assertIn("review-v1-annotation-batch.schema.json", schemas)
        self.assertIn("review-v1-calibration-annotation-result.schema.json", schemas)
        self.assertIn("review-v1-calibration-adjudication-result.schema.json", schemas)
        self.assertIn("genome-descriptor.schema.json", schemas)
        self.assertIn("genome-graph-projection.schema.json", schemas)
        self.assertIn("genome-standards-catalog.schema.json", schemas)
        self.assertIn("xray-v1-request.schema.json", schemas)
        self.assertIn("xray-v1-report.schema.json", schemas)
        self.assertIn("observatory-v1-request.schema.json", schemas)
        self.assertIn("observatory-v1-report.schema.json", schemas)
        self.assertIn("counterfactual-replay-v1-request.schema.json", schemas)
        self.assertIn("counterfactual-replay-v1-report.schema.json", schemas)
        self.assertIn("harness-ci-v1-request.schema.json", schemas)
        self.assertIn("harness-ci-v1-report.schema.json", schemas)
        self.assertNotIn("evidence-receipt.schema.json", schemas)
        self.assertNotIn("reproduction-receipt.schema.json", schemas)
        self.assertNotIn("human-annotation-batch.schema.json", schemas)
        self.assertNotIn("decision-brief.schema.json", schemas)

    def test_review_schemas_preserve_the_human_calibration_contract(self) -> None:
        schemas = {name: json.loads(contents) for name, contents in generator.generated_schemas().items()}
        batch = schemas["review-v1-annotation-batch.schema.json"]
        self.assertEqual(batch["properties"]["annotator_pseudonyms"]["minItems"], 3)
        receipt = batch["$defs"]["HumanCalibrationReceipt"]
        self.assertEqual(receipt["properties"]["annotator_count"]["minimum"], 3)
        self.assertEqual(receipt["properties"]["resolved_conflicts"]["const"], True)
        adjudication = schemas["review-v1-calibration-adjudication-result.schema.json"]
        self.assertIn("evidence_artifact_digest", adjudication["properties"])
        self.assertIn("final_scores", adjudication["properties"])

    def test_check_detects_drift_without_writing(self) -> None:
        output_directory = self._copy_schemas()
        target = output_directory / "scenario.schema.json"
        target.write_text("{}\n", encoding="utf-8")
        self.assertEqual(generator.main(["--check", "--output-dir", str(output_directory)]), 1)
        self.assertEqual(target.read_text(encoding="utf-8"), "{}\n")

    def test_check_detects_missing_file(self) -> None:
        output_directory = self._copy_schemas()
        (output_directory / "protocol.schema.json").unlink()
        self.assertEqual(generator.main(["--check", "--output-dir", str(output_directory)]), 1)

    def _copy_schemas(self) -> Path:
        import tempfile

        parent = Path(tempfile.mkdtemp(prefix="protocol-v1-schemas-"))
        path = parent / "schemas"
        shutil.copytree(ROOT / "specs" / "v1", path)
        self.addCleanup(shutil.rmtree, parent)
        return path


if __name__ == "__main__":
    unittest.main()
