from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_authoritative_release_metadata_and_verifier_exist() -> None:
    metadata_path = ROOT / "release" / "release-metadata.json"
    verifier = ROOT / "scripts" / "verify-release-metadata.py"

    assert metadata_path.is_file()
    assert verifier.is_file()
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata == {
        "schema_version": "scaffold-arena-release-metadata-v1",
        "version": "0.9.1",
        "status": "release-candidate",
        "protocol_version": "1.0",
        "tag": "v0.9.1",
        "released_at": "2026-08-23",
    }

    result = subprocess.run(
        [sys.executable, str(verifier), "--root", str(ROOT)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "PASS"
    assert payload["release_status"] == "release-candidate"


def test_release_candidate_is_not_advertised_as_published_before_tag_workflow() -> None:
    citation = _read("CITATION.cff")
    changelog = _read("CHANGELOG.md")

    assert 'version: "0.9.1"' in citation
    assert 'date-released: "2026-08-23"' in citation
    assert "## [0.9.1] - 2026-08-23" in changelog
    candidate = changelog.split("## [0.9.1] - 2026-08-23", 1)[1].split(
        "## [0.9.0]", 1
    )[0]
    assert "releases/tag/v0.9.1" in candidate
    assert "not yet created" in candidate
    assert "has not been published or deployed" in candidate


def test_code_ownership_covers_high_risk_boundaries() -> None:
    codeowners = _read(".github/CODEOWNERS")

    for required in (
        "* @jlov7",
        "/backend/protocol_v1/ @jlov7",
        "/backend/evidence_v1/ @jlov7",
        "/backend/auth_v1/ @jlov7",
        "/.github/workflows/ @jlov7",
        "/release/ @jlov7",
        "/SECURITY.md @jlov7",
    ):
        assert required in codeowners
    assert (ROOT / "MAINTAINERS.md").is_file()


def test_release_workflow_is_pinned_attested_signed_and_fail_closed() -> None:
    workflow = _read(".github/workflows/release.yml")

    for required in (
        "tags:",
        "- 'v*'",
        "id-token: write",
        "attestations: write",
        "artifact-metadata: write",
        "packages: write",
        "actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6",
        "anchore/sbom-action@e22c389904149dbc22b58101806040fa8d37a610",
        "sigstore/cosign-installer@6f9f17788090df1f26f669e9d70d6ae9567deba6",
        "cosign sign-blob",
        "cosign sign --yes",
        "gh release create",
        "--verify-tag",
        "verify-release-metadata.py",
    ):
        assert required in workflow

    # No floating third-party action references are accepted in the release path.
    uses = re.findall(r"uses:\s*([^\s#]+)", workflow)
    assert uses
    for action in uses:
        assert re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", action), action

    # Manual validation may exercise the workflow but cannot reach publication.
    assert "workflow_dispatch:" in workflow
    assert "if: github.event_name == 'push'" in workflow
