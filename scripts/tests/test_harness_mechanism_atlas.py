from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "scripts/generate-harness-mechanism-atlas.py"
VALIDATOR = ROOT / "scripts/validate-harness-mechanism-atlas.py"


def run(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(script), *args], cwd=ROOT, text=True, capture_output=True, check=False)


def run_with_path(script: Path, path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PATH": str(path)}
    return subprocess.run([sys.executable, str(script), *args], cwd=ROOT, text=True, capture_output=True, check=False, env=env)


def test_generator_check_is_current_and_provider_free():
    result = run(GENERATOR, "--check")
    assert result.returncode == 0, result.stderr
    assert "current" in result.stdout


def test_validator_returns_bounded_pass_and_signature_hold(tmp_path: Path):
    result = run(VALIDATOR)
    assert result.returncode == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "PASS"
    hold = run(VALIDATOR, "--require-signature", str(tmp_path / "missing.sigstore.json"))
    assert hold.returncode == 2
    assert json.loads(hold.stdout)["verdict"] == "HOLD_RELEASE_SIGNATURE_REQUIRED"


def test_validator_cryptographically_verifies_signature_bundle(tmp_path: Path):
    bundle = tmp_path / "fake.sigstore.json"
    bundle.write_text("not a signature")
    cosign = tmp_path / "cosign"
    cosign.write_text("#!/bin/sh\nexit 1\n")
    cosign.chmod(0o755)
    rejected = run_with_path(VALIDATOR, tmp_path, "--require-signature", str(bundle))
    assert rejected.returncode == 1
    assert json.loads(rejected.stdout)["verdict"] == "FAIL"


def test_validator_rejects_tampered_atlas_without_rewriting(tmp_path: Path):
    original = ROOT / "backend/genome_v1/data/harness_mechanism_atlas_v1.json"
    tampered = tmp_path / "atlas.json"
    payload = json.loads(original.read_text())
    payload["claim_ceiling"] = "certified runtime"
    tampered.write_text(json.dumps(payload))
    result = run(VALIDATOR, "--atlas", str(tampered))
    assert result.returncode == 1
    assert json.loads(result.stdout)["verdict"] == "FAIL"
