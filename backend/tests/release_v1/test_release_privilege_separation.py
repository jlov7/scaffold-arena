from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
READ = "read"
WRITE = "write"


def test_release_build_and_publication_are_privilege_separated() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    )
    jobs = workflow["jobs"]

    assert workflow["permissions"] == {"contents": READ}
    assert set(jobs) == {"verify-build", "publish"}
    assert jobs["verify-build"]["permissions"] == {"contents": READ}
    assert "id-token" not in jobs["verify-build"]["permissions"]
    assert "packages" not in jobs["verify-build"]["permissions"]
    assert f"contents: {WRITE}" not in json.dumps(jobs["verify-build"])

    publish = jobs["publish"]
    assert publish["needs"] == ["verify-build"]
    assert publish["if"] == "github.event_name == 'push'"
    assert publish["permissions"] == {
        "actions": READ,
        "artifact-metadata": WRITE,
        "attestations": WRITE,
        "contents": WRITE,
        "id-token": WRITE,
        "packages": WRITE,
    }
    publish_text = json.dumps(publish)
    assert "./scripts/verify-all.sh" not in publish_text
    assert "pnpm install" not in publish_text
    assert "uv build" not in publish_text
    assert "docker build" not in publish_text
    assert "docker load" in publish_text
