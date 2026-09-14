from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


calibration = _load_module("check_human_calibration", "check-human-calibration.py")
external = _load_module("check_external_validation", "check-external-validation.py")


class HumanCalibrationContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.packet = calibration.build_packet()
        self.target = self.packet["targets"][0]
        self.single_target_packet = copy.deepcopy(self.packet)
        self.single_target_packet["targets"] = [copy.deepcopy(self.target)]

    def _annotation(self, index: int, *, task_success: float = 0.5, blind: bool = True) -> dict:
        assignment = self.target["assignments"][index]
        return {
            "target_id": self.target["target_id"],
            "run_id": self.target["run_id"],
            "assignment_id": assignment["assignment_id"],
            "annotator_pseudonym": assignment["annotator_pseudonym"],
            "blind_to_scaffold": blind,
            "dimension_scores": {
                "task_success": task_success,
                "evidence_grounding": 0.5,
                "schema_adherence": 0.5,
                "safety_boundary": 0.5,
                "actionability": 0.5,
            },
        }

    def _write(self, directory: Path, name: str, value: dict) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / name).write_text(json.dumps(value), encoding="utf-8")

    def test_zero_annotations_remain_a_hold(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            audit = calibration.build_calibration_audit(Path(temp), self.packet)
        self.assertEqual(audit["status"], "blocked_no_completed_annotations")
        self.assertEqual(audit["annotation_count"], 0)
        self.assertEqual(calibration._validate_audit(audit), [])

    def test_two_reviews_are_incomplete_but_three_assigned_reviews_complete(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            self._write(directory, "one.json", self._annotation(0))
            self._write(directory, "two.json", self._annotation(1))
            partial = calibration.build_calibration_audit(directory, self.single_target_packet)
            self.assertEqual(partial["status"], "partial_human_calibration_not_release_evidence")
            self.assertEqual(partial["completed_annotation_targets"], 0)
            self.assertTrue(calibration._validate_audit(partial))
            self._write(directory, "three.json", self._annotation(2))
            complete = calibration.build_calibration_audit(directory, self.single_target_packet)
        self.assertEqual(complete["status"], "protocol_complete_requires_authority_attestation")
        self.assertEqual(complete["completed_annotation_targets"], 1)
        self.assertIsNone(complete["human_calibration_receipt"])
        self.assertEqual(len(complete["protocol_completion_digest"]), 64)

    def test_duplicate_assignment_and_blindness_failure_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            self._write(directory, "one.json", self._annotation(0))
            self._write(directory, "duplicate.json", self._annotation(0))
            report = calibration._agreement_report(directory, self.single_target_packet)
            self.assertTrue(any("duplicate annotation assignment" in error for error in report["errors"]))
            (directory / "duplicate.json").unlink()
            self._write(directory, "not-blind.json", self._annotation(1, blind=False))
            report = calibration._agreement_report(directory, self.single_target_packet)
        self.assertTrue(any("annotation schema failed" in error for error in report["errors"]))

    def test_packet_rejects_identity_or_scaffold_leaks(self) -> None:
        packet = copy.deepcopy(self.packet)
        packet["targets"][0]["annotator_view"]["scaffold_id"] = "private"
        packet["targets"][0]["blind_payload_digest"] = calibration._digest(packet["targets"][0]["annotator_view"])
        errors = calibration._validate_packet(packet)
        self.assertTrue(any("leaks withheld fields" in error for error in errors))

    def test_conflicts_need_exactly_one_bound_adjudication(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            for index, score in enumerate((0.0, 0.5, 1.0)):
                self._write(directory, f"{index}.json", self._annotation(index, task_success=score))
            held = calibration.build_calibration_audit(directory, self.single_target_packet)
            self.assertEqual(held["status"], "human_calibration_requires_adjudication")
            adjudications = directory / "adjudications"
            wrong = {
                "target_id": self.target["target_id"],
                "run_id": self.target["run_id"],
                "adjudicator_pseudonym": "lead",
                "final_scores": {"task_success": 0.7, "evidence_grounding": 0.7},
                "decision": "resolve",
                "rationale": "reviewed blinded output",
                "evidence_artifact_digest": self.target["blind_payload_digest"],
            }
            self._write(adjudications, "wrong.json", wrong)
            invalid = calibration.build_calibration_audit(directory, self.single_target_packet)
            self.assertEqual(invalid["status"], "invalid_human_calibration_evidence")
            self.assertTrue(any("exactly the conflicted dimensions" in error for error in invalid["validation_errors"]))
            (adjudications / "wrong.json").unlink()
            wrong["final_scores"] = {"task_success": 0.7}
            wrong["evidence_artifact_digest"] = "0" * 64
            self._write(adjudications, "unbound.json", wrong)
            invalid = calibration.build_calibration_audit(directory, self.single_target_packet)
            self.assertTrue(any("not bound" in error for error in invalid["validation_errors"]))
            (adjudications / "unbound.json").unlink()
            wrong["evidence_artifact_digest"] = self.target["blind_payload_digest"]
            self._write(adjudications, "valid.json", wrong)
            complete = calibration.build_calibration_audit(directory, self.single_target_packet)
        self.assertEqual(complete["status"], "protocol_complete_requires_authority_attestation")

    def test_non_conflict_adjudication_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            for index in range(3):
                self._write(directory, f"{index}.json", self._annotation(index))
            self._write(directory / "adjudications", "unneeded.json", {
                "target_id": self.target["target_id"],
                "run_id": self.target["run_id"],
                "adjudicator_pseudonym": "lead",
                "final_scores": {"task_success": 0.5},
                "decision": "resolve",
                "rationale": "unneeded",
                "evidence_artifact_digest": self.target["blind_payload_digest"],
            })
            audit = calibration.build_calibration_audit(directory, self.single_target_packet)
        self.assertEqual(audit["status"], "invalid_human_calibration_evidence")
        self.assertTrue(any("not permitted" in error for error in audit["validation_errors"]))


class ExternalValidationContractTests(unittest.TestCase):
    def test_external_artifact_reference_cannot_escape_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "repo"
            root.mkdir()
            (base / "attestation.json").write_text("{}", encoding="utf-8")
            old_root = external.ROOT
            external.ROOT = root
            try:
                errors = external._artifact_reference_errors(
                    "authority_attestation_uri", "../attestation.json"
                )
            finally:
                external.ROOT = old_root
        self.assertTrue(any("inside the repository" in error for error in errors))

    def test_human_batch_requires_v1_three_annotators_and_bound_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            schema = json.loads((ROOT / "specs/external-validation.schema.json").read_text())
            ledger_path = root / "outputs/external_validation.json"
            audit_path = root / "outputs/external_validation_audit.json"
            schema_path = root / "specs/external-validation.schema.json"
            ledger_path.parent.mkdir(parents=True)
            schema_path.parent.mkdir(parents=True)
            schema_path.write_text(json.dumps(schema), encoding="utf-8")
            for name in ("agreement.json", "adjudication.json", "completion.json", "attestation.json"):
                (root / name).write_text("{}", encoding="utf-8")
            batch = {
                "id": "batch-one", "date": "2026-08-19", "protocol_version": "1.0",
                "annotator_count": 2, "artifact_count": 1, "agreement_statistic": "pairwise",
                "agreement_artifact_uri": "agreement.json", "adjudication_artifact_uri": "adjudication.json",
                "review_completion_artifact_uri": "completion.json", "authority_attestation_uri": "attestation.json",
                "resolved_conflicts": True,
            }
            ledger = {
                "schema_version": "0.1", "generated_at": "2026-08-19T00:00:00Z", "status": "external_validation_completed",
                "independent_reproductions": [], "public_critiques": [], "human_annotation_batches": [batch],
                "claim_boundary": "Concrete evidence is required before any claim.", "blockers": ["none recorded"],
            }
            ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
            old = (external.ROOT, external.LEDGER_PATH, external.AUDIT_PATH, external.SCHEMA_PATH)
            external.ROOT, external.LEDGER_PATH, external.AUDIT_PATH, external.SCHEMA_PATH = root, ledger_path, audit_path, schema_path
            try:
                invalid = external.build_audit()
                self.assertEqual(invalid["status"], "invalid_external_validation_evidence")
                self.assertTrue(any("at least 3" in error for error in invalid["validation_errors"]))
                batch["annotator_count"] = 3
                ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
                valid = external.build_audit()
            finally:
                external.ROOT, external.LEDGER_PATH, external.AUDIT_PATH, external.SCHEMA_PATH = old
        self.assertEqual(valid["status"], "external_validation_evidence_recorded_not_live_or_field_validation")
        self.assertEqual(valid["validation_error_count"], 0)


if __name__ == "__main__":
    unittest.main()
