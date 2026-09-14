from __future__ import annotations

import json
from pathlib import Path

import arena_cli.demo as demo_module
from arena_cli.cli import main


def test_demo_creates_a_verified_fixture_decision_card_without_a_provider(
    tmp_path: Path,
    capsys,
) -> None:
    workspace = tmp_path / "demo"

    assert main(["demo", "--path", str(workspace)]) == 0
    emitted = json.loads(capsys.readouterr().out)
    persisted = json.loads(
        (workspace / ".arena" / "demo-summary.json").read_text(encoding="utf-8")
    )

    assert emitted == persisted
    assert emitted["verdict"] == "PASS"
    assert emitted["mode"] == "verified_fixture_replay"
    assert emitted["evidence_class"] == "fixture"
    assert emitted["provider_execution_started"] is False
    assert emitted["study_pack"] == "offline-demo-v1@1.0.0"
    assert emitted["expected_attempts"] == 80
    assert emitted["verified_truth_table_rows"] == 80
    assert emitted["decision"]["status"] == "DESCRIPTIVE_ONLY"
    effects = {item["factor_id"]: item for item in emitted["decision"]["main_effects"]}
    assert effects["planning"]["risk_difference"] == 0.3125
    assert effects["verification"]["risk_difference"] == 0.3125
    assert effects["recovery"]["risk_difference"] == 0.0625
    assert effects["memory"]["risk_difference"] == 0.0625
    assert Path(emitted["workspace"]) == workspace.resolve()
    assert (workspace / ".arena" / "provenance.json").is_file()
    assert (workspace / "study_packs" / "offline-demo-v1" / "study-pack.json").is_file()
    assert "pytest" in emitted["full_execution_command"]
    assert "fixture" in emitted["claim_ceiling"].lower()


def test_demo_refuses_to_overwrite_an_existing_workspace(
    tmp_path: Path,
    capsys,
) -> None:
    workspace = tmp_path / "demo"
    workspace.mkdir()
    (workspace / "keep.txt").write_text("do not overwrite", encoding="utf-8")

    assert main(["demo", "--path", str(workspace)]) == 2
    emitted = json.loads(capsys.readouterr().out)
    assert emitted["verdict"] == "HOLD"
    assert emitted["code"] == "workspace_not_empty"
    assert (workspace / "keep.txt").read_text(encoding="utf-8") == "do not overwrite"


def test_demo_failure_leaves_no_partial_or_staging_workspace(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    workspace = tmp_path / "demo"

    def fail_after_workspace_mutation(*args, **kwargs):
        del args, kwargs
        raise ValueError("injected digest failure")

    monkeypatch.setattr(demo_module, "sha256_bytes", fail_after_workspace_mutation)

    assert main(["demo", "--path", str(workspace)]) == 2
    emitted = json.loads(capsys.readouterr().out)
    assert emitted["verdict"] == "HOLD"
    assert emitted["code"] == "demo_fixture_hold"
    assert not workspace.exists()
    assert not tuple(tmp_path.glob(".demo.staging-*"))
