from __future__ import annotations

import sys
import hashlib
from pathlib import Path
from datetime import UTC, datetime

import pytest

from genome_v1.acp import AcpBridgeHold, AcpStdioBridge, validate_jsonrpc
from genome_v1.canonical import digest_for
from genome_v1.models import AcpAgentIdentity, AcpBridgePolicy, AcpLaunchAttestation, AcpRegistrySnapshot


_DIGEST = "sha256:" + "a" * 64


def _identity(script: str) -> AcpAgentIdentity:
    snapshot = AcpRegistrySnapshot(
        registry_uri="https://cdn.agentclientprotocol.com/registry/v1/latest/registry.json",
        registry_schema_version="1.0.0", content_digest=_DIGEST, captured_at=datetime.now(UTC), agent_ids=("fixture-agent",),
    )
    executable = str(Path(sys.executable).resolve())
    executable_digest = "sha256:" + hashlib.sha256(open(executable, "rb").read()).hexdigest()
    return AcpAgentIdentity(agent_id="fixture-agent", display_name="Fixture", version="1.0.0", distribution="binary", distribution_ref="fixture-1.0.0", distribution_digest=executable_digest, executable_argv=(executable, script), source_snapshot=snapshot)


def _policy() -> AcpBridgePolicy:
    return AcpBridgePolicy(max_wall_time_seconds=2, max_idle_seconds=1, max_message_bytes=4096, max_event_count=10, max_stdout_bytes=16_384, max_stderr_bytes=16_384, max_artifact_bytes=16_384, home_root_digest=_DIGEST, xdg_roots_digest=_DIGEST, workspace_root_digest=_DIGEST)


def _attestation(identity: AcpAgentIdentity, policy: AcpBridgePolicy) -> AcpLaunchAttestation:
    return AcpLaunchAttestation(attestation_id="attest-fixture", registry_snapshot_digest=identity.source_snapshot.content_digest, agent_id=identity.agent_id, distribution_digest=identity.distribution_digest, argv_digest=digest_for(identity.executable_argv, domain="scaffold-arena.acp.argv"), sandbox_launcher_digest=identity.distribution_digest, sandbox_launcher_argv=identity.executable_argv, enforced_limits_digest=digest_for(policy, domain="scaffold-arena.acp.limits"))


def test_callback_envelope_is_default_denied() -> None:
    denied = validate_jsonrpc({"jsonrpc": "2.0", "id": 3, "method": "terminal/create", "params": {}})
    assert denied["error"]["code"] == -32001
    with pytest.raises(AcpBridgeHold, match="outside the pinned"):
        validate_jsonrpc({"jsonrpc": "2.0", "id": 3, "method": "not-an-acp-method", "params": {}})


def test_bridge_execution_is_unavailable_without_service_owned_containment(tmp_path) -> None:
    script = tmp_path / "agent.py"; script.write_text("", encoding="utf-8")
    with pytest.raises(AcpBridgeHold, match="execution is unavailable"):
        AcpStdioBridge(_identity(str(script)), _policy(), operator_approved_agent_ids=frozenset(), operator_attestation=_attestation(_identity(str(script)), _policy()))


def test_bridge_does_not_start_fixture_processes(tmp_path) -> None:
    script = tmp_path / "agent.py"
    script.write_text(
        "import json,sys\n"
        "for line in sys.stdin:\n"
        " msg=json.loads(line)\n"
        " method=msg.get('method')\n"
        " if method=='initialize': print(json.dumps({'jsonrpc':'2.0','id':1,'result':{'protocolVersion':1}}),flush=True)\n"
        " elif method=='session/new': print(json.dumps({'jsonrpc':'2.0','id':2,'result':{'sessionId':'fixture'}}),flush=True)\n"
        " elif method=='session/prompt': print(json.dumps({'jsonrpc':'2.0','id':42,'method':'terminal/create','params':{'sessionId':'fixture','command':'false'}}),flush=True)\n"
        " elif msg.get('id')==42: print(json.dumps({'jsonrpc':'2.0','id':3,'result':{'stopReason':'end_turn'}}),flush=True)\n",
        encoding="utf-8",
    )
    identity, policy = _identity(str(script)), _policy()
    with pytest.raises(AcpBridgeHold, match="execution is unavailable"):
        AcpStdioBridge(identity, policy, operator_approved_agent_ids=frozenset({"fixture-agent"}), operator_attestation=_attestation(identity, policy)).run("hello")


def test_bridge_rejects_non_default_deny_policy(tmp_path) -> None:
    script = tmp_path / "agent.py"; script.write_text("", encoding="utf-8")
    with pytest.raises(AcpBridgeHold, match="execution is unavailable"):
        identity, policy = _identity(str(script)), _policy().model_copy(update={"filesystem": "workspace_only"})
        AcpStdioBridge(identity, policy, operator_approved_agent_ids=frozenset({"fixture-agent"}), operator_attestation=_attestation(identity, policy))


def test_bridge_rejects_executable_byte_substitution(tmp_path) -> None:
    script = tmp_path / "agent.py"; script.write_text("", encoding="utf-8")
    identity = _identity(str(script)).model_copy(update={"distribution_digest": _DIGEST})
    with pytest.raises(AcpBridgeHold, match="execution is unavailable"):
        AcpStdioBridge(identity, _policy(), operator_approved_agent_ids=frozenset({"fixture-agent"}), operator_attestation=_attestation(identity, _policy()))


def test_bridge_cannot_start_a_live_process_at_any_deadline(tmp_path) -> None:
    script = tmp_path / "agent.py"; script.write_text("import time\ntime.sleep(10)\n", encoding="utf-8")
    identity, policy = _identity(str(script)), _policy()
    with pytest.raises(AcpBridgeHold, match="execution is unavailable"):
        AcpStdioBridge(identity, policy, operator_approved_agent_ids=frozenset({"fixture-agent"}), operator_attestation=_attestation(identity, policy)).run("hello", cancel_after_seconds=0.05)
