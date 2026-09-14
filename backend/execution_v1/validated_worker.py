"""Compatibility wrapper that preserves kernel validation failure semantics."""

from __future__ import annotations

import json
from collections.abc import Mapping

from adapters_v1 import AttemptInput
from persistence_v1.jobs import JobLease

from .fenced_worker import DurableWorker as _FencedDurableWorker
from .worker import DurableWorker as _KernelDurableWorker
from .worker import WorkerResult


class DurableWorker(_FencedDurableWorker):
    """Fence valid invocations while leaving malformed jobs to the kernel.

    The original durable worker is the authority that converts malformed or
    swapped AttemptInput payloads into redacted terminal evidence.  Invocation
    setup must never let a validation exception escape before that boundary.
    """

    async def run_lease(self, lease: JobLease) -> WorkerResult:
        raw_input = lease.payload.get("attempt_input")
        if isinstance(raw_input, Mapping):
            try:
                AttemptInput.model_validate_json(json.dumps(raw_input))
            except (TypeError, ValueError, json.JSONDecodeError):
                return await _KernelDurableWorker.run_lease(self, lease)
        return await super().run_lease(lease)
