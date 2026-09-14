"""Narrow, default-deny Agent Client Protocol v1 stdio bridge.

This is deliberately not a generic process runner.  A caller supplies a
captured, digest-bound registry identity and an operator-approved identifier;
StudyPacks, prompts, and API requests never select a command or environment.
"""

from __future__ import annotations

import json
import os
import resource
import select
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from protocol_v1.canonical import sha256_bytes

from .acp_schema import AcpSchemaHold, validate_acp_fragment
from .canonical import digest_for
from .models import AcpAgentIdentity, AcpBridgePolicy, AcpLaunchAttestation


class AcpBridgeHold(ValueError):
    """A typed, public-safe refusal by the bounded bridge."""

    def __init__(self, code: str, prerequisite: str) -> None:
        super().__init__(prerequisite)
        self.code = code
        self.prerequisite = prerequisite


_MAX_JSON_DEPTH = 32
_FORBIDDEN_CALLBACKS = frozenset(
    {
        "fs/read_text_file",
        "fs/write_text_file",
        "terminal/create",
        "terminal/output",
        "terminal/release",
        "terminal/wait_for_exit",
        "terminal/kill",
        "session/request_permission",
        "elicitation/create",
        "authenticate",
        "auth/login",
    }
)
_ARENA_CLIENT_METHODS = frozenset({"initialize", "session/new", "session/prompt", "session/cancel", "session/close"})


def _resource_limiter(policy: AcpBridgePolicy) -> Callable[[], None]:
    def apply() -> None:
        limits = (
            (resource.RLIMIT_CPU, (max(1, policy.max_wall_time_seconds), max(1, policy.max_wall_time_seconds))),
            (resource.RLIMIT_AS, (policy.max_memory_bytes, policy.max_memory_bytes)),
            (resource.RLIMIT_FSIZE, (policy.max_artifact_bytes, policy.max_artifact_bytes)),
            (resource.RLIMIT_NOFILE, (64, 64)),
        )
        if hasattr(resource, "RLIMIT_NPROC"):
            limits += ((resource.RLIMIT_NPROC, (policy.max_processes, policy.max_processes)),)
        for limit, value in limits:
            try:
                resource.setrlimit(limit, value)
            except (OSError, ValueError):
                continue
    return apply


def _validate_json(value: Any, *, depth: int = 0) -> None:
    if depth > _MAX_JSON_DEPTH:
        raise AcpBridgeHold("acp_message_depth_exceeded", "The ACP message exceeds the configured JSON nesting limit.")
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise AcpBridgeHold("acp_message_invalid", "ACP JSON object keys must be strings.")
        for item in value.values():
            _validate_json(item, depth=depth + 1)
    elif isinstance(value, list):
        for item in value:
            _validate_json(item, depth=depth + 1)
    elif value is not None and not isinstance(value, (str, bool, int, float)):
        raise AcpBridgeHold("acp_message_invalid", "ACP messages must be JSON values.")


def validate_jsonrpc(message: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one JSON-RPC 2.0 envelope without guessing ACP methods."""
    _validate_json(message)
    if message.get("jsonrpc") != "2.0":
        raise AcpBridgeHold("acp_jsonrpc_invalid", "ACP requires JSON-RPC 2.0 envelopes.")
    if "method" in message:
        method = message["method"]
        if not isinstance(method, str) or not method:
            raise AcpBridgeHold("acp_jsonrpc_invalid", "ACP method names must be nonempty strings.")
        if method in _FORBIDDEN_CALLBACKS:
            return {"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": -32001, "message": "operation denied by Arena ACP policy"}}
        if method not in _ARENA_CLIENT_METHODS:
            raise AcpBridgeHold("acp_method_unavailable", "The method is outside the pinned non-executing Arena ACP profile.")
        return dict(message)
    if "id" not in message or ("result" not in message and "error" not in message):
        raise AcpBridgeHold("acp_jsonrpc_invalid", "ACP responses require an id and result or error.")
    return dict(message)


@dataclass(frozen=True)
class AcpBridgeEvent:
    sequence: int
    direction: str
    method: str | None
    message_digest: str
    denied: bool = False


@dataclass(frozen=True)
class AcpBridgeResult:
    transcript: bytes
    transcript_digest: str
    events: tuple[AcpBridgeEvent, ...]
    cancellation: str
    denied_operations: tuple[str, ...]
    initialize_result_digest: str | None
    authority_ceiling: str = "local_acp_process_observation"
    integrity_not_truth: bool = True


class AcpStdioBridge:
    """One ACP v1 process with fixed argv, isolated roots, and hard bounds."""

    def __init__(
        self,
        identity: AcpAgentIdentity,
        policy: AcpBridgePolicy,
        *,
        operator_approved_agent_ids: frozenset[str],
        operator_attestation: AcpLaunchAttestation | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        raise AcpBridgeHold("acp_execution_unavailable", "ACP process execution is unavailable in M1. Only typed non-executing lifecycle HOLD routes are shipped until a service-owned registry resolver and verifiable operator sandbox are deployed.")
        if identity.agent_id not in operator_approved_agent_ids:
            raise AcpBridgeHold("acp_identity_not_operator_approved", "The captured ACP identity is not operator-approved.")
        if operator_attestation is None:
            raise AcpBridgeHold("acp_sandbox_attestation_required", "ACP execution requires an operator-owned, digest-bound sandbox-launcher attestation.")
        if (
            operator_attestation.agent_id != identity.agent_id
            or operator_attestation.registry_snapshot_digest != identity.source_snapshot.content_digest
            or operator_attestation.distribution_digest != identity.distribution_digest
            or operator_attestation.argv_digest != digest_for(identity.executable_argv, domain="scaffold-arena.acp.argv")
            or operator_attestation.enforced_limits_digest != digest_for(policy, domain="scaffold-arena.acp.limits")
        ):
            raise AcpBridgeHold("acp_attestation_mismatch", "The operator attestation does not bind this registry identity, full argv, distribution, and limits.")
        if operator_attestation.sandbox_launcher_argv[-len(identity.executable_argv):] != identity.executable_argv:
            raise AcpBridgeHold("acp_attestation_mismatch", "The operator launcher attestation must bind the complete fixed agent argv as its suffix.")
        if not identity.distribution_digest:
            raise AcpBridgeHold("acp_distribution_digest_required", "A pinned distribution digest is required before ACP spawning.")
        if identity.distribution != "binary":
            raise AcpBridgeHold("acp_launcher_unsupported", "Only a directly pinned binary identity is executable in ACP bridge v1.")
        if not identity.executable_argv or any(not arg or "\x00" in arg for arg in identity.executable_argv):
            raise AcpBridgeHold("acp_executable_identity_invalid", "The captured ACP identity must contain a fixed nonempty argv.")
        executable = Path(identity.executable_argv[0])
        if not executable.is_absolute() or executable.is_symlink() or not executable.is_file():
            raise AcpBridgeHold("acp_executable_identity_invalid", "The executable identity must be an absolute, regular, non-symlink file.")
        if sha256_bytes(executable.read_bytes()) != identity.distribution_digest.removeprefix("sha256:"):
            raise AcpBridgeHold("acp_executable_digest_mismatch", "The fixed executable does not match the captured distribution digest.")
        launcher = Path(operator_attestation.sandbox_launcher_argv[0])
        if not launcher.is_absolute() or launcher.is_symlink() or not launcher.is_file() or sha256_bytes(launcher.read_bytes()) != operator_attestation.sandbox_launcher_digest.removeprefix("sha256:"):
            raise AcpBridgeHold("acp_sandbox_launcher_invalid", "The operator sandbox launcher must be an absolute, regular, digest-bound executable.")
        if policy.protocol_version != "1" or policy.transport != "stdio":
            raise AcpBridgeHold("acp_policy_unsupported", "Only ACP v1 over isolated stdio is implemented.")
        if policy.filesystem != "deny" or policy.terminal != "deny" or policy.permission_requests != "deny" or policy.elicitation != "deny":
            raise AcpBridgeHold("acp_policy_not_default_deny", "This bridge currently permits only default-deny filesystem, terminal, permission, and elicitation policies.")
        self.identity = identity
        self.policy = policy
        self.operator_attestation = operator_attestation
        self.clock = clock

    def run(self, prompt: str, *, cancel_after_seconds: float | None = None) -> AcpBridgeResult:
        if not isinstance(prompt, str) or len(prompt.encode("utf-8")) > self.policy.max_message_bytes:
            raise AcpBridgeHold("acp_prompt_limit", "The prompt must be a bounded UTF-8 ACP payload.")
        if cancel_after_seconds is not None and cancel_after_seconds < 0:
            raise AcpBridgeHold("acp_cancel_invalid", "Cancellation timing must be nonnegative.")
        with tempfile.TemporaryDirectory(prefix="arena-acp-") as root:
            isolated = Path(root)
            workspace = isolated / "workspace"
            for path in (workspace, isolated / "home", isolated / "xdg-config", isolated / "xdg-data", isolated / "xdg-cache", isolated / "xdg-runtime", isolated / "tmp"):
                path.mkdir(mode=0o700)
            environment = {
                "HOME": str(isolated / "home"), "XDG_CONFIG_HOME": str(isolated / "xdg-config"),
                "XDG_DATA_HOME": str(isolated / "xdg-data"), "XDG_CACHE_HOME": str(isolated / "xdg-cache"),
                "XDG_RUNTIME_DIR": str(isolated / "xdg-runtime"), "TMPDIR": str(isolated / "tmp"),
                "PATH": os.defpath, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
            }
            return self._communicate(workspace, environment, prompt, cancel_after_seconds)

    def _communicate(self, workspace: Path, environment: Mapping[str, str], prompt: str, cancel_after_seconds: float | None) -> AcpBridgeResult:
        try:
            process = subprocess.Popen(
                list(self.operator_attestation.sandbox_launcher_argv), cwd=workspace, env=dict(environment), shell=False,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
                preexec_fn=_resource_limiter(self.policy),
            )
        except OSError as exc:
            raise AcpBridgeHold("acp_spawn_failed", "The fixed ACP identity could not be started under its isolated policy.") from exc
        started = self.clock()
        deadline = started + min(self.policy.max_wall_time_seconds, cancel_after_seconds if cancel_after_seconds is not None else self.policy.max_wall_time_seconds)
        cancellation = "not_requested"
        transcript = bytearray()
        events: list[AcpBridgeEvent] = []
        denied: list[str] = []
        initialize_digest: str | None = None
        session_id: str | None = None
        stderr = bytearray()

        def drain_stderr() -> None:
            if process.stderr is None:
                return
            while chunk := process.stderr.read(64 * 1024):
                if len(stderr) <= self.policy.max_stderr_bytes:
                    stderr.extend(chunk[: self.policy.max_stderr_bytes + 1 - len(stderr)])

        stderr_thread = threading.Thread(target=drain_stderr, name="arena-acp-stderr", daemon=True)
        stderr_thread.start()
        try:
            initialize = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": 1, "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False}}}
            response, callback_events, callback_denials = self._request(process, initialize, deadline, len(events))
            transcript.extend(response[0]); events.extend(response[1]); events.extend(callback_events); denied.extend(callback_denials)
            self._validate_result("InitializeResponse", response[2])
            if response[2].get("protocolVersion") != 1:
                raise AcpBridgeHold("acp_protocol_negotiation_failed", "The agent did not negotiate the pinned ACP v1 protocol version.")
            initialize_digest = sha256_bytes(json.dumps(response[2], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())
            new_session = {"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": {"cwd": str(workspace.resolve()), "mcpServers": []}}
            response, callback_events, callback_denials = self._request(process, new_session, deadline, len(events))
            transcript.extend(response[0]); events.extend(response[1]); events.extend(callback_events); denied.extend(callback_denials)
            self._validate_result("NewSessionResponse", response[2])
            session_id = response[2]["sessionId"]
            prompt_request = {"jsonrpc": "2.0", "id": 3, "method": "session/prompt", "params": {"sessionId": session_id, "prompt": [{"type": "text", "text": prompt}]}}
            for request in (prompt_request,):
                response, callback_events, callback_denials = self._request(process, request, deadline, len(events))
                transcript.extend(response[0])
                events.extend(response[1]); events.extend(callback_events); denied.extend(callback_denials)
                self._validate_result("PromptResponse", response[2])
            process.stdin.close()
            remaining = max(0.0, deadline - self.clock())
            process.wait(timeout=remaining)
        except (subprocess.TimeoutExpired, TimeoutError):
            cancellation = self._cancel_process(process, session_id)
        finally:
            if process.poll() is None:
                cancellation = self._cancel_process(process, session_id)
            stderr_thread.join(timeout=1.0)
        stdout = bytes(transcript)
        if len(stdout) > self.policy.max_stdout_bytes or len(stderr) > self.policy.max_stderr_bytes:
            raise AcpBridgeHold("acp_output_limit", "The ACP process exceeded its stdout or stderr byte limit.")
        if process.returncode not in {0, None} and cancellation == "not_requested":
            raise AcpBridgeHold("acp_process_failed", "The isolated ACP process exited without a successful bridge receipt.")
        return AcpBridgeResult(bytes(transcript), sha256_bytes(bytes(transcript)), tuple(events), cancellation, tuple(sorted(set(denied))), initialize_digest)

    def _request(self, process: subprocess.Popen[bytes], request: Mapping[str, Any], deadline: float, sequence: int) -> tuple[tuple[bytes, list[AcpBridgeEvent], Any], list[AcpBridgeEvent], list[str]]:
        if process.stdin is None or process.stdout is None:
            raise AcpBridgeHold("acp_pipe_unavailable", "The isolated ACP process has no stdio transport.")
        process.stdin.write(json.dumps(request, separators=(",", ":"), ensure_ascii=False).encode() + b"\n")
        process.stdin.flush()
        transcript = bytearray(); events: list[AcpBridgeEvent] = []; denied_events: list[AcpBridgeEvent] = []; denied: list[str] = []
        while True:
            remaining = min(float(self.policy.max_idle_seconds), deadline - self.clock())
            if remaining <= 0 or not select.select([process.stdout], [], [], remaining)[0]:
                raise TimeoutError
            line = process.stdout.readline(self.policy.max_message_bytes + 1)
            if not line or len(line) > self.policy.max_message_bytes:
                raise AcpBridgeHold("acp_message_limit", "The ACP process emitted an oversized or incomplete message.")
            if sequence + len(events) + len(denied_events) >= self.policy.max_event_count:
                raise AcpBridgeHold("acp_event_limit", "The ACP process emitted too many events.")
            try:
                raw = json.loads(line)
                if not isinstance(raw, dict): raise TypeError
                method = raw.get("method") if isinstance(raw.get("method"), str) else None
                response = validate_jsonrpc(raw)
            except (json.JSONDecodeError, TypeError, AcpBridgeHold) as exc:
                if isinstance(exc, AcpBridgeHold): raise
                raise AcpBridgeHold("acp_jsonrpc_invalid", "The ACP process emitted an invalid JSON-RPC message.") from exc
            transcript.extend(line)
            denied_callback = method in _FORBIDDEN_CALLBACKS
            events.append(AcpBridgeEvent(sequence + len(events), "agent_to_client", method, sha256_bytes(line), denied_callback))
            if denied_callback:
                self._validate_agent_callback(raw)
                denied.append(method or "unknown")
                process.stdin.write(json.dumps(response, separators=(",", ":")).encode() + b"\n"); process.stdin.flush()
                continue
            if response.get("id") == request["id"]:
                return (bytes(transcript), events, response.get("result")), denied_events, denied

    @staticmethod
    def _validate_result(fragment: str, value: Any) -> None:
        if not isinstance(value, dict):
            raise AcpBridgeHold("acp_schema_validation_failed", f"ACP {fragment} result must be an object.")
        try:
            validate_acp_fragment(fragment, value)
        except AcpSchemaHold as exc:
            raise AcpBridgeHold("acp_schema_validation_failed", str(exc)) from exc

    @staticmethod
    def _validate_agent_callback(message: Mapping[str, Any]) -> None:
        envelope = {key: value for key, value in message.items() if key != "jsonrpc"}
        try:
            validate_acp_fragment("AgentRequest", envelope)
        except AcpSchemaHold as exc:
            raise AcpBridgeHold("acp_schema_validation_failed", str(exc)) from exc

    @staticmethod
    def _cancel_process(process: subprocess.Popen[bytes], session_id: str | None) -> str:
        if process.poll() is not None:
            return "acknowledged"
        if session_id is not None and process.stdin is not None:
            try:
                process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "session/cancel", "params": {"sessionId": session_id}}, separators=(",", ":")).encode() + b"\n")
                process.stdin.flush()
                process.wait(timeout=0.25)
                return "acknowledged"
            except (OSError, subprocess.TimeoutExpired):
                pass
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=1.0)
            return "acknowledged"
        except (ProcessLookupError, PermissionError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, signal.SIGKILL)
                return "forced"
            except (ProcessLookupError, PermissionError):
                return "uncertain"
