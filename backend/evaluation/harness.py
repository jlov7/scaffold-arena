"""Evaluation harness — combines deterministic + optional LLM judge scores."""

from __future__ import annotations

from core.provider import AnthropicProvider
from config.settings import settings
from tasks.base import BaseTask
from evaluation.deterministic import (
    schema_validity,
    field_accuracy,
    must_flag_hit_rate,
    false_positive_rate,
    risk_level_accuracy,
    structure_compliance,
    citation_coverage,
    required_findings_coverage,
    word_count_compliance,
)

WEIGHT_TABLES = {
    "extraction": {
        "schema_validity": {"weight": 0.45, "type": "deterministic"},
        "field_accuracy": {"weight": 0.30, "type": "deterministic"},
        "completeness": {"weight": 0.15, "type": "judge"},
        "reasoning_clarity": {"weight": 0.10, "type": "judge"},
    },
    "risk_analysis": {
        "must_flag_hit_rate": {"weight": 0.45, "type": "deterministic"},
        "risk_level_accuracy": {"weight": 0.20, "type": "deterministic"},
        "false_positive_rate": {"weight": 0.10, "type": "deterministic"},
        "structure_compliance": {"weight": 0.10, "type": "deterministic"},
        "recommendation_quality": {"weight": 0.15, "type": "judge"},
    },
    "research_synthesis": {
        "citation_coverage": {"weight": 0.35, "type": "deterministic"},
        "required_findings_coverage": {"weight": 0.25, "type": "deterministic"},
        "schema_validity": {"weight": 0.15, "type": "deterministic"},
        "word_count_compliance": {"weight": 0.10, "type": "deterministic"},
        "synthesis_quality": {"weight": 0.10, "type": "judge"},
        "recommendation_quality": {"weight": 0.05, "type": "judge"},
    },
}


async def evaluate(
    task: BaseTask,
    raw_output: str,
    provider: AnthropicProvider,
    model_id: str,
) -> dict:
    weights = WEIGHT_TABLES[task.task_type]
    breakdown: dict[str, float] = {}
    notes: list[str] = []

    # --- Deterministic metrics ---
    if task.task_type == "extraction":
        sv_score, sv_notes = schema_validity(raw_output, task.get_schema())
        breakdown["schema_validity"] = sv_score
        notes.extend(sv_notes)

        fa_score, fa_notes = field_accuracy(raw_output, task.get_gold())
        breakdown["field_accuracy"] = fa_score
        notes.extend(fa_notes)

    elif task.task_type == "risk_analysis":
        mf_score, mf_notes = must_flag_hit_rate(raw_output, task.get_gold())
        breakdown["must_flag_hit_rate"] = mf_score
        notes.extend(mf_notes)

        fp_score, fp_notes = false_positive_rate(raw_output)
        breakdown["false_positive_rate"] = fp_score
        notes.extend(fp_notes)

        rl_score, rl_notes = risk_level_accuracy(raw_output, task.get_gold())
        breakdown["risk_level_accuracy"] = rl_score
        notes.extend(rl_notes)

        sc_score, sc_notes = structure_compliance(raw_output, task.get_schema())
        breakdown["structure_compliance"] = sc_score
        notes.extend(sc_notes)

    elif task.task_type == "research_synthesis":
        gold = task.get_gold()

        cc_score, cc_notes = citation_coverage(raw_output, gold.get("required_sources", []))
        breakdown["citation_coverage"] = cc_score
        notes.extend(cc_notes)

        rf_score, rf_notes = required_findings_coverage(raw_output, gold.get("required_findings", []))
        breakdown["required_findings_coverage"] = rf_score
        notes.extend(rf_notes)

        sv_score, sv_notes = schema_validity(raw_output, task.get_schema())
        breakdown["schema_validity"] = sv_score
        notes.extend(sv_notes)

        wc_score, wc_notes = word_count_compliance(raw_output)
        breakdown["word_count_compliance"] = wc_score
        notes.extend(wc_notes)

    # --- LLM judge ---
    judge_result = None
    if settings.enable_llm_judge:
        try:
            from evaluation.llm_judge import run_judge
            judge_result = await run_judge(task, raw_output, provider, model_id)
        except (ImportError, Exception):
            pass

    if judge_result is not None:
        for metric, entry in weights.items():
            if entry["type"] == "judge" and metric in judge_result:
                breakdown[metric] = judge_result[metric]

    # --- Score combination ---
    use_judge = judge_result is not None

    if use_judge:
        total_score = sum(
            breakdown.get(metric, 0.0) * entry["weight"]
            for metric, entry in weights.items()
        )
    else:
        # Redistribute judge weights to deterministic metrics proportionally
        det_total = sum(
            entry["weight"] for entry in weights.values() if entry["type"] == "deterministic"
        )
        total_score = sum(
            breakdown.get(metric, 0.0) * (entry["weight"] / det_total)
            for metric, entry in weights.items()
            if entry["type"] == "deterministic"
        )

    total_score = round(total_score, 1)

    return {
        "total_score": total_score,
        "breakdown": breakdown,
        "weights": weights,
        "notes": notes,
        "judge": judge_result,
    }
