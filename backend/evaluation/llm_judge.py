"""LLM judge — supplementary qualitative scoring via cheap model."""

from __future__ import annotations

import json

from config.models import get_model
from config.settings import settings
from core.provider import LLMProvider, get_provider
from tasks.base import BaseTask

RUBRICS: dict[str, dict[str, str]] = {
    "extraction": {
        "completeness": "Does the output capture all key information from the document?",
        "reasoning_clarity": "Is the output well-organized and clearly structured?",
    },
    "risk": {
        "recommendation_quality": "Are the risk recommendations actionable, specific, and well-justified?",
    },
    "research": {
        "synthesis_quality": "Is the synthesis coherent, balanced across sources, and insightful?",
        "recommendation_quality": "Are the recommendations specific, actionable, and evidence-based?",
    },
}


def _build_rubric_text(rubric: dict[str, str]) -> str:
    return "\n".join(f"- {criterion}: {description}" for criterion, description in rubric.items())


def _default_scores(rubric: dict[str, str], score: int = 50) -> dict[str, int]:
    return {criterion: score for criterion in rubric}


async def run_judge(
    task: BaseTask,
    raw_output: str,
    provider: LLMProvider,
    model_id: str,
) -> dict:
    rubric = RUBRICS.get(task.task_type, {})

    if not rubric:
        return {
            "scores": {},
            "explanation": f"No rubric defined for task type '{task.task_type}'.",
            "model_id": settings.default_cheap_model_id,
        }

    try:
        judge_model_id = settings.default_cheap_model_id
        judge_provider = provider
        if get_model(model_id).provider != get_model(judge_model_id).provider:
            judge_provider = get_provider(judge_model_id)

        rubric_text = _build_rubric_text(rubric)

        prompt = (
            f"You are an expert evaluator scoring an LLM output on qualitative criteria.\n\n"
            f"TASK TYPE: {task.task_type}\n"
            f"TASK: {task.get_input_text()[:500]}\n\n"
            f"OUTPUT TO EVALUATE:\n{raw_output[:2000]}\n\n"
            f"Score each criterion 0–100:\n{rubric_text}\n\n"
            f'Return ONLY a JSON object:\n{{"scores": {{"criterion_name": score, ...}}, "explanation": "Brief justification (2-3 sentences)"}}'
        )

        result = await judge_provider.complete(
            model_id=judge_model_id,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )

        try:
            parsed = json.loads(result.text)
            scores = parsed.get("scores", _default_scores(rubric))
            explanation = parsed.get("explanation", "")
        except json.JSONDecodeError:
            scores = _default_scores(rubric)
            explanation = "Judge response could not be parsed; defaulting to 50 for all criteria."

        return {
            "scores": scores,
            "explanation": explanation,
            "model_id": judge_model_id,
        }

    except Exception as exc:
        rubric = RUBRICS.get(task.task_type, {})
        return {
            "scores": _default_scores(rubric),
            "explanation": f"Judge failed with error: {exc}",
            "model_id": settings.default_cheap_model_id,
        }
