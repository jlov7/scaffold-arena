"""Evaluation harness — combines deterministic + optional LLM judge scores."""

from __future__ import annotations

from core.provider import LLMProvider
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
    "risk": {
        "must_flag_hit_rate": {"weight": 0.45, "type": "deterministic"},
        "risk_level_accuracy": {"weight": 0.20, "type": "deterministic"},
        "false_positive_rate": {"weight": 0.10, "type": "deterministic"},
        "structure_compliance": {"weight": 0.10, "type": "deterministic"},
        "recommendation_quality": {"weight": 0.15, "type": "judge"},
    },
    "research": {
        "citation_coverage": {"weight": 0.35, "type": "deterministic"},
        "required_findings_coverage": {"weight": 0.25, "type": "deterministic"},
        "schema_validity": {"weight": 0.15, "type": "deterministic"},
        "word_count_compliance": {"weight": 0.10, "type": "deterministic"},
        "synthesis_quality": {"weight": 0.10, "type": "judge"},
        "recommendation_quality": {"weight": 0.05, "type": "judge"},
    },
    "custom": {
        "schema_validity": {"weight": 0.70, "type": "deterministic"},
        "output_presence": {"weight": 0.30, "type": "deterministic"},
    },
}


async def evaluate(
    task: BaseTask,
    raw_output: str,
    provider: LLMProvider,
    model_id: str,
) -> dict:
    if task.task_type not in WEIGHT_TABLES:
        raise ValueError(f"Unknown task type: {task.task_type}")

    weights = WEIGHT_TABLES[task.task_type]
    breakdown: dict[str, float] = {}
    notes: list[str] = []

    # --- Deterministic metrics ---
    if task.task_type == "extraction":
        sv_result = schema_validity(raw_output, task.get_schema())
        breakdown["schema_validity"] = sv_result.score
        notes.extend(sv_result.notes)

        fa_result = field_accuracy(raw_output, task.get_gold())
        breakdown["field_accuracy"] = fa_result.score
        notes.extend(fa_result.notes)

    elif task.task_type == "risk":
        mf_result = must_flag_hit_rate(raw_output, task.get_gold())
        breakdown["must_flag_hit_rate"] = mf_result.score
        notes.extend(mf_result.notes)

        fp_result = false_positive_rate(raw_output)
        breakdown["false_positive_rate"] = fp_result.score
        notes.extend(fp_result.notes)

        rl_result = risk_level_accuracy(raw_output, task.get_gold())
        breakdown["risk_level_accuracy"] = rl_result.score
        notes.extend(rl_result.notes)

        sc_result = structure_compliance(raw_output, task.get_schema())
        breakdown["structure_compliance"] = sc_result.score
        notes.extend(sc_result.notes)

    elif task.task_type == "research":
        gold = task.get_gold()

        cc_result = citation_coverage(raw_output, gold.get("required_sources", []))
        breakdown["citation_coverage"] = cc_result.score
        notes.extend(cc_result.notes)

        rf_result = required_findings_coverage(raw_output, gold.get("required_findings", []))
        breakdown["required_findings_coverage"] = rf_result.score
        notes.extend(rf_result.notes)

        sv_result = schema_validity(raw_output, task.get_schema())
        breakdown["schema_validity"] = sv_result.score
        notes.extend(sv_result.notes)

        wc_result = word_count_compliance(raw_output)
        breakdown["word_count_compliance"] = wc_result.score
        notes.extend(wc_result.notes)

    elif task.task_type == "custom":
        sv_result = schema_validity(raw_output, task.get_schema())
        breakdown["schema_validity"] = sv_result.score
        notes.extend(sv_result.notes)

        output_presence = 100.0 if raw_output.strip() else 0.0
        breakdown["output_presence"] = output_presence
        if output_presence == 0:
            notes.append("Output was empty")

    # --- LLM judge ---
    judge_result = None
    if settings.enable_llm_judge:
        try:
            from evaluation.llm_judge import run_judge
            judge_result = await run_judge(task, raw_output, provider, model_id)
        except (ImportError, Exception):
            pass

    judge_scores = judge_result.get("scores", {}) if judge_result is not None else {}
    if judge_result is not None:
        for metric, entry in weights.items():
            if entry["type"] == "judge" and metric in judge_scores:
                breakdown[metric] = judge_scores[metric]

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
