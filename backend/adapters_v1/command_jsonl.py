"""Bounded subprocess adapter: no shell, pinned executable, live JSONL."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from protocol_v1.canonical import canonical_json, sha256, sha256_bytes
from protocol_v1.models import HarnessSpec, TraceEvent
from pydantic import ValidationError

from .base import HarnessAdapter
from .invocation import InvocationContext
from .models import (
    AdapterCapabilities,
    AdapterHealth,
    ArtifactRef,
    AttemptInput,
    PreparedAttempt,
    ResultBundle,
    validate_result_for_attempt,
)
from .preflight import preflight
from .transport import (
    DEFAULT_TRANSPORT_LIMITS,
    AdapterTransportLimits,
    EventChannel,
    JsonlResultParser,
    TransportLimitExceeded,
    invocation_environment,
    parse_jsonl_response,
    read_bounded_stream,
    validate_request_size,
    validate_result_transport_limits,
)


@dataclass(frozen=True)
class _CommandAttempt:
    input_bytes: bytes
    argv: tuple[str, ...]
    environment: Mapping[str, str]
    timeout_seconds: int
    invocation: InvocationContext | None


class CommandJsonlAdapter(HarnessAdapter):
    """Run one trusted executable with bounded stdin/stdout/stderr and no shell.

    The executable receives the exact canonical ``AttemptInput`` on stdin.
    Generation fencing is delivered separately through reserved environment
    variables so operational lease context never mutates the scientific input.
    """

    def __init__(
        self,
        *,
        adapter_id: str,
        adapter_digest: str,
        executable: str | Path,
        executable_digest: str,
        environment_allowlist: frozenset[str] = frozenset(),
        limits: AdapterTransportLimits | None = None,
    ) -> None:
        self._executable = Path(executable).resolve()
        self._executable_digest = executable_digest
        self._environment_allowlist = environment_allowlist
        self._limits = limits or DEFAULT_TRANSPORT_LIMITS
        self._capabilities = AdapterCapabilities(
            adapter_id=adapter_id,
            adapter_digest=adapter_digest,
            adapter_kind="cli",
            supported_isolation=("none", "process"),
            claim_eligibility="protocol_only",
            supports_cancellation=True,
            supports_artifacts=True,
        )
        self._attempts: dict[str, _CommandAttempt] = {}
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._events: dict[str, tuple[TraceEvent, ...]] = {}
        self._results: dict[str, ResultBundle] = {}
        self._event_queues: dict[str, EventChannel] = {}
        self._execution_locks: dict[str, asyncio.Lock] = {}
        self._cancelled: set[str] = set()
        self._cleaned: set[str] = set()

    async def describe_capabilities(self) -> AdapterCapabilities:
        return self._capabilities

    async def healthcheck(self) -> AdapterHealth:
        healthy = (
            self._executable.is_file()
            and sha256_bytes(self._executable.read_bytes()) == self._executable_digest
        )
        return AdapterHealth(
            healthy=healthy,
            checked_at=datetime.now(UTC),
            detail=(
                "pinned executable verified"
                if healthy
                else "pinned executable unavailable or digest mismatch"
            ),
        )

    async def prepare_attempt(
        self,
        harness: HarnessSpec,
        input: AttemptInput,
    ) -> PreparedAttempt:
        return await self._prepare(harness, input, invocation=None)

    async def prepare_invocation(
        self,
        harness: HarnessSpec,
        input: AttemptInput,
        context: InvocationContext,
    ) -> PreparedAttempt:
        if context.attempt_id != input.attempt.attempt_id:
            raise ValueError("invocation context does not bind the prepared attempt")
        return await self._prepare(harness, input, invocation=context)

    async def _prepare(
        self,
        harness: HarnessSpec,
        input: AttemptInput,
        *,
        invocation: InvocationContext | None,
    ) -> PreparedAttempt:
        bound = AttemptInput.model_validate_json(
            canonical_json(input.model_dump(mode="json"))
        )
        preflight(self._capabilities, harness, bound)
        attempt = bound.attempt
        if harness.claim_eligibility not in ("fixture_only", "protocol_only"):
            raise ValueError(
                "unsandboxed command execution is claim-ineligible beyond protocol evidence"
            )
        if (
            not self._executable.is_file()
            or sha256_bytes(self._executable.read_bytes()) != self._executable_digest
        ):
            raise ValueError("trusted executable digest mismatch")
        if attempt.attempt_id in self._attempts and attempt.attempt_id not in self._cleaned:
            raise ValueError("attempt is already prepared by this adapter")
        argv, environment = self._command_config(harness.configuration)
        input_bytes = canonical_json(bound.model_dump(mode="json"))
        validate_request_size(input_bytes, self._limits, label="command adapter")
        self._attempts[attempt.attempt_id] = _CommandAttempt(
            input_bytes=input_bytes,
            argv=tuple(argv),
            environment=dict(environment),
            timeout_seconds=harness.timeout_seconds,
            invocation=invocation,
        )
        self._event_queues[attempt.attempt_id] = EventChannel(
            max_pending_events=self._limits.max_pending_events
        )
        self._execution_locks[attempt.attempt_id] = asyncio.Lock()
        self._events.pop(attempt.attempt_id, None)
        self._results.pop(attempt.attempt_id, None)
        self._cancelled.discard(attempt.attempt_id)
        self._cleaned.discard(attempt.attempt_id)
        return PreparedAttempt(
            attempt_id=attempt.attempt_id,
            adapter_id=self._capabilities.adapter_id,
            prepared_at=datetime.now(UTC),
            timeout_seconds=harness.timeout_seconds,
            opaque_handle=attempt.attempt_id,
            input_digest=sha256(bound.model_dump(mode="json")),
        )

    def _command_config(
        self,
        configuration: Mapping[str, Any],
    ) -> tuple[list[str], dict[str, str]]:
        if set(configuration) - {"argv", "environment"}:
            raise ValueError(
                "command adapter configuration only permits argv and environment"
            )
        argv = configuration.get("argv")
        if (
            not isinstance(argv, (list, tuple))
            or not argv
            or any(not isinstance(item, str) or not item for item in argv)
        ):
            raise ValueError(
                "argv must be a non-empty list of strings; shell commands are forbidden"
            )
        if Path(argv[0]).resolve() != self._executable:
            raise ValueError("argv must start with the pinned executable")
        environment = configuration.get("environment", {})
        if (
            not isinstance(environment, dict)
            or any(
                not isinstance(key, str) or not isinstance(value, str)
                for key, value in environment.items()
            )
        ):
            raise ValueError("environment must be a string mapping")
        if set(environment) - self._environment_allowlist:
            raise ValueError("environment includes keys outside the adapter allowlist")
        reserved = {
            key
            for key in environment
            if key.startswith("SCAFFOLD_ARENA_") or key == "Idempotency-Key"
        }
        if reserved:
            raise ValueError("environment cannot override reserved invocation variables")
        return list(argv), dict(environment)

    async def execute_attempt(self, prepared: PreparedAttempt) -> ResultBundle:
        if prepared.attempt_id in self._results:
            return self._results[prepared.attempt_id]
        stored, bound = self._attempt(prepared)
        async with self._execution_locks[prepared.attempt_id]:
            if prepared.attempt_id in self._results:
                return self._results[prepared.attempt_id]
            channel = self._event_queues[prepared.attempt_id]
            if prepared.attempt_id in self._cancelled:
                result = ResultBundle(
                    attempt_id=prepared.attempt_id,
                    terminal_outcome="cancelled",
                    completed_at=datetime.now(UTC),
                    detail="cancelled before command dispatch",
                )
                self._results[prepared.attempt_id] = result
                await channel.close()
                return result

            environment = {
                "PATH": os.environ.get("PATH", ""),
                **stored.environment,
                **invocation_environment(stored.invocation),
            }
            process = await asyncio.create_subprocess_exec(
                *stored.argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=environment,
                start_new_session=True,
                limit=self._limits.max_jsonl_line_bytes + 1,
            )
            self._processes[prepared.attempt_id] = process
            assert process.stdin is not None
            assert process.stdout is not None
            assert process.stderr is not None
            parser = JsonlResultParser(
                attempt=bound.attempt,
                limits=self._limits,
                channel=channel,
                source="command",
            )
            stdout_task = asyncio.create_task(
                self._consume_stdout(process.stdout, parser)
            )
            stderr_task = asyncio.create_task(
                read_bounded_stream(
                    process.stderr,
                    maximum=self._limits.max_stderr_bytes,
                    label="command stderr",
                )
            )
            wait_task = asyncio.create_task(process.wait())
            stdin_task = asyncio.create_task(
                self._write_stdin(process.stdin, stored.input_bytes)
            )
            try:
                stdout_result, stderr, returncode, _ = await asyncio.wait_for(
                    asyncio.gather(stdout_task, stderr_task, wait_task, stdin_task),
                    timeout=stored.timeout_seconds,
                )
                if prepared.attempt_id in self._cancelled:
                    result = ResultBundle(
                        attempt_id=prepared.attempt_id,
                        terminal_outcome="cancelled",
                        completed_at=datetime.now(UTC),
                        detail="command cancellation acknowledged",
                    )
                elif returncode != 0:
                    result = ResultBundle(
                        attempt_id=prepared.attempt_id,
                        terminal_outcome="failed",
                        completed_at=datetime.now(UTC),
                        detail=stderr.decode("utf-8", "replace")[:1000]
                        or f"command exited with status {returncode}",
                        failure_classification="permanent_adapter",
                    )
                else:
                    result = stdout_result
                validate_result_transport_limits(result, self._limits)
                self._events[prepared.attempt_id] = channel.events
                self._results[prepared.attempt_id] = validate_result_for_attempt(
                    result,
                    bound.attempt,
                )
                return self._results[prepared.attempt_id]
            except TimeoutError:
                await self._terminate_process(process)
                result = ResultBundle(
                    attempt_id=prepared.attempt_id,
                    terminal_outcome="timed_out",
                    completed_at=datetime.now(UTC),
                    detail="command timeout",
                    failure_classification="transient_adapter",
                )
                self._results[prepared.attempt_id] = result
                return result
            except asyncio.CancelledError:
                await self._terminate_process(process)
                current = asyncio.current_task()
                if current is not None and hasattr(current, "uncancel"):
                    current.uncancel()
                result = ResultBundle(
                    attempt_id=prepared.attempt_id,
                    terminal_outcome="cancelled",
                    completed_at=datetime.now(UTC),
                    detail="command execution cancelled",
                )
                self._results[prepared.attempt_id] = result
                return result
            except (TransportLimitExceeded, TypeError, ValueError):
                await self._terminate_process(process)
                raise
            finally:
                for task in (stdin_task, stdout_task, stderr_task, wait_task):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(
                    stdin_task,
                    stdout_task,
                    stderr_task,
                    wait_task,
                    return_exceptions=True,
                )
                self._processes.pop(prepared.attempt_id, None)
                await channel.close()

    @staticmethod
    async def _write_stdin(writer: asyncio.StreamWriter, content: bytes) -> None:
        try:
            writer.write(content)
            await writer.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            writer.close()
            with contextlib.suppress(BrokenPipeError, ConnectionResetError, ValueError):
                await writer.wait_closed()

    async def _consume_stdout(
        self,
        reader: asyncio.StreamReader,
        parser: JsonlResultParser,
    ) -> ResultBundle:
        while True:
            try:
                line = await reader.readline()
            except ValueError as exc:
                raise TransportLimitExceeded(
                    "command JSONL line exceeded the configured stream-reader bound"
                ) from exc
            if not line:
                return parser.finish()
            await parser.consume_line(line)

    def _parse_jsonl(
        self,
        output: bytes,
        attempt: Any,
    ) -> tuple[tuple[TraceEvent, ...], ResultBundle]:
        """Compatibility helper backed by the same bounded JSONL contract."""

        try:
            return parse_jsonl_response(
                output,
                attempt=attempt,
                limits=self._limits,
                source="command",
            )
        except ValidationError as exc:
            raise ValueError("command JSONL record violates adapter contract") from exc

    async def stream_events(
        self,
        prepared: PreparedAttempt,
    ) -> AsyncIterator[TraceEvent]:
        self._attempt(prepared)
        async for event in self._event_queues[prepared.attempt_id].iterate():
            yield event

    async def collect_artifacts(
        self,
        prepared: PreparedAttempt,
    ) -> tuple[ArtifactRef, ...]:
        self._attempt(prepared)
        result = self._results.get(prepared.attempt_id)
        return () if result is None else result.artifacts

    async def cancel_attempt(self, prepared: PreparedAttempt) -> None:
        if prepared.attempt_id in self._cleaned:
            return
        self._attempt(prepared)
        self._cancelled.add(prepared.attempt_id)
        process = self._processes.get(prepared.attempt_id)
        if process is not None:
            await self._terminate_process(process)
        channel = self._event_queues.get(prepared.attempt_id)
        if channel is not None:
            await channel.close()

    async def cleanup_attempt(self, prepared: PreparedAttempt) -> None:
        if prepared.attempt_id in self._cleaned:
            return
        self._attempt(prepared)
        await self.cancel_attempt(prepared)
        attempt_id = prepared.attempt_id
        self._attempts.pop(attempt_id, None)
        self._processes.pop(attempt_id, None)
        self._events.pop(attempt_id, None)
        self._results.pop(attempt_id, None)
        self._event_queues.pop(attempt_id, None)
        self._execution_locks.pop(attempt_id, None)
        self._cancelled.discard(attempt_id)
        self._cleaned.add(attempt_id)

    async def _terminate_process(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except PermissionError:
            try:
                process.terminate()
            except ProcessLookupError:
                return
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), timeout=2)
        except TimeoutError:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except PermissionError:
                try:
                    process.kill()
                except ProcessLookupError:
                    return
            except ProcessLookupError:
                return
            await process.wait()

    def _attempt(
        self,
        prepared: PreparedAttempt,
    ) -> tuple[_CommandAttempt, AttemptInput]:
        stored = self._attempts.get(prepared.attempt_id)
        if prepared.adapter_id != self._capabilities.adapter_id or stored is None:
            raise ValueError("prepared attempt is not owned by this adapter")
        bound = AttemptInput.model_validate_json(stored.input_bytes)
        if prepared.input_digest != sha256(bound.model_dump(mode="json")):
            raise ValueError("prepared attempt input binding mismatch")
        return stored, bound
