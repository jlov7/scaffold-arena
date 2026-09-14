from __future__ import annotations

import json
from pathlib import Path

from arena_cli.cli import main


_FIXTURES = Path(__file__).parents[3] / "examples" / "arena-forge"


def test_forge_cli_keeps_proposal_untrusted_and_plans_without_execution(tmp_path: Path, capsys) -> None:
    proposal_output = tmp_path / "proposal.json"
    assert main(["forge", "proposal", "--input", str(_FIXTURES / "proposal.json"), "--output", str(proposal_output)]) == 2
    proposal = json.loads(proposal_output.read_text(encoding="utf-8"))
    assert proposal["state"] == "PENDING_APPROVAL"
    assert proposal["untrusted"] is True
    assert proposal["execution_started"] is False
    assert proposal["automatic_merge"] is False

    plan_output = tmp_path / "plan.json"
    assert main(["forge", "plan", "--input", str(_FIXTURES / "planner-exploratory.json"), "--output", str(plan_output)]) == 0
    plan = json.loads(plan_output.read_text(encoding="utf-8"))
    assert plan["verdict"] == "READY"
    assert plan["execution_started"] is False
    assert plan["recommendations"][0]["proposed_design"]["design_id"] == "context-design"
    assert '"network_requested": false' in capsys.readouterr().out


def test_forge_process_safety_cli_reports_controls_and_evaluation_is_hold(capsys) -> None:
    assert main(["forge", "process-safety", "--input", str(_FIXTURES / "process-safety-pass.json")]) == 0
    assert '"raw_sensitive_content_retained": false' in capsys.readouterr().out
    assert main(["forge", "evaluate"]) == 2
    assert "forge_evaluation_service_required" in capsys.readouterr().out
