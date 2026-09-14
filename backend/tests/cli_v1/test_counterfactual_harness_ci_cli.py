from __future__ import annotations

import json
from pathlib import Path

from arena_cli.cli import main


_EXAMPLES = Path(__file__).parents[3] / "examples" / "counterfactual-replay"


def test_provider_free_counterfactual_cli_writes_machine_report_without_starting_a_provider(tmp_path: Path, capsys) -> None:
    replay = tmp_path / "replay.json"
    replay.write_bytes((_EXAMPLES / "fixture-replay.json").read_bytes())
    output = tmp_path / "replay-report.json"

    assert main(["counterfactual-replay", "--input", str(replay), "--output", str(output)]) == 2
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["verdict"] == "HOLD"
    assert report["provider_execution_started"] is False
    assert report["execution_started"] is False
    assert report["network_requested"] is False
    assert '"usage_state": "unknown"' in capsys.readouterr().out

    declared_live = json.loads(replay.read_text(encoding="utf-8"))
    declared_live["mode"] = "live"
    replay.write_text(json.dumps(declared_live), encoding="utf-8")
    assert main(["counterfactual-replay", "--input", str(replay)]) == 2
    assert "live_flag_required" in capsys.readouterr().out


def test_harness_ci_cli_writes_json_summary_and_pr_comment_artifacts(tmp_path: Path, capsys) -> None:
    replay = tmp_path / "replay.json"
    base = tmp_path / "base.json"
    candidate = tmp_path / "candidate.json"
    policy = tmp_path / "policy.json"
    output = tmp_path / "report.json"
    summary = tmp_path / "summary.md"
    comment = tmp_path / "comment.md"
    replay.write_bytes((_EXAMPLES / "fixture-replay.json").read_bytes())
    base.write_bytes((_EXAMPLES / "fixture-base.json").read_bytes())
    candidate.write_bytes((_EXAMPLES / "fixture-candidate.json").read_bytes())
    policy.write_bytes((_EXAMPLES / "fixture-policy.json").read_bytes())

    assert main([
        "harness-ci", "--replay", str(replay), "--base", str(base), "--candidate", str(candidate),
        "--policy", str(policy), "--output", str(output), "--summary", str(summary), "--comment-output", str(comment),
    ]) == 2
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["verdict"] == "HOLD"
    assert report["provider_execution_started"] is False
    assert "## Harness CI" in summary.read_text(encoding="utf-8")
    assert comment.read_text(encoding="utf-8") == report["pr_comment_body"] + "\n"
    assert '"pr_comment_body"' in capsys.readouterr().out
