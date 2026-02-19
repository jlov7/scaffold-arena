"""Task and scaffold registries."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scaffolds.base import BaseScaffold
    from tasks.base import BaseTask

_tasks: dict[str, BaseTask] = {}
_scaffolds: dict[str, BaseScaffold] = {}


def register_task(task: BaseTask) -> None:
    _tasks[task.id] = task


def register_scaffold(scaffold: BaseScaffold) -> None:
    _scaffolds[scaffold.id] = scaffold


def get_task(task_id: str) -> BaseTask:
    if task_id not in _tasks:
        raise ValueError(f"Unknown task: {task_id}")
    return _tasks[task_id]


def get_scaffold(scaffold_id: str) -> BaseScaffold:
    if scaffold_id not in _scaffolds:
        raise ValueError(f"Unknown scaffold: {scaffold_id}")
    return _scaffolds[scaffold_id]


def all_tasks_meta() -> list[dict]:
    return [
        {
            "id": t.id,
            "name": t.name,
            "subtitle": t.subtitle,
            "type": t.task_type,
            **({"synthetic_sources": True} if t.synthetic_sources else {}),
        }
        for t in _tasks.values()
    ]


def all_scaffolds_meta() -> list[dict]:
    return [
        {
            "id": s.id,
            "name": s.name,
            "subtitle": s.subtitle,
        }
        for s in _scaffolds.values()
    ]
