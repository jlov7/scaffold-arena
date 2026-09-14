#!/usr/bin/env python3
"""Verify that public documentation visuals are pinned to bounded local evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "docs/assets/visual-assets.v1.json"
HERO_PATH = "docs/assets/scaffold-arena-hero.svg"
SCREENSHOT_PREFIX = "docs/assets/screenshots/v1/"
SOURCE_COMMIT = "1a5967aa70892470ac58e0fa95bc6bc299a17b28"
SOURCE_STATE = "base_commit_plus_pinned_inputs"
EXPECTED_SCREENSHOTS = {
    "docs/assets/screenshots/v1/product-tour/harness-home-xray-desktop.png": {
        "surface_id": "harness-home-xray",
        "alt_text": "Desktop blocked Harness Home / X-Ray showing Captured source required; inspection cannot discover or execute an uncaptured source.",
        "route": "/workbench/xray",
        "viewport": {"width": 1440, "height": 900},
        "color_scheme": "dark",
        "device_scale_factor": 2,
        "screenshot_scale": "css",
        "png_dimensions": {"width": 1440, "height": 956},
    },
    "docs/assets/screenshots/v1/product-tour/harness-home-xray-mobile.png": {
        "surface_id": "harness-home-xray",
        "alt_text": "Mobile blocked Harness Home / X-Ray showing Captured source required; inspection cannot discover or execute an uncaptured source.",
        "route": "/workbench/xray",
        "viewport": {"width": 390, "height": 844},
        "color_scheme": "dark",
        "device_scale_factor": 2,
        "screenshot_scale": "css",
        "png_dimensions": {"width": 390, "height": 973},
    },
    "docs/assets/screenshots/v1/product-tour/study-canvas-desktop.png": {
        "surface_id": "study-canvas",
        "alt_text": "Desktop synthetic fixture Study Canvas showing offline-demo-v1 metadata and the not benchmark evidence boundary.",
        "route": "/workbench/studies",
        "viewport": {"width": 1440, "height": 900},
        "color_scheme": "dark",
        "device_scale_factor": 2,
        "screenshot_scale": "css",
        "png_dimensions": {"width": 1440, "height": 956},
    },
    "docs/assets/screenshots/v1/product-tour/study-canvas-mobile.png": {
        "surface_id": "study-canvas",
        "alt_text": "Mobile synthetic fixture Study Canvas showing offline-demo-v1 metadata and the not benchmark evidence boundary.",
        "route": "/workbench/studies",
        "viewport": {"width": 390, "height": 844},
        "color_scheme": "dark",
        "device_scale_factor": 2,
        "screenshot_scale": "css",
        "png_dimensions": {"width": 390, "height": 1056},
    },
    "docs/assets/screenshots/v1/product-tour/run-cockpit-desktop.png": {
        "surface_id": "run-cockpit",
        "alt_text": "Desktop synthetic fixture Run Cockpit showing Execution HOLD because no durable preflight report or provider request exists.",
        "route": "/workbench/execute?experiment_id=fixture-created-experiment",
        "viewport": {"width": 1440, "height": 900},
        "color_scheme": "dark",
        "device_scale_factor": 2,
        "screenshot_scale": "css",
        "png_dimensions": {"width": 1440, "height": 1182},
    },
    "docs/assets/screenshots/v1/product-tour/run-cockpit-mobile.png": {
        "surface_id": "run-cockpit",
        "alt_text": "Mobile synthetic fixture Run Cockpit showing Execution HOLD because no durable preflight report or provider request exists.",
        "route": "/workbench/execute?experiment_id=fixture-created-experiment",
        "viewport": {"width": 390, "height": 844},
        "color_scheme": "dark",
        "device_scale_factor": 2,
        "screenshot_scale": "css",
        "png_dimensions": {"width": 390, "height": 1641},
    },
    "docs/assets/screenshots/v1/product-tour/decision-canvas-desktop.png": {
        "surface_id": "decision-canvas",
        "alt_text": "Desktop empty Decision Canvas showing no durable analysis report; no effect, winner, cost, or confidence is inferred.",
        "route": "/workbench/analyze?experiment_id=fixture-created-experiment&execution_id=fixture-execution",
        "viewport": {"width": 1440, "height": 900},
        "color_scheme": "dark",
        "device_scale_factor": 2,
        "screenshot_scale": "css",
        "png_dimensions": {"width": 1440, "height": 956},
    },
    "docs/assets/screenshots/v1/product-tour/decision-canvas-mobile.png": {
        "surface_id": "decision-canvas",
        "alt_text": "Mobile empty Decision Canvas showing no durable analysis report; no effect, winner, cost, or confidence is inferred.",
        "route": "/workbench/analyze?experiment_id=fixture-created-experiment&execution_id=fixture-execution",
        "viewport": {"width": 390, "height": 844},
        "color_scheme": "dark",
        "device_scale_factor": 2,
        "screenshot_scale": "css",
        "png_dimensions": {"width": 390, "height": 1109},
    },
    "docs/assets/screenshots/v1/product-tour/trace-counterfactual-desktop.png": {
        "surface_id": "trace-counterfactual-lab",
        "alt_text": "Desktop provider-free paired fixture replay in Trace / Counterfactual Lab showing HOLD, unknown usage, and no posted comment.",
        "route": "/workbench/counterfactual",
        "viewport": {"width": 1440, "height": 900},
        "color_scheme": "dark",
        "device_scale_factor": 2,
        "screenshot_scale": "css",
        "png_dimensions": {"width": 1440, "height": 2323},
    },
    "docs/assets/screenshots/v1/product-tour/trace-counterfactual-mobile.png": {
        "surface_id": "trace-counterfactual-lab",
        "alt_text": "Mobile provider-free paired fixture replay in Trace / Counterfactual Lab showing HOLD, unknown usage, and no posted comment.",
        "route": "/workbench/counterfactual",
        "viewport": {"width": 390, "height": 844},
        "color_scheme": "dark",
        "device_scale_factor": 2,
        "screenshot_scale": "css",
        "png_dimensions": {"width": 390, "height": 3257},
    },
    "docs/assets/screenshots/v1/product-tour/evidence-room-desktop.png": {
        "surface_id": "evidence-room",
        "alt_text": "Desktop empty Evidence Room showing Integrity is not truth and no durable evidence or decision briefs.",
        "route": "/workbench/evidence?execution_id=fixture-execution",
        "viewport": {"width": 1440, "height": 900},
        "color_scheme": "dark",
        "device_scale_factor": 2,
        "screenshot_scale": "css",
        "png_dimensions": {"width": 1440, "height": 2420},
    },
    "docs/assets/screenshots/v1/product-tour/evidence-room-mobile.png": {
        "surface_id": "evidence-room",
        "alt_text": "Mobile empty Evidence Room showing Integrity is not truth and no durable evidence or decision briefs.",
        "route": "/workbench/evidence?execution_id=fixture-execution",
        "viewport": {"width": 390, "height": 844},
        "color_scheme": "dark",
        "device_scale_factor": 2,
        "screenshot_scale": "css",
        "png_dimensions": {"width": 390, "height": 2781},
    },
}
RENDER_INPUTS = ("frontend/index.html", "frontend/playwright.config.ts", "frontend/pnpm-lock.yaml")
BROWSER_IDENTITY = "Ubuntu 24.04.4 LTS (x86_64); Google Chrome 153.0.8010.36; @playwright/test 1.60.0"
ALLOWED_PATHS = {HERO_PATH, *EXPECTED_SCREENSHOTS}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_path(value: object) -> str | None:
    if not isinstance(value, str) or not value or value.strip() != value:
        return None
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or ".." in candidate.parts or "\\" in value:
        return None
    return value


def _source_tree_sha256(root: Path, relative: str) -> tuple[str | None, str | None]:
    source_root = root / relative
    if not source_root.is_dir() or source_root.is_symlink():
        return None, "source tree is missing or unsafe"
    entries: list[Path] = []
    for path in source_root.rglob("*"):
        if path.is_symlink():
            return None, "source tree contains a symlink"
        if path.is_file():
            entries.append(path)
    digest = hashlib.sha256()
    for path in sorted(entries, key=lambda item: item.relative_to(source_root).as_posix()):
        digest.update(path.relative_to(source_root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest(), None


def _png_dimensions(path: Path) -> tuple[dict[str, int] | None, str | None]:
    header = path.read_bytes()[:24]
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        return None, "is not a PNG with an IHDR header"
    return {
        "width": int.from_bytes(header[16:20], "big"),
        "height": int.from_bytes(header[20:24], "big"),
    }, None


def _load_manifest(root: Path, path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    if not path.is_file():
        try:
            display_path = path.relative_to(root)
        except ValueError:
            display_path = path
        return None, [f"missing manifest: {display_path}"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return None, [f"invalid manifest JSON: {error}"]
    if not isinstance(data, dict):
        return None, ["manifest root must be an object"]
    return data, []


def audit(root: Path = ROOT, manifest_path: Path | None = None) -> list[str]:
    manifest_path = manifest_path or root / "docs/assets/visual-assets.v1.json"
    manifest, errors = _load_manifest(root, manifest_path)
    if manifest is None:
        return errors
    if manifest.get("schema_version") != "1.0":
        errors.append("manifest schema_version must be 1.0")
    if "fixture evidence only" not in str(manifest.get("claim_boundary", "")).lower():
        errors.append("manifest claim_boundary must retain the fixture-evidence ceiling")

    assets = manifest.get("assets")
    if not isinstance(assets, list):
        return errors + ["manifest assets must be a list"]

    seen: set[str] = set()
    for asset in assets:
        if not isinstance(asset, dict):
            errors.append("asset entry must be an object")
            continue
        relative = _safe_path(asset.get("path"))
        if relative is None:
            errors.append("asset has an unsafe path")
            continue
        if relative in seen:
            errors.append(f"duplicate asset: {relative}")
        seen.add(relative)
        if relative not in ALLOWED_PATHS:
            errors.append(f"asset is not allowlisted: {relative}")
            continue
        path = root / relative
        if not path.is_file():
            errors.append(f"missing asset: {relative}")
            continue
        expected_hash = asset.get("sha256")
        if not isinstance(expected_hash, str) or len(expected_hash) != 64:
            errors.append(f"asset has invalid sha256: {relative}")
        elif _sha256(path) != expected_hash:
            errors.append(f"asset hash mismatch: {relative}")

        if relative == HERO_PATH:
            _audit_hero(root, path, asset, errors)
        elif relative.startswith(SCREENSHOT_PREFIX):
            _audit_screenshot(root, asset, relative, errors)

    missing = sorted(ALLOWED_PATHS - seen)
    errors.extend(f"manifest is missing allowlisted asset: {path}" for path in missing)
    screenshot_root = root / SCREENSHOT_PREFIX
    actual_screenshots = {
        str(path.relative_to(root))
        for path in screenshot_root.rglob("*.png")
    } if screenshot_root.is_dir() else set()
    errors.extend(
        f"screenshot is not allowlisted: {path}"
        for path in sorted(actual_screenshots - set(EXPECTED_SCREENSHOTS))
    )
    errors.extend(
        f"allowlisted screenshot is missing from product-tour directory: {path}"
        for path in sorted(set(EXPECTED_SCREENSHOTS) - actual_screenshots)
    )
    return errors


def _audit_source_inputs(
    root: Path,
    provenance: object,
    errors: list[str],
    relative: str,
    *,
    require_generator: bool,
) -> None:
    if not isinstance(provenance, dict):
        errors.append(f"asset lacks fixture provenance: {relative}")
        return
    source_commit = provenance.get("source_base_commit")
    if source_commit != SOURCE_COMMIT:
        errors.append(f"asset provenance must pin source_base_commit {SOURCE_COMMIT}: {relative}")
    if provenance.get("source_state") != SOURCE_STATE:
        errors.append(f"asset provenance must pin source_state {SOURCE_STATE}: {relative}")
    source_keys = ("generator", "fixture_source") if require_generator else ("fixture_source",)
    hashes = provenance.get("input_hashes")
    if not isinstance(hashes, dict):
        errors.append(f"asset provenance lacks input hashes: {relative}")
        return
    for key in source_keys:
        value = _safe_path(provenance.get(key))
        if value is None:
            errors.append(f"asset provenance has unsafe {key}: {relative}")
            continue
        source_path = root / value
        if not source_path.is_file():
            errors.append(f"asset provenance has missing {key}: {relative}")
            continue
        expected_hash = hashes.get(key)
        if not isinstance(expected_hash, str) or len(expected_hash) != 64:
            errors.append(f"asset provenance has invalid {key} hash: {relative}")
        elif _sha256(source_path) != expected_hash:
            errors.append(f"asset provenance {key} hash mismatch: {relative}")


def _audit_hero(root: Path, path: Path, asset: dict[str, Any], errors: list[str]) -> None:
    if path.suffix != ".svg":
        errors.append(f"hero must be an SVG: {HERO_PATH}")
        return
    text = path.read_text(encoding="utf-8")
    accessibility = asset.get("accessibility")
    if not isinstance(accessibility, dict):
        errors.append("hero must declare accessibility metadata")
        return
    required = ("role", "aria_labelledby", "title_id", "description_id", "freeze_media_query", "light_media_query", "determinism_copy")
    metadata_errors: list[str] = []
    for key in required:
        value = accessibility.get(key)
        if not isinstance(value, str) or not value:
            metadata_errors.append(f"hero accessibility metadata missing {key}")
    errors.extend(metadata_errors)
    if metadata_errors:
        return
    markers = {
        "role": f'role="{accessibility["role"]}"',
        "aria_labelledby": f'aria-labelledby="{accessibility["aria_labelledby"]}"',
        "title_id": f'<title id="{accessibility["title_id"]}"',
        "description_id": f'<desc id="{accessibility["description_id"]}"',
        "freeze_media_query": accessibility["freeze_media_query"],
        "light_media_query": accessibility["light_media_query"],
        "determinism_copy": accessibility["determinism_copy"],
    }
    for key, marker in markers.items():
        if marker not in text:
            errors.append(f"hero SVG missing required {key} marker")
    _audit_source_inputs(root, asset.get("provenance"), errors, HERO_PATH, require_generator=False)
    provenance = asset.get("provenance")
    fixture_inputs = provenance.get("fixture_inputs") if isinstance(provenance, dict) else None
    if not isinstance(fixture_inputs, dict):
        errors.append("hero provenance lacks fixture inputs")
        return
    for name in ("study_pack", "runtime_truth_table"):
        binding = fixture_inputs.get(name)
        if not isinstance(binding, dict):
            errors.append(f"hero provenance missing {name} binding")
            continue
        relative = _safe_path(binding.get("path"))
        expected_hash = binding.get("sha256")
        if relative is None or not (root / relative).is_file():
            errors.append(f"hero provenance has invalid {name} path")
        elif not isinstance(expected_hash, str) or _sha256(root / relative) != expected_hash:
            errors.append(f"hero provenance {name} hash mismatch")


def _audit_screenshot(root: Path, asset: dict[str, Any], relative: str, errors: list[str]) -> None:
    provenance = asset.get("provenance")
    _audit_source_inputs(root, provenance, errors, relative, require_generator=True)
    expected = EXPECTED_SCREENSHOTS[relative]
    if asset.get("surface_id") != expected["surface_id"]:
        errors.append(f"screenshot surface_id mismatch: {relative}")
    if asset.get("alt_text") != expected["alt_text"]:
        errors.append(f"screenshot alt_text mismatch: {relative}")
    if not isinstance(asset.get("alt_text"), str) or len(asset["alt_text"].strip()) < 30:
        errors.append(f"screenshot alt_text must be meaningful: {relative}")
    if not isinstance(provenance, dict):
        return
    expected_render = {
        key: value
        for key, value in expected.items()
        if key in {"route", "viewport", "color_scheme", "device_scale_factor", "screenshot_scale", "png_dimensions"}
    }
    render = provenance.get("render")
    if render != expected_render:
        errors.append(f"screenshot provenance render metadata mismatch: {relative}")
    dimensions, png_error = _png_dimensions(root / relative)
    if png_error:
        errors.append(f"screenshot {png_error}: {relative}")
    elif dimensions != expected_render["png_dimensions"]:
        errors.append(f"screenshot pixel dimensions mismatch: {relative}")
    if provenance.get("png_sha256") != asset.get("sha256"):
        errors.append(f"screenshot provenance PNG digest mismatch: {relative}")
    if provenance.get("browser_identity") != BROWSER_IDENTITY:
        errors.append(f"screenshot provenance browser identity mismatch: {relative}")
    render_inputs = provenance.get("render_inputs")
    if not isinstance(render_inputs, dict):
        errors.append(f"screenshot provenance lacks render inputs: {relative}")
    else:
        for input_path in RENDER_INPUTS:
            expected_hash = render_inputs.get(input_path)
            source_path = root / input_path
            if not source_path.is_file():
                errors.append(f"screenshot provenance render input missing: {input_path}")
            elif not isinstance(expected_hash, str) or len(expected_hash) != 64:
                errors.append(f"screenshot provenance render input hash invalid: {input_path}")
            elif _sha256(source_path) != expected_hash:
                errors.append(f"screenshot provenance render input hash mismatch: {input_path}")
    if provenance.get("fixture_kind") != "synthetic_ui_mock":
        errors.append(f"screenshot provenance must be a synthetic UI mock: {relative}")
    source_tree = provenance.get("source_tree")
    if source_tree != "frontend/src":
        errors.append(f"screenshot provenance must pin frontend/src source tree: {relative}")
        return
    actual_tree_hash, tree_error = _source_tree_sha256(root, source_tree)
    if tree_error:
        errors.append(f"screenshot provenance {tree_error}: {relative}")
        return
    expected_tree_hash = provenance.get("source_tree_sha256")
    if not isinstance(expected_tree_hash, str) or len(expected_tree_hash) != 64:
        errors.append(f"screenshot provenance has invalid source tree hash: {relative}")
    elif actual_tree_hash != expected_tree_hash:
        errors.append(f"screenshot provenance source tree hash mismatch: {relative}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check pinned public documentation visual assets.")
    parser.add_argument("--check", action="store_true", help="Validate the checked-in visual asset manifest.")
    args = parser.parse_args()
    errors = audit()
    if errors:
        for error in errors:
            print(f"[doc-visual-assets] FAIL: {error}", file=sys.stderr)
        print("[doc-visual-assets] claim ceiling: fixture evidence only; not benchmark, live-provider, usability, or release assurance evidence.", file=sys.stderr)
        return 1
    print("[doc-visual-assets] PASS: allowlisted assets exist and match pinned fixture provenance.")
    print("[doc-visual-assets] claim ceiling: fixture evidence only; not benchmark, live-provider, usability, or release assurance evidence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
