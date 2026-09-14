from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import httpx
import pytest

from adapters_v1 import OllamaAdapter
from protocol_v1.canonical import sha256

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "run-local-runtime-evidence.py"
SPEC = importlib.util.spec_from_file_location("run_local_runtime_evidence", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)

ENDPOINT = "http://127.0.0.1:11434/api"
MODEL = "qwen3.5:4b"
REVISION = "a" * 40


def _clean_checkout(tmp_path: Path) -> tuple[Path, str]:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "README.md").write_text("fixture checkout\n")
    subprocess.run(["git", "init", "--quiet", str(checkout)], check=True)
    subprocess.run(["git", "-C", str(checkout), "add", "README.md"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(checkout),
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "user.name=Scaffold Arena Test",
            "commit",
            "--quiet",
            "-m",
            "fixture",
        ],
        check=True,
    )
    revision = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return checkout, revision


def _mock_adapter(*, response_content: str = '{"result":"ok"}') -> tuple[OllamaAdapter, list[str]]:
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "mock-ollama"})
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": MODEL,
                            "model": MODEL,
                            "digest": "b" * 64,
                            "details": {"context_length": 256},
                        }
                    ]
                },
            )
        assert request.url.path == "/api/chat"
        return httpx.Response(
            200,
            json={
                "model": MODEL,
                "created_at": "2026-08-20T00:00:00Z",
                "message": {"role": "assistant", "content": response_content},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 4,
                "eval_count": 1,
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False)
    adapter = OllamaAdapter(
        adapter_id="ollama-local",
        adapter_digest=sha256({"adapter": "mock-ollama"}),
        endpoint=ENDPOINT,
        client=client,
        config_schema_hash=sha256({"schema": "mock-ollama-v1"}),
    )
    return adapter, calls


def test_mock_transport_publishes_reverifiable_sanitized_bundle(tmp_path: Path) -> None:
    checkout, revision = _clean_checkout(tmp_path)
    adapter, calls = _mock_adapter()
    output = tmp_path / "local-evidence"
    result = asyncio.run(
        runner.run_local_runtime_evidence(
            runtime="ollama",
            endpoint=ENDPOINT,
            models=[MODEL],
            output=output,
            code_revision=revision,
            max_attempts=1,
            max_tokens=64,
            max_output_tokens=8,
            max_context_tokens=128,
            max_wall_time_seconds=20,
            injected_adapter=adapter,
            repo_root=checkout,
        )
    )
    assert result["summary"]["status"] == "COMPLETE_LOCAL_EXPLORATORY_CUSTODY"
    assert result["summary"]["paid_cost_usd"] == 0.0
    assert result["summary"]["energy_status"] == "unknown"
    assert result["summary"]["runtime_registry_kind"] == "ollama_local"
    assert json.loads((output / "receipt.json").read_text())["evidence_type"] == "derived_local_live"
    assert json.loads((output / "receipt-verification.json").read_text())["verified"] is True
    manifest = json.loads((output / "bundle-manifest.json").read_text())
    inventory = json.loads((output / "artifact-digest-inventory.json").read_text())
    listed_paths = {item["path"] for item in manifest["files"]}
    assert {item["path"] for item in inventory} <= listed_paths
    for item in inventory:
        path = output / item["path"]
        data = path.read_bytes()
        assert hashlib.sha256(data).hexdigest() == item["sha256"]
        assert len(data) == item["size_bytes"]
    assert not list(output.rglob("*.db"))
    assert all("reasoning" not in path.read_text(errors="ignore").lower() for path in output.rglob("*.json"))
    assert calls == ["/api/version", "/api/tags", "/api/chat", "/api/version", "/api/tags"]


def test_collision_and_invalid_caps_fail_closed_without_provider_calls(tmp_path: Path) -> None:
    output = tmp_path / "existing"
    output.mkdir()
    adapter, calls = _mock_adapter()
    with pytest.raises(runner.LocalRuntimeEvidenceError, match="existing") as collision:
        asyncio.run(
            runner.run_local_runtime_evidence(
                runtime="ollama",
                endpoint=ENDPOINT,
                models=[MODEL],
                output=output,
                code_revision=REVISION,
                injected_adapter=adapter,
            )
        )
    assert collision.value.code == "output_collision"
    assert calls == []
    invalid_output = tmp_path / "invalid"
    with pytest.raises(runner.LocalRuntimeEvidenceError, match="attempts"):
        asyncio.run(
            runner.run_local_runtime_evidence(
                runtime="ollama",
                endpoint=ENDPOINT,
                models=[MODEL, "other-model"],
                output=invalid_output,
                code_revision=REVISION,
                max_attempts=1,
                injected_adapter=adapter,
            )
        )
    assert not invalid_output.exists()


def test_lm_studio_requires_operator_attestation_and_uses_distinct_registry_kind(tmp_path: Path) -> None:
    with pytest.raises(runner.LocalRuntimeEvidenceError, match="runtime-revision"):
        asyncio.run(
            runner.run_local_runtime_evidence(
                runtime="lm-studio",
                endpoint="http://127.0.0.1:1234/api/v1",
                models=["google/gemma"],
                output=tmp_path / "missing-attestation",
                code_revision=REVISION,
            )
        )
    with pytest.raises(runner.LocalRuntimeEvidenceError, match="only with"):
        asyncio.run(
            runner.run_local_runtime_evidence(
                runtime="ollama",
                endpoint=ENDPOINT,
                models=[MODEL],
                output=tmp_path / "ambiguous-attestation",
                code_revision=REVISION,
                runtime_revision="operator-rev",
            )
        )


def test_cli_exposes_lm_studio_attestation_arguments() -> None:
    args = runner.build_parser().parse_args(
        [
            "--runtime",
            "lm-studio",
            "--endpoint",
            "http://127.0.0.1:1234/api/v1",
            "--model",
            "qwen3.8-27b",
            "--output",
            "unused",
            "--code-revision",
            REVISION,
            "--runtime-revision",
            "71bd99c",
            "--model-artifact-digest",
            "c" * 64,
        ]
    )
    assert args.runtime_revision == "71bd99c"
    assert args.model_artifact_digest == "c" * 64


def test_runner_requires_exact_clean_checkout_before_provider_calls(tmp_path: Path) -> None:
    checkout, revision = _clean_checkout(tmp_path)
    adapter, calls = _mock_adapter()
    output = tmp_path / "evidence"
    with pytest.raises(runner.LocalRuntimeEvidenceError) as mismatch:
        asyncio.run(
            runner.run_local_runtime_evidence(
                runtime="ollama",
                endpoint=ENDPOINT,
                models=[MODEL],
                output=output,
                code_revision="b" * 40,
                injected_adapter=adapter,
                repo_root=checkout,
            )
        )
    assert mismatch.value.code == "code_revision_mismatch"
    assert calls == []

    (checkout / "README.md").write_text("dirty\n")
    with pytest.raises(runner.LocalRuntimeEvidenceError) as tracked:
        asyncio.run(
            runner.run_local_runtime_evidence(
                runtime="ollama",
                endpoint=ENDPOINT,
                models=[MODEL],
                output=output,
                code_revision=revision,
                injected_adapter=adapter,
                repo_root=checkout,
            )
        )
    assert tracked.value.code == "dirty_checkout"
    assert calls == []

    (checkout / "README.md").write_text("fixture checkout\n")
    (checkout / "untracked.py").write_text("print('untracked')\n")
    with pytest.raises(runner.LocalRuntimeEvidenceError) as untracked:
        asyncio.run(
            runner.run_local_runtime_evidence(
                runtime="ollama",
                endpoint=ENDPOINT,
                models=[MODEL],
                output=output,
                code_revision=revision,
                injected_adapter=adapter,
                repo_root=checkout,
            )
        )
    assert untracked.value.code == "dirty_checkout"
    assert calls == []

    (checkout / "README.md").write_text("staged\n")
    subprocess.run(["git", "-C", str(checkout), "add", "README.md"], check=True)
    with pytest.raises(runner.LocalRuntimeEvidenceError) as indexed:
        asyncio.run(
            runner.run_local_runtime_evidence(
                runtime="ollama",
                endpoint=ENDPOINT,
                models=[MODEL],
                output=output,
                code_revision=revision,
                injected_adapter=adapter,
                repo_root=checkout,
            )
        )
    assert indexed.value.code == "dirty_checkout"
    assert calls == []


def test_runner_allows_prior_untracked_local_runtime_evidence(tmp_path: Path) -> None:
    checkout, revision = _clean_checkout(tmp_path)
    prior = checkout / "outputs" / "local_runtime_evidence" / "prior"
    prior.mkdir(parents=True)
    (prior / "summary.json").write_text("{}")
    adapter, calls = _mock_adapter()
    result = asyncio.run(
        runner.run_local_runtime_evidence(
            runtime="ollama",
            endpoint=ENDPOINT,
            models=[MODEL],
            output=tmp_path / "evidence",
            code_revision=revision,
            max_context_tokens=128,
            injected_adapter=adapter,
            repo_root=checkout,
        )
    )
    assert result["summary"]["code_revision"] == revision
    assert "/api/chat" in calls


def test_malicious_synthetic_response_is_withheld_before_bundle_publish(tmp_path: Path) -> None:
    checkout, revision = _clean_checkout(tmp_path)
    adapter, calls = _mock_adapter(response_content='{"result":"ok","session":"private-value"}')
    output = tmp_path / "malicious-evidence"
    with pytest.raises(runner.LocalRuntimeEvidenceError) as rejected:
        asyncio.run(
            runner.run_local_runtime_evidence(
                runtime="ollama",
                endpoint=ENDPOINT,
                models=[MODEL],
                output=output,
                code_revision=revision,
                max_context_tokens=128,
                injected_adapter=adapter,
                repo_root=checkout,
            )
        )
    assert rejected.value.code == "synthetic_response_hold"
    assert not output.exists()
    assert "/api/chat" in calls


def test_provider_summary_rejects_alternate_message_content() -> None:
    summary = json.dumps(
        {
            "response": {
                "message": {"role": "assistant", "content": '{"result":"ok"}'},
                "alternate_message": {"role": "assistant", "content": "private-value"},
            },
            "raw_response_sha256": "a" * 64,
        }
    ).encode()
    with pytest.raises(runner.LocalRuntimeEvidenceError) as rejected:
        runner._validate_provider_response_summary(summary, artifact_digest="b" * 64)
    assert rejected.value.code == "provider_summary_hold"
