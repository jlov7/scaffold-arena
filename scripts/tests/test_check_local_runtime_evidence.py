from __future__ import annotations

import errno
import base64
import hashlib
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/check-local-runtime-evidence.py"
SPEC = importlib.util.spec_from_file_location("local_runtime_evidence", SCRIPT)
assert SPEC and SPEC.loader
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


class LocalRuntimeEvidenceTests(unittest.TestCase):
    def bundle(self, root: Path, name: str = "bundle") -> Path:
        bundle = root / name
        (bundle / "artifacts").mkdir(parents=True)
        artifact = b'{"result":"ok"}'
        artifact_digest = digest(artifact)
        files = {
            "summary.json": {
                "status": "COMPLETE_LOCAL_EXPLORATORY_CUSTODY",
                "claim_boundary": "Exploratory only; never confirmatory and never a scaffold-effect claim.",
                "paid_cost_usd": 0.0,
                "energy_status": "unknown",
                "code_revision": "a" * 40,
            },
            "attempts.json": [],
            "evaluations.json": [],
            "events.json": [],
            "receipt.json": {},
            "receipt-verification.json": {},
            "artifact-digest-inventory.json": [
                {"path": f"artifacts/{artifact_digest}", "sha256": artifact_digest, "size_bytes": len(artifact)}
            ],
        }
        receipt_artifacts = [artifact_digest]
        receipt_payload = {
            "receipt_id": "receipt",
            "manifest_hash": "b" * 64,
            "artifact_hashes": receipt_artifacts,
            "integrity_not_truth": True,
        }
        receipt_hash = digest(canonical(receipt_payload))
        files["receipt.json"] = {
            "receipt_id": "receipt",
            "manifest_hash": "b" * 64,
            "receipt_hash": receipt_hash,
            "artifacts": [
                {"sha256": artifact_digest, "disposition": "withheld", "reason": "test"}
            ],
            "evidence_type": "derived_local_live",
            "evidence_class": "local_live",
            "integrity_not_truth": True,
        }
        files["receipt-verification.json"] = {
            "receipt_id": "receipt",
            "manifest_hash": "b" * 64,
            "receipt_hash": digest(
                canonical({**receipt_payload, "receipt_hash": receipt_hash})
            ),
            "errors": [],
            "verified": True,
            "integrity_not_truth": True,
        }
        declared: dict[str, str] = {}
        for name, value in files.items():
            payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
            (bundle / name).write_bytes(payload)
            declared[name] = digest(payload)
        artifact_path = f"artifacts/{artifact_digest}"
        (bundle / artifact_path).write_bytes(artifact)
        declared[artifact_path] = artifact_digest
        manifest = {
            "files": [{"path": path, "sha256": value} for path, value in declared.items()],
            "bundle_hash": digest(json.dumps({"files": declared}, sort_keys=True, separators=(",", ":")).encode()),
        }
        (bundle / "bundle-manifest.json").write_text(json.dumps(manifest))
        return bundle

    def refresh_manifest(self, bundle: Path) -> None:
        manifest = json.loads((bundle / "bundle-manifest.json").read_bytes())
        declared: dict[str, str] = {}
        for entry in manifest["files"]:
            path = bundle / entry["path"]
            entry["sha256"] = digest(path.read_bytes())
            declared[entry["path"]] = entry["sha256"]
        manifest["bundle_hash"] = digest(canonical({"files": declared}))
        (bundle / "bundle-manifest.json").write_bytes(canonical(manifest))

    def _git(self, root: Path, *arguments: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def _publication_binding(self, root: Path, bundle: Path, *, source_tree: str | None = None) -> str:
        revision = self._git(root, "rev-parse", "HEAD")
        tree = source_tree or self._git(root, "rev-parse", "HEAD^{tree}")
        inventory, errors = checker._tree_inventory_sha256(root, revision)
        self.assertEqual(errors, [])
        self.assertIsNotNone(inventory)
        binding = {
            "claim_ceiling": checker.PORTABLE_CLAIM_CEILING,
            "historical_bundles": [
                {
                    "path": bundle.relative_to(root).as_posix(),
                    "bundle_manifest_sha256": digest((bundle / "bundle-manifest.json").read_bytes()),
                }
            ],
            "kind": checker.PUBLICATION_BINDING_KIND,
            "inventory_sha256": inventory,
            "schema_version": 1,
            "source_revision": "c" * 40,
            "source_tree": tree,
        }
        encoded = base64.urlsafe_b64encode(canonical(binding)).decode("ascii").rstrip("=")
        return checker.PUBLICATION_BINDING_MARKER + encoded

    def publication_repository(self, root: Path, *, source_tree: str | None = None, marker: str | None = None) -> Path:
        evidence_root = root / checker.EVIDENCE_ROOT
        bundle = self.bundle(evidence_root)
        self._git(root, "init", "--quiet")
        self._git(root, "config", "user.email", "tests@example.invalid")
        self._git(root, "config", "user.name", "Publication test")
        self._git(root, "add", ".")
        self._git(root, "commit", "--quiet", "-m", "initial public snapshot")
        message = marker or self._publication_binding(root, bundle, source_tree=source_tree)
        self._git(root, "commit", "--quiet", "--amend", "-m", message)
        return bundle

    def test_valid_bundle_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = self.bundle(Path(temporary))
            self.assertEqual(checker.audit_bundle(bundle, is_ancestor=lambda _: True), [])

    def test_portable_binding_survives_fresh_clone_with_origin_and_follow_on_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "source"
            root.mkdir()
            self.publication_repository(root)
            self.assertEqual(checker.audit(root), [])
            clone = Path(temporary) / "clone"
            subprocess.run(["git", "clone", "--quiet", str(root), str(clone)], check=True)
            self._git(clone, "config", "user.email", "tests@example.invalid")
            self._git(clone, "config", "user.name", "Publication test")
            (clone / "FOLLOW_ON.md").write_text("subsequent public change\n")
            self._git(clone, "add", "FOLLOW_ON.md")
            self._git(clone, "commit", "--quiet", "-m", "follow-on change")
            self.assertEqual(self._git(clone, "remote"), "origin")
            self.assertEqual(checker.audit(clone), [])

    def test_portable_binding_fails_closed_for_malformed_or_wrong_root_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            malformed_root = Path(temporary) / "malformed"
            malformed_root.mkdir()
            self.publication_repository(
                malformed_root,
                marker=checker.PUBLICATION_BINDING_MARKER + "not%base64url",
            )
            malformed_bundle = malformed_root / checker.EVIDENCE_ROOT / "bundle"
            summary_path = malformed_bundle / "summary.json"
            summary = json.loads(summary_path.read_bytes())
            summary["code_revision"] = self._git(malformed_root, "rev-parse", "HEAD")
            summary_path.write_bytes(canonical(summary))
            self.refresh_manifest(malformed_bundle)
            malformed_errors = checker.audit(malformed_root)
            self.assertTrue(any("base64url" in error for error in malformed_errors))

            wrong_tree_root = Path(temporary) / "wrong-tree"
            wrong_tree_root.mkdir()
            self.publication_repository(wrong_tree_root, source_tree="f" * 40)
            wrong_tree_errors = checker.audit(wrong_tree_root)
            self.assertTrue(any("source tree" in error for error in wrong_tree_errors))

    def test_portable_binding_pins_original_bundle_bytes_and_rejects_unbound_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bound_bundle = self.publication_repository(root)
            receipt = json.loads((bound_bundle / "receipt.json").read_bytes())
            receipt["receipt_id"] = "rewritten"
            (bound_bundle / "receipt.json").write_bytes(canonical(receipt))
            self.refresh_manifest(bound_bundle)
            changed_errors = checker.audit(root)
            self.assertTrue(any("historical bundle changed" in error for error in changed_errors))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.publication_repository(root)
            new_bundle = self.bundle(root / checker.EVIDENCE_ROOT, "new-bundle")
            self.assertTrue(any("not an ancestor" in error for error in checker.audit(root)))
            summary_path = new_bundle / "summary.json"
            summary = json.loads(summary_path.read_bytes())
            summary["code_revision"] = self._git(root, "rev-parse", "HEAD")
            summary_path.write_bytes(canonical(summary))
            self.refresh_manifest(new_bundle)
            self.assertEqual(checker.audit(root), [])

    def test_portable_binding_rejects_symlinked_bound_bundle_before_reading_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "source"
            root.mkdir()
            bundle = self.publication_repository(root)
            outside = Path(temporary) / "outside-bundle"
            bundle.rename(outside)
            bundle.symlink_to(outside, target_is_directory=True)
            errors = checker.audit(root)
            self.assertTrue(any("not a contained real directory" in error for error in errors))

    def test_publication_binding_parser_rejects_noncanonical_schema_and_paths(self) -> None:
        valid = {
            "claim_ceiling": checker.PORTABLE_CLAIM_CEILING,
            "historical_bundles": [
                {
                    "path": "outputs/local_runtime_evidence/bundle",
                    "bundle_manifest_sha256": "a" * 64,
                }
            ],
            "kind": checker.PUBLICATION_BINDING_KIND,
            "inventory_sha256": "b" * 64,
            "schema_version": 1,
            "source_revision": "c" * 40,
            "source_tree": "d" * 40,
        }
        for name, value in {
            "unknown_key": {**valid, "unexpected": True},
            "unsafe_path": {
                **valid,
                "historical_bundles": [
                    {"path": "outputs/local_runtime_evidence/../bundle", "bundle_manifest_sha256": "a" * 64}
                ],
            },
            "wrong_ceiling": {**valid, "claim_ceiling": "anything_else"},
            "boolean_version": {**valid, "schema_version": True},
        }.items():
            with self.subTest(name=name):
                raw = canonical(value)
                marker = checker.PUBLICATION_BINDING_MARKER + base64.urlsafe_b64encode(raw).decode().rstrip("=")
                binding, errors = checker._parse_publication_binding(marker.encode())
                self.assertIsNone(binding)
                self.assertTrue(errors)

        duplicate_keys = (
            b'{"claim_ceiling":"historical_integrity_not_current_code_or_live_evidence",'
            b'"claim_ceiling":"historical_integrity_not_current_code_or_live_evidence"}'
        )
        duplicate_marker = checker.PUBLICATION_BINDING_MARKER + base64.urlsafe_b64encode(duplicate_keys).decode().rstrip("=")
        self.assertTrue(checker._parse_publication_binding(duplicate_marker.encode())[1])
        multiple_marker = (checker.PUBLICATION_BINDING_MARKER + "a\n" + checker.PUBLICATION_BINDING_MARKER + "b").encode()
        self.assertTrue(checker._parse_publication_binding(multiple_marker)[1])
        oversized_marker = checker.PUBLICATION_BINDING_MARKER + "A" * (checker.PUBLICATION_BINDING_MAX_BYTES * 2)
        self.assertTrue(checker._parse_publication_binding(oversized_marker.encode())[1])

    def test_tampering_privacy_and_revision_fail_closed(self) -> None:
        mutations = {
            "digest": lambda bundle: (bundle / "summary.json").write_text("{}"),
            "privacy": lambda bundle: (bundle / "artifacts" / next((bundle / "artifacts").iterdir()).name).write_text('{"reasoning":"secret"}'),
            "revision": lambda bundle: None,
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                bundle = self.bundle(Path(temporary))
                mutate(bundle)
                errors = checker.audit_bundle(
                    bundle, is_ancestor=lambda _, current=name: current != "revision"
                )
                self.assertTrue(errors)

    def test_symlinked_evidence_root_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "outputs").mkdir()
            outside = root / "outside"
            outside.mkdir()
            (root / "outputs" / "local_runtime_evidence").symlink_to(
                outside, target_is_directory=True
            )
            errors = checker.audit(root)
            self.assertTrue(any("evidence root" in error for error in errors))

    def test_unexpected_root_entry_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence_root = root / "outputs" / "local_runtime_evidence"
            evidence_root.mkdir(parents=True)
            (evidence_root / "unexpected.txt").write_text("unexpected")
            errors = checker.audit(root)
            self.assertTrue(any("unexpected non-directory" in error for error in errors))

    def test_unexpected_bundle_directory_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = self.bundle(Path(temporary))
            (bundle / "unexpected").mkdir()
            errors = checker.audit_bundle(bundle, is_ancestor=lambda _: True)
            self.assertTrue(any("unexpected directory" in error for error in errors))

    def test_fifo_fails_closed_when_supported(self) -> None:
        if not hasattr(os, "mkfifo"):
            self.skipTest("FIFO creation is unavailable on this platform")
        with tempfile.TemporaryDirectory() as temporary:
            bundle = self.bundle(Path(temporary))
            try:
                os.mkfifo(bundle / "unlisted.fifo")
            except OSError as exc:
                if exc.errno in {errno.ENOTSUP, errno.EOPNOTSUPP, errno.EPERM}:
                    self.skipTest(f"FIFO creation is unavailable: {exc}")
                raise
            errors = checker.audit_bundle(bundle, is_ancestor=lambda _: True)
            self.assertTrue(any("non-regular file" in error for error in errors))

    def test_rewritten_receipt_and_verified_flag_fail_after_manifest_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = self.bundle(Path(temporary))
            receipt_path = bundle / "receipt.json"
            receipt = json.loads(receipt_path.read_bytes())
            receipt["artifacts"][0]["sha256"] = "c" * 64
            receipt_path.write_bytes(canonical(receipt))
            self.refresh_manifest(bundle)
            errors = checker.audit_bundle(bundle, is_ancestor=lambda _: True)
            self.assertTrue(any("receipt hash mismatch" in error for error in errors))

        with tempfile.TemporaryDirectory() as temporary:
            bundle = self.bundle(Path(temporary))
            verification_path = bundle / "receipt-verification.json"
            verification = json.loads(verification_path.read_bytes())
            verification["verified"] = False
            verification_path.write_bytes(canonical(verification))
            self.refresh_manifest(bundle)
            errors = checker.audit_bundle(bundle, is_ancestor=lambda _: True)
            self.assertTrue(any("not freshly verified" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
