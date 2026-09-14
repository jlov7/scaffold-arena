from __future__ import annotations

import asyncio
import importlib.util
import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest
from adapters_v1.context_handoff import ContextHandoffOllamaAdapter
from adapters_v1.context_handoff.models import EXPECTED_MODEL_DIGEST
from evaluation_v1 import TrustedGraderRegistry, compile_grader_plan
from evaluation_v1.models import EvaluationContext
from persistence_v1.schema import attempts, evaluations
from protocol_v1 import canonical_json, load_study_pack
from sqlalchemy import update

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "context_handoff_runner", ROOT / "scripts" / "run-context-handoff-local.py"
)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)
VERIFY_SPEC = importlib.util.spec_from_file_location(
    "context_handoff_verifier", ROOT / "scripts" / "check-context-handoff-evidence.py"
)
assert VERIFY_SPEC and VERIFY_SPEC.loader
verifier = importlib.util.module_from_spec(VERIFY_SPEC)
VERIFY_SPEC.loader.exec_module(verifier)


def _checkout(tmp_path: Path) -> Path:
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "README.md").write_text("test\n")
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "test",
        ],
        check=True,
    )
    return root


def _adapter(
    calls: list[str],
    *,
    malformed: bool = False,
    bad_identity: bool = False,
    failure: str | None = None,
    observe=None,
) -> ContextHandoffOllamaAdapter:
    async def handler(request: httpx.Request) -> httpx.Response:
        if observe:
            observe(request)
        calls.append(request.url.path)
        if request.url.path == "/api/version":
            return httpx.Response(
                200,
                json={
                    "version": "0.34.1"
                    if failure == "post_identity" and calls.count("/api/version") == 2
                    else "0.34.0"
                },
            )
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "qwen3.5:4b",
                            "model": "qwen3.5:4b",
                            "digest": "b" * 64
                            if bad_identity
                            else EXPECTED_MODEL_DIGEST,
                            "details": {"context_length": 262144},
                        }
                    ]
                },
            )
        if failure == "timeout":
            raise httpx.ReadTimeout("mock timeout")
        if failure == "exception":
            raise RuntimeError("injected transport crash")
        if failure == "cancel":
            asyncio.current_task().cancel()
            await asyncio.sleep(0)
        if failure == "process_exit":
            import os

            os._exit(23)
        return httpx.Response(
            200,
            json={
                "model": "qwen3.5:4b",
                "message": {
                    "role": "assistant",
                    "content": "not-json"
                    if malformed
                    else '{"answer":"hold","evidence":"receipt"}',
                },
                "done": True,
                "prompt_eval_count": 3841
                if failure == "context_budget"
                else 3840
                if failure == "boundary_usage"
                else 12,
                "eval_count": 256
                if failure in {"boundary_usage", "context_budget"}
                else 257
                if failure == "output_budget"
                else 3,
            },
        )

    return ContextHandoffOllamaAdapter(
        endpoint="http://127.0.0.1:11434/api",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def test_complete_mocked_context_study_uses_real_registry_workers_and_evaluator(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    output = tmp_path / "evidence"
    actual_requests = []

    def observe(request):
        initial = json.loads((output / "initial.json").read_bytes())
        assert len(initial["rows"]) == 24
        assert all(row["attempt_status"] == "queued" for row in initial["rows"])
        assert (output / "arena.db").is_file()
        if request.method == "POST":
            actual_requests.append(json.loads(request.content))

    result = asyncio.run(
        runner.run_context_handoff_study(
            output=output,
            adapter=_adapter(calls, observe=observe),
            repo_root=_checkout(tmp_path),
        )
    )
    assert result["preflight"]["verdict"] == "PASS" and result["fatal_reason"] is None
    assert len(result["ledger"]["attempts"]) == 24
    assert {row["status"] for row in result["ledger"]["attempts"]} == {"completed"}
    checked = verifier.verify(tmp_path / "evidence")
    assert checked["integrity"] == "PASS", checked
    assert checked["completed"] is True
    assert all(
        row["evaluations"][0]["result"]["grader_results"][-1]["metric_id"]
        == "context-delivery"
        for row in result["ledger"]["evidence"]["rows"]
    )
    assert calls.count("/api/chat") == 24
    pack = load_study_pack(runner.STUDY_PACK)
    from adapters_v1.context_handoff.models import (
        CONTEXT_HANDOFF_NAMESPACE,
        ContextPacket,
    )
    from adapters_v1.context_handoff.render import render_context

    scenarios = {s.scenario_id: s for s in pack.scenarios}
    for request, cell in zip(
        actual_requests,
        pack.experiments[0].extensions[runner.SCHEDULE]["cells"],
        strict=True,
    ):
        scenario = scenarios[cell["scenario_id"]]
        prompt, _ = render_context(
            task=scenario.prompt,
            packet=ContextPacket.model_validate(
                scenario.extensions[CONTEXT_HANDOFF_NAMESPACE]["packet"]
            ),
            policy=cell["context_policy"],
        )
        assert request["messages"][0]["content"] == prompt
        assert (
            request["options"]["seed"]
            == int(
                runner.sha256(
                    {
                        "scenario_id": cell["scenario_id"],
                        "repetition_index": cell["repetition_index"],
                        "declared_seed": cell["declared_seed"],
                    }
                )[:16],
                16,
            )
            % 2**31
        )
    for row in result["ledger"]["evidence"]["rows"]:
        grades = row["evaluations"][0]["result"]["grader_results"]
        assert grades[-1]["passed"] is True
        assert grades[1]["passed"] is True
    before = {str(p): p.read_bytes() for p in output.rglob("*") if p.is_file()}
    assert verifier.verify(output)["completed"]
    assert before == {str(p): p.read_bytes() for p in output.rglob("*") if p.is_file()}


def test_fatal_attempt_retains_started_terminal_and_all_undispatched_cells(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    result = asyncio.run(
        runner.run_context_handoff_study(
            output=tmp_path / "evidence",
            adapter=_adapter(calls, bad_identity=True),
            repo_root=_checkout(tmp_path),
        )
    )
    statuses = [row["status"] for row in result["ledger"]["attempts"]]
    assert statuses.count("not_started_due_to_fatal_stop") == 23
    assert any(status != "not_started_due_to_fatal_stop" for status in statuses)
    assert calls.count("/api/chat") == 0
    checked = verifier.verify(tmp_path / "evidence")
    assert checked["integrity"] == "PASS", checked
    assert checked["completed"] is False and checked["study_status"] == "partial"


@pytest.fixture(scope="module")
def complete_evidence(tmp_path_factory):
    root = tmp_path_factory.mktemp("context-evidence")
    result = asyncio.run(
        runner.run_context_handoff_study(
            output=root / "evidence", adapter=_adapter([]), repo_root=_checkout(root)
        )
    )
    assert result["fatal_reason"] is None
    assert verifier.verify(root / "evidence")["completed"]
    return root / "evidence"


def test_recipient_can_verify_relocated_evidence_without_mutation(
    complete_evidence, tmp_path
):
    relocated = tmp_path / "relocated"
    shutil.copytree(complete_evidence, relocated)
    before = {str(p): p.read_bytes() for p in relocated.rglob("*") if p.is_file()}
    result = verifier.verify(relocated)
    assert result["completed"], result
    assert before == {
        str(p): p.read_bytes() for p in relocated.rglob("*") if p.is_file()
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("seed", 1),
        ("num_predict", 257),
        ("num_ctx", 8192),
        ("temperature", 1.0),
        ("top_p", 0.5),
        ("model", "other"),
        ("prompt", "forged inherited context"),
    ],
)
def test_rehashed_transport_request_tampering_is_reconstructed(
    complete_evidence, tmp_path, field, value
):
    root = tmp_path / "evidence"
    shutil.copytree(complete_evidence, root)
    transport = json.loads((root / "transport.json").read_bytes())
    post = next(
        t for t in transport if t["method"] == "POST" and t["phase"] == "request"
    )
    store = runner.LocalArtifactStore(root / "artifacts")
    request = json.loads(store.get_bytes(post["digest"]))
    if field == "model":
        request[field] = value
    elif field == "prompt":
        request["messages"][0]["content"] = value
    else:
        request["options"][field] = value
    post["digest"] = store.put_bytes(canonical_json(request))
    runner._write(root / "transport.json", transport)
    runner._seal(root)
    result = verifier.verify(root)
    assert (
        result["integrity"] == "HOLD"
        and "actual request/rendered delivery" in result["errors"][0]
    ), result


@pytest.mark.parametrize(
    "target",
    [
        "cohort",
        "freeze",
        "provenance",
        "schedule",
        "usage",
        "pricing",
        "terminal",
        "evaluation",
        "receipt",
        "identity",
        "cache",
        "extra_manifest",
        "missing_artifact",
        "source",
    ],
)
def test_retained_content_bindings_fail_closed(complete_evidence, tmp_path, target):
    root = tmp_path / "evidence"
    shutil.copytree(complete_evidence, root)
    ledger = json.loads((root / "ledger.json").read_bytes())
    store = runner.LocalArtifactStore(root / "artifacts")
    engine = runner.create_persistence_engine(f"sqlite:///{root / 'arena.db'}")
    repo = runner.ArenaRepository(engine)
    row = ledger["evidence"]["rows"][0]
    if target in {"usage", "terminal", "receipt", "identity"}:
        metadata = row["result_metadata"]
        if target == "usage":
            metadata["usage"]["input_tokens"] += 1
        elif target == "terminal":
            metadata["terminal_envelope"]["response_hash"] = "a" * 64
        else:
            key = (
                "context-renderer-receipt"
                if target == "receipt"
                else "runtime-identity"
            )
            value = json.loads(store.get_bytes(metadata["artifact_ids"][key]))
            if target == "receipt":
                value["included_segment_ids"] = ["forged"]
            else:
                value["after"]["model_digest"] = "b" * 64
            metadata["artifact_ids"][key] = store.put_bytes(canonical_json(value))
        with engine.begin() as conn:
            conn.execute(
                update(attempts)
                .where(attempts.c.id == row["attempt_id"])
                .values(result_metadata=metadata)
            )
    elif target == "evaluation":
        evaluation = row["evaluations"][0]
        evaluation["result"]["grader_results"][0]["score"] = 0.991
        digest = store.put_bytes(canonical_json(evaluation["result"]))
        repo.register_artifact(
            digest,
            size_bytes=len(store.get_bytes(digest)),
            storage_uri=store.uri_for(digest),
            media_type="application/json",
            content_metadata={},
        )
        with engine.begin() as conn:
            conn.execute(
                update(evaluations)
                .where(evaluations.c.id == evaluation["id"])
                .values(
                    result=evaluation["result"],
                    result_hash=digest,
                    result_artifact_digest=digest,
                )
            )
    elif target == "pricing":
        from persistence_v1.schema import usage_ledger

        with engine.begin() as conn:
            conn.execute(update(usage_ledger).values(price_catalog_revision="forged"))
    elif target == "cohort":
        path = root / "study-pack/study-pack.json"
        pack = json.loads(path.read_bytes())
        pack["scenarios"][0]["cluster_id"] = "changed"
        runner._write(path, pack)
    elif target in {"freeze", "schedule"}:
        ledger["freeze_hash" if target == "freeze" else "attempts"] = "a" * 64
    elif target == "provenance":
        path = root / "provenance.json"
        value = json.loads(path.read_bytes())
        value["material"]["runtime_image_hash"]["version"] = "forged"
        runner._write(path, value)
    elif target == "cache":
        path = root / "accounting.json"
        value = json.loads(path.read_bytes())
        value[0]["cache_savings_usd"] = 1
        runner._write(path, value)
    elif target == "extra_manifest":
        (root / "artifacts/manifest.json").write_text("unsealed")
    elif target == "missing_artifact":
        store._path(row["result_metadata"]["output_artifact_digest"]).unlink()
    elif target == "source":
        (root / "source/README.md").write_text("changed")
    ledger["evidence"] = json.loads(
        runner._json_bytes(runner._snapshot(repo, ledger["execution_id"]))
    )
    runner._write(root / "ledger.json", ledger)
    engine.dispose()
    if target != "extra_manifest":
        runner._seal(root)
    result = verifier.verify(root)
    assert result["integrity"] == "HOLD", (target, result)


@pytest.mark.parametrize(
    "failure",
    [
        "timeout",
        "exception",
        "cancel",
        "post_identity",
        "context_budget",
        "output_budget",
    ],
)
def test_started_failure_retains_raw_request_and_fixed_denominator(tmp_path, failure):
    root = tmp_path / "evidence"
    calls = []
    try:
        asyncio.run(
            runner.run_context_handoff_study(
                output=root,
                adapter=_adapter(calls, failure=failure),
                repo_root=_checkout(tmp_path),
            )
        )
    except asyncio.CancelledError:
        assert failure == "cancel"
    ledger = json.loads((root / "ledger.json").read_bytes())
    assert len(ledger["attempts"]) == 24
    assert calls.count("/api/chat") == 1
    assert (
        sum(r["status"] == "not_started_due_to_fatal_stop" for r in ledger["attempts"])
        == 23
    )
    checked = verifier.verify(root)
    assert checked["integrity"] == "PASS" and checked["completed"] is False, checked
    if failure in {"post_identity", "context_budget", "output_budget"}:
        assert "HOLD_" in ledger["fatal_reason"]


def test_all24_at_provider_total_token_boundary(tmp_path):
    calls = []
    root = tmp_path / "evidence"
    result = asyncio.run(
        runner.run_context_handoff_study(
            output=root,
            adapter=_adapter(calls, failure="boundary_usage"),
            repo_root=_checkout(tmp_path),
        )
    )
    assert result["fatal_reason"] is None, result["fatal_reason"]
    assert calls.count("/api/chat") == 24
    assert (
        sum(
            row["result_metadata"]["usage"]["total_tokens"]
            for row in result["ledger"]["evidence"]["rows"]
        )
        == 98304
    )
    assert verifier.verify(root)["completed"]


def test_bad_output_is_retained_as_failure_evidence_without_replacement(tmp_path):
    root = tmp_path / "evidence"
    calls = []
    result = asyncio.run(
        runner.run_context_handoff_study(
            output=root,
            adapter=_adapter(calls, malformed=True),
            repo_root=_checkout(tmp_path),
        )
    )
    assert calls.count("/api/chat") == 24
    for row in result["ledger"]["evidence"]["rows"]:
        grades = row["evaluations"][0]["result"]["grader_results"]
        assert (
            not grades[0]["passed"] and not grades[1]["passed"] and grades[-1]["passed"]
        )
    assert verifier.verify(root)["completed"]


def test_preconditions_send_no_provider_requests(tmp_path):
    calls = []
    checkout = _checkout(tmp_path)
    (checkout / "README.md").write_text("dirty")
    with pytest.raises(runner.ContextStudyError):
        asyncio.run(
            runner.run_context_handoff_study(
                output=tmp_path / "evidence",
                adapter=_adapter(calls),
                repo_root=checkout,
            )
        )
    assert not calls and not (tmp_path / "evidence").exists()


def test_default_worker_cancellation_retains_existing_recovery_semantics(
    tmp_path, monkeypatch
):
    worker_type = runner.DurableWorker

    def default_worker(*args, **kwargs):
        kwargs.pop("terminalize_on_cancel")
        return worker_type(*args, **kwargs)

    monkeypatch.setattr(runner, "DurableWorker", default_worker)
    root = tmp_path / "evidence"
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            runner.run_context_handoff_study(
                output=root,
                adapter=_adapter([], failure="cancel"),
                repo_root=_checkout(tmp_path),
            )
        )
    ledger = json.loads((root / "ledger.json").read_bytes())
    assert [row["status"] for row in ledger["attempts"]].count("running") == 1
    assert all(
        row["result_metadata"] is None or not row["result_metadata"]
        for row in ledger["evidence"]["rows"]
    )


def test_aggregate_stop_uses_persisted_creation_deadline(tmp_path, monkeypatch):
    class Expired(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(seconds=4321)

    monkeypatch.setattr(runner, "datetime", Expired)
    calls = []
    root = tmp_path / "evidence"
    result = asyncio.run(
        runner.run_context_handoff_study(
            output=root, adapter=_adapter(calls), repo_root=_checkout(tmp_path)
        )
    )
    assert not calls and result["fatal_reason"] == "aggregate_wall_time_stop"
    assert verifier.verify(root)["integrity"] == "PASS"


def test_abrupt_process_exit_keeps_initial24_and_inflight_transport(tmp_path):
    checkout = _checkout(tmp_path)
    root = tmp_path / "evidence"
    code = (
        "import importlib.util,asyncio; from pathlib import Path; s=importlib.util.spec_from_file_location('test_runner',"
        + repr(str(Path(__file__)))
        + "); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); asyncio.run(m.runner.run_context_handoff_study(output=Path("
        + repr(str(root))
        + "),adapter=m._adapter([],failure='process_exit'),repo_root=Path("
        + repr(str(checkout))
        + ")))"
    )
    child = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert child.returncode == 23, child.stderr
    assert len(json.loads((root / "initial.json").read_bytes())["rows"]) == 24
    transport = json.loads((root / "transport.json").read_bytes())
    assert len([t for t in transport if t["method"] == "POST"]) == 1
    assert (root / "arena.db").stat().st_size > 0
    assert verifier.verify(root)["completed"] is False


def test_cli_hold_and_unsupported_pack_are_nonzero(monkeypatch):
    async def hold():
        return {"verdict": "HOLD"}

    monkeypatch.setattr(runner, "preflight", hold)
    monkeypatch.setattr(sys, "argv", ["run", "--preflight-only"])
    assert runner.main() == 1
    monkeypatch.setattr(sys, "argv", ["run", "--study-pack", "other"])
    with pytest.raises(SystemExit) as raised:
        runner.main()
    assert raised.value.code == 2


@pytest.mark.parametrize(
    "scenario_id",
    [
        "dev-helpful",
        "dev-distractor",
        "analysis-holdout-helpful",
        "analysis-holdout-distractor",
    ],
)
def test_actual_scenario_graders_accept_declared_response_and_reject_wrong_fields(
    scenario_id,
):
    pack = load_study_pack(runner.STUDY_PACK)
    expected = json.loads((runner.STUDY_PACK / "fixtures/expected.json").read_bytes())[
        scenario_id
    ]
    plan = compile_grader_plan(pack, scenario_id, TrustedGraderRegistry())
    graders = {b.metric_id: plan.resolve_builtin(b.installation) for b in plan.bindings}
    context = EvaluationContext()
    for key in ["exact-json", "json-schema", "forbidden-token-guard"]:
        assert graders[key].evaluate(json.dumps(expected), context).passed
    assert (
        not graders["exact-json"]
        .evaluate('{"answer":"wrong","evidence":"wrong"}', context)
        .passed
    )
    assert not graders["json-schema"].evaluate('{"answer":1}', context).passed
    assert (
        not graders["forbidden-token-guard"]
        .evaluate('{"answer":"deployment"}', context)
        .passed
    )


@pytest.mark.parametrize("payload", ["null", "[]", "{}", "not-json"])
def test_malformed_manifest_fails_without_traceback(tmp_path, payload):
    (tmp_path / "manifest.json").write_text(payload)
    assert verifier.verify(tmp_path)["integrity"] == "HOLD"
