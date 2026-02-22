"""Markdown report generator."""

from __future__ import annotations

import time

from config.models import get_model
from core.registry import get_task


def generate_markdown(
    task_id: str,
    model_id: str,
    results: dict,
    comparison: dict | None = None,
    autopsy: dict | None = None,
    patch_rerun: dict | None = None,
) -> str:
    """Generate a Markdown audit report following the PRD Appendix E template."""
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    try:
        task = get_task(task_id)
        task_name = task.name
    except ValueError:
        task_name = task_id

    try:
        model = get_model(model_id)
        model_label = model.label
    except ValueError:
        model_label = model_id

    # --- Arena Results table ---
    rows = []
    scores = {}
    costs = []
    for scaffold_name, scaffold_data in results.items():
        metrics = scaffold_data.get("metrics", {})
        evaluation = scaffold_data.get("evaluation", {})
        score = evaluation.get("total_score", 0.0)
        scores[scaffold_name] = score
        input_tok = metrics.get("input_tokens", 0)
        output_tok = metrics.get("output_tokens", 0)
        cost_usd = metrics.get("cost_usd", 0.0)
        wall_time_ms = metrics.get("wall_time_ms", 0)
        num_api_calls = metrics.get("num_api_calls", 0)
        costs.append(cost_usd)
        rows.append(
            f"| {scaffold_name} | {score:.2f} | {input_tok:,} | {output_tok:,} |"
            f" ${cost_usd:.4f} | {wall_time_ms:,}ms | {num_api_calls} |"
        )

    arena_table = "\n".join(rows) if rows else "| — | — | — | — | — | — | — |"

    # --- Scoring methodology ---
    first_eval = next(iter(results.values()), {}).get("evaluation", {}) if results else {}
    weights_data = first_eval.get("weights", {})
    if weights_data:
        weights_lines = [f"- {k}: {v}" for k, v in weights_data.items()]
        weights_str = "\n".join(weights_lines)
    else:
        weights_str = "- (weights not available)"

    judge_info = first_eval.get("judge") or {}
    judge_model = judge_info.get("model_id", "N/A")
    judge_scores = judge_info.get("scores", {})
    judge_explanation = judge_info.get("explanation", "(no explanation provided)")
    if judge_scores:
        judge_scores_str = "\n".join(f"- {k}: {v}" for k, v in judge_scores.items())
    else:
        judge_scores_str = "- (no judge scores)"

    # --- Per-scaffold notes ---
    per_scaffold_sections = []
    for scaffold_name, scaffold_data in results.items():
        evaluation = scaffold_data.get("evaluation", {})
        breakdown = evaluation.get("breakdown", {})
        failures = evaluation.get("key_failures", [])
        patch = evaluation.get("suggested_patch", "None")

        failures_str = "\n".join(f"  - {f}" for f in failures) if failures else "  - None recorded"
        breakdown_str = ""
        if breakdown:
            breakdown_str = "\n" + "\n".join(f"  - {k}: {v}" for k, v in breakdown.items())

        section = (
            f"### {scaffold_name}\n"
            f"- Key failures:\n{failures_str}\n"
            f"- Suggested patch: {patch}"
        )
        if breakdown_str:
            section += f"\n- Score breakdown:{breakdown_str}"
        per_scaffold_sections.append(section)

    per_scaffold_notes = "\n\n".join(per_scaffold_sections) if per_scaffold_sections else "_No scaffold data._"

    # --- Auto-generated summary ---
    if scores:
        winner = max(scores, key=lambda k: scores[k])
        winner_score = scores[winner]
        cost_min = min(costs) if costs else 0.0
        cost_max = max(costs) if costs else 0.0
        auto_summary = (
            f"Winner: **{winner}** with score {winner_score:.2f}. "
            f"Cost range: ${cost_min:.4f}–${cost_max:.4f}."
        )
    else:
        auto_summary = "No results available."

    # --- Auto-generated recommendations ---
    recommendations = _build_recommendations(results, scores)
    rec_lines = "\n".join(f"{i + 1}. {r}" for i, r in enumerate(recommendations))

    # --- Optional sections ---
    patch_rerun_section = _build_patch_rerun_section(patch_rerun)
    comparison_section = _build_comparison_section(comparison)

    # --- Disclaimer ---
    disclaimer_lines = ["- Token costs computed from reported usage and price table."]
    if task_id == "research_synthesis":
        disclaimer_lines.insert(
            0,
            "- If task is Research Synthesis: **Sources are synthetic demo materials; not real publications.**",
        )
    disclaimer = "\n".join(disclaimer_lines)

    report = f"""# Scaffold Architecture Audit Report

**Generated:** {timestamp}
**Task:** {task_name} ({task_id})
**Main model:** {model_label} ({model_id})

## Executive Summary
{auto_summary}

## Arena Results
| Scaffold | Score | Input tok | Output tok | Cost | Time | API calls |
|---|---:|---:|---:|---:|---:|---:|
{arena_table}

## Scoring Methodology
**Weights**
{weights_str}

**LLM Judge**
Model: {judge_model}
Scores:
{judge_scores_str}
Notes: {judge_explanation}

## Per-Scaffold Notes
{per_scaffold_notes}

## Patch Rerun (if performed)
{patch_rerun_section}

## Proof Comparison (if performed)
{comparison_section}

## Recommendations
{rec_lines}

---
### Disclaimer
{disclaimer}
"""
    return report


def _build_recommendations(results: dict, scores: dict) -> list[str]:
    """Auto-generate up to 3 recommendations from results."""
    recs = []

    if not scores:
        return ["Run the arena with at least one scaffold to generate recommendations."]

    winner = max(scores, key=lambda k: scores[k])
    recs.append(f"Use **{winner}** as the primary scaffold for this task based on highest overall score.")

    # Cost efficiency recommendation
    cost_map = {
        name: data.get("metrics", {}).get("cost_usd", 0.0)
        for name, data in results.items()
    }
    valid_costs = {k: v for k, v in cost_map.items() if v > 0}
    if valid_costs:
        cheapest = min(valid_costs, key=lambda k: valid_costs[k])
        cheapest_score = scores.get(cheapest, 0.0)
        winner_score = scores[winner]
        if cheapest != winner and cheapest_score >= winner_score * 0.9:
            recs.append(
                f"Consider **{cheapest}** as a cost-efficient alternative "
                f"(${valid_costs[cheapest]:.4f} vs ${cost_map.get(winner, 0):.4f}, "
                f"score within 10% of winner)."
            )
        elif cheapest != winner:
            recs.append(
                f"**{cheapest}** has the lowest cost (${valid_costs[cheapest]:.4f}) "
                f"but a lower score ({cheapest_score:.2f}); suitable for budget-constrained runs."
            )

    # Patch recommendation if any scaffold has suggested patches
    patch_candidates = [
        name
        for name, data in results.items()
        if data.get("evaluation", {}).get("suggested_patch") not in (None, "None", "")
    ]
    if patch_candidates:
        recs.append(
            f"Review and apply suggested patches for: {', '.join(patch_candidates)} "
            f"to improve reliability in future runs."
        )
    elif len(recs) < 3:
        recs.append(
            "Run a patch rerun on the lowest-scoring scaffold to measure improvement potential."
        )

    return recs[:3]


def _build_patch_rerun_section(patch_rerun: dict | None) -> str:
    if not patch_rerun:
        return "_No patch rerun was performed._"

    lines = []
    for scaffold_name, data in patch_rerun.items():
        before = data.get("before_score", "N/A")
        after = data.get("after_score", "N/A")
        lines.append(f"- **{scaffold_name}**: score {before} → {after}")

    return "\n".join(lines) if lines else "_No patch rerun data available._"


def _build_comparison_section(comparison: dict | None) -> str:
    if not comparison:
        return "_No proof comparison was performed._"

    lines = []
    for scaffold_name, data in comparison.items():
        verdict = data.get("verdict", "N/A")
        notes = data.get("notes", "")
        line = f"- **{scaffold_name}**: {verdict}"
        if notes:
            line += f" — {notes}"
        lines.append(line)

    return "\n".join(lines) if lines else "_No comparison data available._"
