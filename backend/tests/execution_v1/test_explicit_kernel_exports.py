from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _probe(prelude: str) -> dict[str, object]:
    script = f"""
import importlib
import json
{prelude}
package = importlib.import_module('execution_v1')
controller = importlib.import_module('execution_v1.controller')
worker = importlib.import_module('execution_v1.worker')
budget = importlib.import_module('execution_v1.budget')
controller_kernel = importlib.import_module('execution_v1._controller_kernel')
worker_kernel = importlib.import_module('execution_v1._worker_kernel')
budget_kernel = importlib.import_module('execution_v1._budget_kernel')
assert package.ExperimentController is controller.ExperimentController
assert package.DurableWorker is worker.DurableWorker
assert package.BudgetReservationService is budget.BudgetReservationService
assert controller.ExperimentController.__module__ == 'execution_v1.controlled_controller'
assert worker.DurableWorker.__module__ == 'execution_v1.validated_worker'
assert budget.BudgetReservationService.__module__ == 'execution_v1.reservation_policy'
assert controller_kernel.ExperimentController in controller.ExperimentController.__mro__
assert worker_kernel.DurableWorker in worker.DurableWorker.__mro__
assert budget_kernel.BudgetReservationService in budget.BudgetReservationService.__mro__
print(json.dumps({{
    'controller': controller.ExperimentController.__module__,
    'worker': worker.DurableWorker.__module__,
    'budget': budget.BudgetReservationService.__module__,
    'controller_mro': [item.__module__ for item in controller.ExperimentController.__mro__],
    'worker_mro': [item.__module__ for item in worker.DurableWorker.__mro__],
    'budget_mro': [item.__module__ for item in budget.BudgetReservationService.__mro__],
}}, sort_keys=True))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    "prelude",
    (
        "import execution_v1",
        "import execution_v1.controller",
        "import execution_v1.worker",
        "import execution_v1.budget",
        "import execution_v1.fenced_worker",
        "import execution_v1.reservation_policy",
    ),
)
def test_public_execution_classes_are_explicit_and_import_order_independent(
    prelude: str,
) -> None:
    observed = _probe(prelude)
    assert observed["controller"] == "execution_v1.controlled_controller"
    assert observed["worker"] == "execution_v1.validated_worker"
    assert observed["budget"] == "execution_v1.reservation_policy"


def test_package_initialization_and_policy_modules_do_not_mutate_other_modules() -> None:
    assignment = re.compile(r"(?m)^\s*_[A-Za-z][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*\s*=")
    for relative in (
        Path("execution_v1/__init__.py"),
        Path("execution_v1/reservation_policy.py"),
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert assignment.search(source) is None, relative


def test_canonical_modules_are_thin_composition_boundaries() -> None:
    expectations = {
        "execution_v1/controller.py": (
            "from ._controller_kernel import",
            "from .controlled_controller import ExperimentController",
        ),
        "execution_v1/worker.py": (
            "from ._worker_kernel import",
            "from .validated_worker import DurableWorker",
        ),
        "execution_v1/budget.py": (
            "from ._budget_kernel import",
            "from .reservation_policy import BudgetReservationService",
        ),
    }
    for relative, required in expectations.items():
        source = (ROOT / relative).read_text(encoding="utf-8")
        for statement in required:
            assert statement in source, (relative, statement)
