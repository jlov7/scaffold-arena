from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/check-doc-visual-assets.py"
SPEC = importlib.util.spec_from_file_location("doc_visual_assets", SCRIPT)
assert SPEC and SPEC.loader
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


class DocumentationVisualAssetTests(unittest.TestCase):
    def test_pinned_assets_pass(self) -> None:
        root = self._repository()
        self.assertEqual(checker.audit(root), [])

    def test_missing_asset_fails(self) -> None:
        root = self._repository()
        (root / "docs/assets/scaffold-arena-hero.svg").unlink()
        errors = checker.audit(root)
        self.assertIn("missing asset: docs/assets/scaffold-arena-hero.svg", errors)

    def test_tampered_screenshot_fails(self) -> None:
        root = self._repository()
        screenshot_path = next(iter(checker.EXPECTED_SCREENSHOTS))
        screenshot = root / screenshot_path
        screenshot.write_bytes(b"tampered")
        errors = checker.audit(root)
        self.assertIn(f"asset hash mismatch: {screenshot_path}", errors)

    def test_stale_or_unallowlisted_manifest_entry_fails(self) -> None:
        root = self._repository()
        manifest_path = root / "docs/assets/visual-assets.v1.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["assets"].append({"path": "docs/assets/screenshots/v1/stale.png", "sha256": "0" * 64})
        manifest_path.write_text(json.dumps(manifest))
        errors = checker.audit(root)
        self.assertIn("asset is not allowlisted: docs/assets/screenshots/v1/stale.png", errors)

    def test_missing_manifest_outside_repository_reports_an_error(self) -> None:
        root = self._repository()
        errors = checker.audit(root, root / "elsewhere" / "visual-assets.v1.json")
        self.assertEqual(len(errors), 1)
        self.assertTrue(errors[0].startswith("missing manifest:"))

    def test_tampered_generator_or_fixture_input_fails(self) -> None:
        root = self._repository()
        (root / "frontend/tests/visual/product-tour-v1.spec.ts").write_text("tampered generator")
        errors = checker.audit(root)
        self.assertIn(
            f"asset provenance generator hash mismatch: {next(iter(checker.EXPECTED_SCREENSHOTS))}",
            errors,
        )

        root = self._repository()
        (root / "frontend/tests/support/workbenchV1Mock.ts").write_text("tampered fixture")
        errors = checker.audit(root)
        self.assertIn(
            f"asset provenance fixture_source hash mismatch: {next(iter(checker.EXPECTED_SCREENSHOTS))}",
            errors,
        )

    def test_tampered_frontend_source_tree_fails(self) -> None:
        root = self._repository()
        (root / "frontend/src/App.tsx").write_text("changed application source")
        errors = checker.audit(root)
        self.assertIn(
            f"screenshot provenance source tree hash mismatch: {next(iter(checker.EXPECTED_SCREENSHOTS))}",
            errors,
        )

    def test_symlinked_frontend_source_tree_fails(self) -> None:
        root = self._repository()
        source = root / "frontend/src/App.tsx"
        source.unlink()
        os.symlink("../tests/support/workbenchV1Mock.ts", source)
        errors = checker.audit(root)
        self.assertIn(
            f"screenshot provenance source tree contains a symlink: {next(iter(checker.EXPECTED_SCREENSHOTS))}",
            errors,
        )

    def test_swapped_render_metadata_or_png_dimensions_fails(self) -> None:
        root = self._repository()
        manifest_path = root / "docs/assets/visual-assets.v1.json"
        manifest = json.loads(manifest_path.read_text())
        first_screenshot = next(index for index, asset in enumerate(manifest["assets"]) if "screenshots/v1/product-tour" in asset["path"])
        second_screenshot = list(checker.EXPECTED_SCREENSHOTS)[1]
        target_path = manifest["assets"][first_screenshot]["path"]
        manifest["assets"][first_screenshot]["provenance"]["render"] = {
            key: value for key, value in checker.EXPECTED_SCREENSHOTS[second_screenshot].items()
            if key in {"route", "viewport", "color_scheme", "device_scale_factor", "screenshot_scale", "png_dimensions"}
        }
        manifest_path.write_text(json.dumps(manifest))
        errors = checker.audit(root)
        self.assertIn(
            f"screenshot provenance render metadata mismatch: {target_path}",
            errors,
        )

    def _repository(self):
        directory = Path(tempfile.mkdtemp(prefix="doc-visual-assets-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(directory))
        hero = directory / "docs/assets/scaffold-arena-hero.svg"
        hero.parent.mkdir(parents=True)
        hero.write_text('<svg role="img" aria-labelledby="hero-title hero-desc"><title id="hero-title">Hero</title><desc id="hero-desc">A deterministic fixture visual.</desc><style>@media (prefers-reduced-motion: reduce) {} @media (prefers-color-scheme: light) {}</style></svg>')
        screenshots = directory / "docs/assets/screenshots/v1/product-tour"
        screenshots.mkdir(parents=True)
        for relative, expected in checker.EXPECTED_SCREENSHOTS.items():
            path = directory / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(self._png_header(**expected["png_dimensions"]))
        generator = directory / "frontend/tests/visual/product-tour-v1.spec.ts"
        fixture = directory / "frontend/tests/support/workbenchV1Mock.ts"
        fixture.parent.mkdir(parents=True)
        generator.parent.mkdir(parents=True)
        generator.write_text("fixture screenshot generator")
        fixture.write_text("fixture source")
        source_file = directory / "frontend/src/App.tsx"
        source_file.parent.mkdir(parents=True)
        source_file.write_text("fixture application source")
        hero_fixture = directory / "study_packs/offline-demo-v1/study-pack.json"
        hero_fixture.parent.mkdir(parents=True)
        hero_fixture.write_text("synthetic recorded StudyPack")
        runtime_truth_table = directory / "study_packs/offline-demo-v1/fixtures/runtime-truth-table.json"
        runtime_truth_table.parent.mkdir(parents=True)
        runtime_truth_table.write_text("synthetic recorded truth table")
        render_inputs = {
            "frontend/index.html": "fixture index",
            "frontend/playwright.config.ts": "fixture config",
            "frontend/pnpm-lock.yaml": "fixture lock",
        }
        for relative, contents in render_inputs.items():
            path = directory / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents)
        fixture_hash = hashlib.sha256(fixture.read_bytes()).hexdigest()
        generator_hash = hashlib.sha256(generator.read_bytes()).hexdigest()
        hero_fixture_hash = hashlib.sha256(hero_fixture.read_bytes()).hexdigest()
        runtime_truth_table_hash = hashlib.sha256(runtime_truth_table.read_bytes()).hexdigest()
        source_tree_hash, tree_error = checker._source_tree_sha256(directory, "frontend/src")
        assert tree_error is None
        assets = []
        for relative in sorted(checker.ALLOWED_PATHS):
            path = directory / relative
            entry = {"path": relative, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            if relative == checker.HERO_PATH:
                entry["accessibility"] = {
                    "role": "img", "aria_labelledby": "hero-title hero-desc", "title_id": "hero-title",
                    "description_id": "hero-desc", "freeze_media_query": "@media (prefers-reduced-motion: reduce)", "light_media_query": "@media (prefers-color-scheme: light)", "determinism_copy": "deterministic",
                }
                entry["provenance"] = {
                    "source_base_commit": checker.SOURCE_COMMIT,
                    "source_state": checker.SOURCE_STATE,
                    "fixture_source": "study_packs/offline-demo-v1/study-pack.json",
                    "input_hashes": {"fixture_source": hero_fixture_hash},
                    "fixture_inputs": {
                        "study_pack": {"path": "study_packs/offline-demo-v1/study-pack.json", "sha256": hero_fixture_hash},
                        "runtime_truth_table": {"path": "study_packs/offline-demo-v1/fixtures/runtime-truth-table.json", "sha256": runtime_truth_table_hash},
                    },
                }
            else:
                expected = checker.EXPECTED_SCREENSHOTS[relative]
                entry.update({"surface_id": expected["surface_id"], "alt_text": expected["alt_text"]})
                entry["provenance"] = {
                    "source_base_commit": checker.SOURCE_COMMIT,
                    "source_state": checker.SOURCE_STATE,
                    "generator": "frontend/tests/visual/product-tour-v1.spec.ts",
                    "fixture_source": "frontend/tests/support/workbenchV1Mock.ts",
                    "input_hashes": {"generator": generator_hash, "fixture_source": fixture_hash},
                    "fixture_kind": "synthetic_ui_mock",
                    "render": {key: value for key, value in expected.items() if key in {"route", "viewport", "color_scheme", "device_scale_factor", "screenshot_scale", "png_dimensions"}},
                    "png_sha256": entry["sha256"],
                    "source_tree": "frontend/src", "source_tree_sha256": source_tree_hash,
                    "render_inputs": {
                        relative: hashlib.sha256((directory / relative).read_bytes()).hexdigest()
                        for relative in checker.RENDER_INPUTS
                    },
                    "browser_identity": checker.BROWSER_IDENTITY,
                }
            assets.append(entry)
        (directory / "docs/assets/visual-assets.v1.json").write_text(json.dumps({"schema_version": "1.0", "claim_boundary": "Fixture evidence only.", "assets": assets}))
        return directory

    @staticmethod
    def _png_header(width: int, height: int) -> bytes:
        return b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR" + width.to_bytes(4, "big") + height.to_bytes(4, "big")
