"""Evaluation harness — combines deterministic + optional LLM judge scores."""

from __future__ import annotations

import logging

from config.settings import settings
from core.provider import LLMProvider
from evaluation.deterministic import (
    citation_coverage,
    data_minimization_coverage,
    false_positive_rate,
    field_accuracy,
    forbidden_tool_avoidance,
    must_flag_hit_rate,
    privacy_boundary_compliance,
    recovery_step_coverage,
    required_findings_coverage,
    required_section_coverage,
    required_term_coverage,
    risk_level_accuracy,
    schema_validity,
    structure_compliance,
    tool_selection_accuracy,
    unsupported_claim_avoidance,
    word_count_compliance,
)
from tasks.base import BaseTask

logger = logging.getLogger(__name__)

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
    "tool_use": {
        "schema_validity": {"weight": 0.25, "type": "deterministic"},
        "tool_selection_accuracy": {"weight": 0.30, "type": "deterministic"},
        "forbidden_tool_avoidance": {"weight": 0.25, "type": "deterministic"},
        "recovery_step_coverage": {"weight": 0.10, "type": "deterministic"},
        "recovery_quality": {"weight": 0.10, "type": "judge"},
    },
    "privacy": {
        "schema_validity": {"weight": 0.25, "type": "deterministic"},
        "privacy_boundary_compliance": {"weight": 0.40, "type": "deterministic"},
        "data_minimization_coverage": {"weight": 0.25, "type": "deterministic"},
        "escalation_quality": {"weight": 0.10, "type": "judge"},
    },
    "strategy": {
        "schema_validity": {"weight": 0.30, "type": "deterministic"},
        "required_section_coverage": {"weight": 0.30, "type": "deterministic"},
        "required_term_coverage": {"weight": 0.20, "type": "deterministic"},
        "unsupported_claim_avoidance": {"weight": 0.10, "type": "deterministic"},
        "actionability": {"weight": 0.10, "type": "judge"},
    },
    "custom": {
        "schema_validity": {"weight": 0.70, "type": "deterministic"},
        "output_presence": {"weight": 0.30, "type": "deterministic"},
    },
}

EVALUATION_PROFILES: dict[str, dict[str, float]] = {
    "balanced": {"deterministic_boost": 1.0, "judge_boost": 1.0},
    "strict": {"deterministic_boost": 1.12, "judge_boost": 0.55},
    "cost_first": {"deterministic_boost": 1.2, "judge_boost": 0.35},
}


def _resolve_weights(task_type: str, evaluation_profile: str) -> dict[str, dict]:
    if task_type not in WEIGHT_TABLES:
        raise ValueError(f"Unknown task type: {task_type}")
    if evaluation_profile not in EVALUATION_PROFILES:
        raise ValueError(
            f"Unknown evaluation profile: {evaluation_profile}. "
            f"Supported: {sorted(EVALUATION_PROFILES)}"
        )

    base_weights = WEIGHT_TABLES[task_type]
    profile = EVALUATION_PROFILES[evaluation_profile]
    adjusted: dict[str, dict] = {}
    total = 0.0
    for metric, entry in base_weights.items():
        multiplier = (
            profile["deterministic_boost"]
            if entry["type"] == "deterministic"
            else profile["judge_boost"]
        )
        weight = entry["weight"] * multiplier
        adjusted[metric] = {"type": entry["type"], "weight": weight}
        total += weight

    if total <= 0:
        return base_weights

    normalized: dict[str, dict] = {}
    for metric, entry in adjusted.items():
        normalized[metric] = {
            "type": entry["type"],
            "weight": round(entry["weight"] / total, 6),
        }
    return normalized


async def evaluate(
    task: BaseTask,
    raw_output: str,
    provider: LLMProvider,
    model_id: str,
    evaluation_profile: str = "balanced",
) -> dict:
    weights = _resolve_weights(task.task_type, evaluation_profile)
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

    elif task.task_type == "tool_use":
        gold = task.get_gold()

        sv_result = schema_validity(raw_output, task.get_schema())
        breakdown["schema_validity"] = sv_result.score
        notes.extend(sv_result.notes)

        ts_result = tool_selection_accuracy(raw_output, gold)
        breakdown["tool_selection_accuracy"] = ts_result.score
        notes.extend(ts_result.notes)

        ft_result = forbidden_tool_avoidance(raw_output, gold)
        breakdown["forbidden_tool_avoidance"] = ft_result.score
        notes.extend(ft_result.notes)

        rs_result = recovery_step_coverage(raw_output, gold)
        breakdown["recovery_step_coverage"] = rs_result.score
        notes.extend(rs_result.notes)

    elif task.task_type == "privacy":
        gold = task.get_gold()

        sv_result = schema_validity(raw_output, task.get_schema())
        breakdown["schema_validity"] = sv_result.score
        notes.extend(sv_result.notes)

        pb_result = privacy_boundary_compliance(raw_output, gold)
        breakdown["privacy_boundary_compliance"] = pb_result.score
        notes.extend(pb_result.notes)

        dm_result = data_minimization_coverage(raw_output, gold)
        breakdown["data_minimization_coverage"] = dm_result.score
        notes.extend(dm_result.notes)

    elif task.task_type == "strategy":
        gold = task.get_gold()

        sv_result = schema_validity(raw_output, task.get_schema())
        breakdown["schema_validity"] = sv_result.score
        notes.extend(sv_result.notes)

        rs_result = required_section_coverage(raw_output, gold.get("required_sections", []))
        breakdown["required_section_coverage"] = rs_result.score
        notes.extend(rs_result.notes)

        rt_result = required_term_coverage(raw_output, gold.get("required_terms", []))
        breakdown["required_term_coverage"] = rt_result.score
        notes.extend(rt_result.notes)

        uc_result = unsupported_claim_avoidance(raw_output, gold.get("forbidden_terms", []))
        breakdown["unsupported_claim_avoidance"] = uc_result.score
        notes.extend(uc_result.notes)

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
        # The optional judge must not invalidate deterministic evaluation.
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM judge unavailable; using deterministic evaluation only: %s", exc)

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
        "profile": evaluation_profile,
        "notes": notes,
        "judge": judge_result,
    }
