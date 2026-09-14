from __future__ import annotations

import json

from arena_cli.cli import main
from tests.services_v1.test_decision_service import _decision_service, _request


def test_results_brief_uses_durable_service_without_starting_provider(tmp_path, capsys) -> None:
    service, report = _decision_service(tmp_path)
    request_path = tmp_path / "brief.json"
    request_path.write_text(json.dumps(_request(str(report["id"]))))
    database = str(service.repository.engine.url)
    result = main([
        "results", "brief", "--database", database, "--artifacts",
        str(service.artifact_store.root), "--project", "personal", "--input", str(request_path),
    ])
    output = json.loads(capsys.readouterr().out)
    assert result == 0
    assert output["provider_execution_started"] is False
