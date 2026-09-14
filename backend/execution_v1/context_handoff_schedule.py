"""Validation of the optional frozen context-handoff controller schedule.

This module deliberately depends only on protocol data and is not an adapter
or runner.  The regular controller continues to own all durable job creation.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from protocol_v1.canonical import sha256


NAMESPACE = "org.scaffold-arena.context-handoff-schedule-v1"
_POLICIES = frozenset({"isolated", "full_inherited", "curated"})


def apply_frozen_context_schedule(units: list[dict[str, Any]], extension: object, *, randomization_seed: int) -> list[dict[str, Any]]:
    """Return an exact scheduled bijection or reject before durable creation."""
    if not isinstance(extension, Mapping) or set(extension) != {"version", "shuffle_algorithm", "randomization_seed", "cells", "schedule_digest"}:
        raise ValueError("context-handoff schedule extension has unknown or missing fields")
    if extension["version"] != "1" or extension["shuffle_algorithm"] != "predeclared-policy-interleaved-v1" or extension["randomization_seed"] != randomization_seed:
        raise ValueError("context-handoff schedule extension version is unsupported")
    cells = extension["cells"]
    if not isinstance(cells, (list, tuple)) or not cells:
        raise ValueError("context-handoff schedule requires cells")
    body = {"version": extension["version"], "shuffle_algorithm": extension["shuffle_algorithm"], "randomization_seed": extension["randomization_seed"], "cells": cells}
    if not isinstance(extension["schedule_digest"], str) or extension["schedule_digest"] != sha256(body):
        raise ValueError("context-handoff schedule digest mismatch")
    expected: dict[tuple[Any, ...], dict[str, Any]] = {}
    for unit in units:
        if set(unit["treatment"]) != {"context_policy"}:
            raise ValueError("context-handoff schedule permits no co-varied treatment factors")
        policy = unit["treatment"].get("context_policy")
        key = (unit["scenario_id"], policy, unit["repetition_index"], unit["endpoint_id"], unit["provider_model"])
        if policy not in _POLICIES or key in expected:
            raise ValueError("context-handoff schedule requires exactly one policy factor per canonical cell")
        expected[key] = unit
    scheduled: list[tuple[int, dict[str, Any]]] = []
    seen: set[tuple[Any, ...]] = set()
    group_seeds: dict[tuple[str, int, str, str], int] = {}
    required = {"scenario_id", "context_policy", "repetition_index", "endpoint_id", "provider_model", "declared_seed", "ordinal"}
    for cell in cells:
        if not isinstance(cell, Mapping) or set(cell) != required:
            raise ValueError("context-handoff schedule cell has unknown or missing fields")
        if not isinstance(cell["scenario_id"], str) or cell["context_policy"] not in _POLICIES or not isinstance(cell["repetition_index"], int) or isinstance(cell["repetition_index"], bool) or cell["repetition_index"] < 0 or not isinstance(cell["endpoint_id"], str) or not isinstance(cell["provider_model"], str) or not isinstance(cell["declared_seed"], int) or isinstance(cell["declared_seed"], bool) or cell["declared_seed"] < 0 or not isinstance(cell["ordinal"], int) or isinstance(cell["ordinal"], bool) or cell["ordinal"] < 0:
            raise ValueError("context-handoff schedule cell has invalid scalar values")
        key = (cell["scenario_id"], cell["context_policy"], cell["repetition_index"], cell["endpoint_id"], cell["provider_model"])
        if key not in expected or key in seen:
            raise ValueError("context-handoff schedule is not a canonical expansion bijection")
        seen.add(key)
        group = (cell["scenario_id"], cell["repetition_index"], cell["endpoint_id"], cell["provider_model"])
        prior_seed = group_seeds.setdefault(group, cell["declared_seed"])
        if prior_seed != cell["declared_seed"]:
            raise ValueError("all context policies in a scenario/repetition group must share one declared seed")
        unit = dict(expected[key])
        unit["seed"] = int(sha256({"scenario_id": cell["scenario_id"], "repetition_index": cell["repetition_index"], "declared_seed": cell["declared_seed"]})[:16], 16) % (2**31)
        unit["frozen_schedule_ordinal"] = cell["ordinal"]
        unit["declared_seed"] = cell["declared_seed"]
        scheduled.append((cell["ordinal"], unit))
    if seen != set(expected) or {ordinal for ordinal, _ in scheduled} != set(range(len(expected))):
        raise ValueError("context-handoff schedule omits, duplicates, or reorders canonical cells")
    if len({unit["harness_id"] for unit in expected.values()}) != 1:
        raise ValueError("context-handoff schedule requires one fixed harness identity")
    scheduled.sort(key=lambda item: item[0])
    policies = [unit["treatment"]["context_policy"] for _, unit in scheduled]
    if any(policies[index:index + 3] == [policies[index]] * 3 for index in range(max(0, len(policies) - 2))):
        raise ValueError("context-handoff schedule must interleave policies rather than block them")
    return [unit for _, unit in scheduled]
