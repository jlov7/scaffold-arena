from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "backend"
EXAMPLES = ROOT / "examples"


def _run_python(*args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("SCAFFOLD_ARENA_PROVIDER", None)
    env.pop("OPENAI_API_KEY", None)
    env.pop("ANTHROPIC_API_KEY", None)
    return subprocess.run(
        [sys.executable, *args],
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def _run_arena(*args: str) -> subprocess.CompletedProcess[str]:
    return _run_python("-m", "arena_cli", *args, cwd=BACKEND)


def _json_stdout(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    assert result.stdout.strip(), result.stderr
    return json.loads(result.stdout)


def test_public_example_manifests_are_complete() -> None:
    required = {
        "compare-two-harnesses",
        "context-compaction-ablation",
        "memory-policy-study",
        "recovery-fault-injection",
        "permission-boundary-study",
        "local-model-harness-comparison",
        "harness-pr-regression",
        "counterfactual-replay",
    }
    for example_id in sorted(required):
        directory = EXAMPLES / example_id
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["schema_version"] == "scaffold-arena.public-example/1"
        assert manifest["example_id"] == example_id
        assert manifest["run"]["command"]
        assert manifest["inputs"]
        assert manifest["expected"]
        assert manifest["evidence_ceiling"]
        assert "focused_test" in manifest
        assert "cleanup" in manifest
        assert manifest["pinned_screenshot"]["status"] in {"HOLD", "PASS"}
        assert (directory / "README.md").is_file()


def test_compare_two_harnesses_fails_closed(tmp_path: Path) -> None:
    output = tmp_path / "compare.json"
    result = _run_python(
        str(EXAMPLES / "compare-two-harnesses" / "run.py"),
        "--output",
        str(output),
    )
    assert result.returncode == 2, result.stderr
    report = _json_stdout(result)
    assert report["verdict"] == "HOLD"
    assert report["code"] == "second_checked_harness_not_supplied"
    assert report["provider_execution_started"] is False
    assert report["execution_started"] is False
    assert report["network_requested"] is False
    assert report["comparison_emitted"] is False
    assert report["source_digests"]["study_pack"] == (
        "sha256:b06d93be7ccbafd9578b60fe0f485afcc57031b46c1cc6b114a05c42675a189c"
    )
    assert report["source_digests"]["runtime_truth_table"] == (
        "sha256:92587ad86a7623b55b57fe1efcd5b4d84da907dd729e30be0ee719a7886c738d"
    )
    assert len(report["harnesses"]) == 1
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted == report

    output.write_text("keep me\n", encoding="utf-8")
    refused = _run_python(
        str(EXAMPLES / "compare-two-harnesses" / "run.py"),
        "--output",
        str(output),
    )
    assert refused.returncode == 2
    assert output.read_text(encoding="utf-8") == "keep me\n"
    assert _json_stdout(refused)["code"] == "output_exists"


def test_context_compaction_example_preserves_unknown_usage(tmp_path: Path) -> None:
    output = tmp_path / "context-compaction.json"
    result = _run_arena(
        "harness-ci",
        "--replay",
        str(EXAMPLES / "counterfactual-replay" / "fixture-replay.json"),
        "--base",
        str(EXAMPLES / "counterfactual-replay" / "fixture-base.json"),
        "--candidate",
        str(EXAMPLES / "counterfactual-replay" / "fixture-candidate.json"),
        "--policy",
        str(EXAMPLES / "counterfactual-replay" / "fixture-policy.json"),
        "--output",
        str(output),
    )
    assert result.returncode == 2, result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["verdict"] == "HOLD"
    assert report["usage_state"] == "unknown"
    assert report["provider_execution_started"] is False
    assert report["execution_started"] is False
    assert report["network_requested"] is False
    assert report["effects"][1]["point_estimate"] is None
    assert report["effects"][1]["candidate_mean"] is None


def test_memory_policy_example_keeps_fixture_ceiling(tmp_path: Path) -> None:
    workspace = tmp_path / "memory-policy"
    result = _run_arena("demo", "--path", str(workspace))
    assert result.returncode == 0, result.stderr
    report = _json_stdout(result)
    assert report["verdict"] == "PASS"
    assert report["evidence_class"] == "fixture"
    assert report["provider_execution_started"] is False
    assert report["verified_truth_table_rows"] == 80
    assert "fixture" in str(report["claim_ceiling"]).lower()
    copied_pack = json.loads(
        (workspace / "study_packs" / "offline-demo-v1" / "study-pack.json").read_text(encoding="utf-8")
    )
    memory = next(
        factor
        for factor in copied_pack["experiments"][0]["factors"]
        if factor["factor_id"] == "memory"
    )
    assert memory["levels"] == [False, True]
    assert memory["fixed_infrastructure"]["runtime_state"] == "not_run"


def test_recovery_example_runs_bounded_model() -> None:
    result = _run_python(
        "scripts/check-lifecycle-model.py",
        "--depth",
        "8",
        "--generations",
        "2",
    )
    assert result.returncode == 0, result.stderr
    report = _json_stdout(result)
    assert report["status"] == "pass"
    assert "bounded engineering model" in report["claim_ceiling"]
    assert "budget_is_not_double_committed" in report["invariants"]


def test_harness_pr_regression_preserves_hold_artifacts(tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    summary_path = tmp_path / "summary.md"
    comment_path = tmp_path / "comment.md"
    result = _run_arena(
        "harness-ci",
        "--replay",
        str(EXAMPLES / "counterfactual-replay" / "fixture-replay.json"),
        "--base",
        str(EXAMPLES / "counterfactual-replay" / "fixture-base.json"),
        "--candidate",
        str(EXAMPLES / "counterfactual-replay" / "fixture-candidate.json"),
        "--policy",
        str(EXAMPLES / "counterfactual-replay" / "fixture-policy.json"),
        "--output",
        str(report_path),
        "--summary",
        str(summary_path),
        "--comment-output",
        str(comment_path),
    )
    assert result.returncode == 2, result.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["verdict"] == "HOLD"
    assert report["usage_state"] == "unknown"
    assert report["provider_execution_started"] is False
    assert report["network_requested"] is False
    assert "HOLD" in summary_path.read_text(encoding="utf-8")
    assert comment_path.read_text(encoding="utf-8").strip() == report["pr_comment_body"]
    assert report["pr_comment_body"]
    assert "posted" not in report["pr_comment_body"].lower()


def test_counterfactual_replay_example_preserves_hold(tmp_path: Path) -> None:
    output = tmp_path / "replay.json"
    result = _run_arena(
        "harness-ci",
        "--replay",
        str(EXAMPLES / "counterfactual-replay" / "fixture-replay.json"),
        "--base",
        str(EXAMPLES / "counterfactual-replay" / "fixture-base.json"),
        "--candidate",
        str(EXAMPLES / "counterfactual-replay" / "fixture-candidate.json"),
        "--policy",
        str(EXAMPLES / "counterfactual-replay" / "fixture-policy.json"),
        "--output",
        str(output),
    )
    assert result.returncode == 2, result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["verdict"] == "HOLD"
    assert report["usage_state"] == "unknown"
    assert report["provider_execution_started"] is False
    assert report["network_requested"] is False
