from __future__ import annotations

from collections import defaultdict
from typing import Any

from core.storage import list_runs

_BIN_LABELS = ["0-20", "20-40", "40-60", "60-80", "80-100"]


def _to_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _extract_score(result: dict[str, Any]) -> float | None:
    evaluation = result.get("evaluation")
    if not isinstance(evaluation, dict):
        return None
    score = _to_float(evaluation.get("total_score"))
    if score is None:
        return None
    return max(0.0, min(100.0, score))


def _extract_cost(result: dict[str, Any]) -> float | None:
    metrics = result.get("metrics")
    if not isinstance(metrics, dict):
        return None
    cost = _to_float(metrics.get("cost_usd"))
    if cost is None:
        return None
    return max(0.0, cost)


def _distribution_bin(score: float) -> int:
    if score >= 100:
        return 4
    return max(0, min(4, int(score // 20)))


def compute_stats(limit: int = 1000) -> dict[str, Any]:
    clamped_limit = max(1, min(limit, 5000))
    runs = list_runs(limit=clamped_limit)
    arena_runs = [
        run
        for run in runs
        if run.get("kind") == "arena" and isinstance(run.get("results"), dict)
    ]

    scaffold_stats: dict[str, dict[str, Any]] = {}
    task_scores: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )

    for run in arena_runs:
        task_id = str(run.get("task_id") or "unknown")
        winner_id = run.get("winner_id")
        results = run.get("results")
        if not isinstance(results, dict):
            continue

        for scaffold_id, payload in results.items():
            if not isinstance(scaffold_id, str) or not isinstance(payload, dict):
                continue

            entry = scaffold_stats.setdefault(
                scaffold_id,
                {
                    "wins": 0,
                    "scores": [],
                    "costs": [],
                    "distribution": [0, 0, 0, 0, 0],
                },
            )

            score = _extract_score(payload)
            if score is not None:
                entry["scores"].append(score)
                entry["distribution"][_distribution_bin(score)] += 1
                task_scores[task_id][scaffold_id].append(score)

            cost = _extract_cost(payload)
            if cost is not None:
                entry["costs"].append(cost)

        if isinstance(winner_id, str):
            winner_entry = scaffold_stats.setdefault(
                winner_id,
                {
                    "wins": 0,
                    "scores": [],
                    "costs": [],
                    "distribution": [0, 0, 0, 0, 0],
                },
            )
            winner_entry["wins"] += 1

    run_count = len(arena_runs)
    scaffold_rows = []
    for scaffold_id, entry in scaffold_stats.items():
        scores = entry["scores"]
        costs = entry["costs"]
        avg_score = sum(scores) / len(scores) if scores else 0.0
        avg_cost = sum(costs) / len(costs) if costs else 0.0
        win_rate = (entry["wins"] / run_count * 100.0) if run_count else 0.0
        scaffold_rows.append(
            {
                "scaffold_id": scaffold_id,
                "wins": int(entry["wins"]),
                "win_rate": round(win_rate, 2),
                "avg_score": round(avg_score, 2),
                "avg_cost": round(avg_cost, 6),
                "samples": len(scores),
            }
        )
    scaffold_rows.sort(
        key=lambda row: (row["win_rate"], row["avg_score"], -row["avg_cost"]),
        reverse=True,
    )

    task_rows: dict[str, list[dict[str, Any]]] = {}
    for task_id, by_scaffold in task_scores.items():
        rows = []
        for scaffold_id, scores in by_scaffold.items():
            avg_score = sum(scores) / len(scores) if scores else 0.0
            rows.append(
                {
                    "scaffold_id": scaffold_id,
                    "avg_score": round(avg_score, 2),
                    "samples": len(scores),
                }
            )
        rows.sort(key=lambda row: row["avg_score"], reverse=True)
        task_rows[task_id] = rows

    distributions = []
    for row in scaffold_rows:
        scaffold_id = row["scaffold_id"]
        bins = scaffold_stats.get(scaffold_id, {}).get("distribution", [0, 0, 0, 0, 0])
        distributions.append(
            {
                "scaffold_id": scaffold_id,
                "bins": [
                    {"label": _BIN_LABELS[idx], "count": int(count)}
                    for idx, count in enumerate(bins)
                ],
            }
        )

    return {
        "run_count": run_count,
        "scaffolds": scaffold_rows,
        "by_task": task_rows,
        "distributions": distributions,
    }
