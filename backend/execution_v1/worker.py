"""Stable public composition boundary for the durable worker."""

from ._worker_kernel import (
    AttemptEvidence,
    CancellationRequested,
    DurableWorker as _KernelDurableWorker,
    LeaseLost,
    MissingOutputEvidence,
    MissingUsageEvidence,
    PartialTrace,
    UsageMismatch,
    WorkerResult,
)

# ``fenced_worker`` and ``validated_worker`` import this module while it is
# initializing. They receive the immutable kernel as their explicit base; the
# final public worker is rebound only inside this canonical module.
DurableWorker = _KernelDurableWorker

from .validated_worker import DurableWorker

__all__ = [
    "AttemptEvidence",
    "CancellationRequested",
    "DurableWorker",
    "LeaseLost",
    "MissingOutputEvidence",
    "MissingUsageEvidence",
    "PartialTrace",
    "UsageMismatch",
    "WorkerResult",
]
