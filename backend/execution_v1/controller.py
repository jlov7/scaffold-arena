"""Stable public composition boundary for experiment dispatch."""

from ._controller_kernel import (
    ExecutionCreated,
    ExecutionProvenance,
    ExperimentController as _KernelExperimentController,
    _hash,
    _id,
)

# ``controlled_controller`` imports this module while it is initializing. The
# temporary binding exposes the immutable kernel as its explicit base class;
# the public binding is replaced locally—not in another module—once the
# control-complete implementation has been defined.
ExperimentController = _KernelExperimentController

from .controlled_controller import ExperimentController

__all__ = [
    "ExecutionCreated",
    "ExecutionProvenance",
    "ExperimentController",
]
