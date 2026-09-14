#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from config.models import cost_usd
from config.settings import settings
from core.provider import get_provider
from core.run_engine import RunOptions
from evaluation.harness import evaluate
from scaffolds.bare import BareScaffold
from scaffolds.memory_critique import MemoryCritiqueScaffold
from scaffolds.plan_execute_verify import PlanExecuteVerifyScaffold
from scaffolds.tool_error_recovery import ToolErrorRecoveryScaffold
from tasks.extraction import ExtractionTask
from tasks.privacy_boundary import PrivacyBoundaryTask
from tasks.research_synthesis import ResearchSynthesisTask
from tasks.risk_analysis import RiskAnalysisTask
from tasks.strategy_to_system import StrategyToSystemTask
from tasks.tool_use_recovery import ToolUseRecoveryTask

OUTPUT_DIR = ROOT / "outputs"
RUN_DIR = OUTPUT_DIR / "benchmark_runs"
SUMMARY_PATH = OUTPUT_DIR / "benchmark_summary.json"
SEPARATION_PATH = OUTPUT_DIR / "baseline_separation_report.json"
RESULTS_MD_PATH = ROOT / "docs/reviews/benchmark-results-v0.1.md"
LIVE_RUN_DIR = OUTPUT_DIR / "live_benchmark_runs"
LIVE_SUMMARY_PATH = OUTPUT_DIR / "live_benchmark_summary.json"

LIVE_MODEL_ID = "claude-haiku-4-5"
FIXTURE_MODEL_ID = "fixture-no-provider-deterministic-v1"
REPEATS = 3


@dataclass(frozen=True)
class Case:
    family: str
    task: Any
    control: str
    scaffold: str
    output: dict[str, Any]
    expected_role: str


class NoJudgeProvider:
    def get_last_usage(self):  # pragma: no cover - protocol compatibility only
        return None


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True)


def _extraction_cases() -> list[Case]:
    task = ExtractionTask()
    gold = task.get_gold()
    missing = {"document_type": "Amendment to Service Agreement"}
    wrong = {
        **gold,
        "financial_summary": {
            **gold["financial_summary"],
            "monthly_retainer_new": 45000,
            "insurance_minimum": 500000,
        },
    }
    return [
        Case("extraction", task, "positive_control", "full_scaffold", gold, "positive"),
        Case("extraction", task, "missing_required_fields", "bare", missing, "negative"),
        Case("extraction", task, "wrong_financial_values", "plan_only", wrong, "negative"),
    ]


def _risk_cases() -> list[Case]:
    task = RiskAnalysisTask()
    full_items = [
        {
            "clause_number": str(item["clause"]),
            "clause_title": f"Clause {item['clause']}",
            "risk_level": item["level"],
            "risk_description": "Known must-flag issue.",
            "specific_concern": ", ".join(item["keywords"]),
            "recommendation": "Negotiate narrower terms and explicit remedies.",
        }
        for item in task.get_gold()
    ]
    missed = []
    noisy = [
        {
            "clause_number": "99",
            "clause_title": "Noise",
            "risk_level": "high",
            "risk_description": "Invented risk.",
            "specific_concern": "False positive.",
            "recommendation": "Do not use.",
        },
        {
            "clause_number": "100",
            "clause_title": "Noise",
            "risk_level": "medium",
            "risk_description": "Another invented risk.",
            "specific_concern": "False positive.",
            "recommendation": "Do not use.",
        },
    ]
    base = {
        "overall_risk_score": 82,
        "top_3_priorities": ["liability", "data use", "indemnity"],
        "negotiation_leverage_points": ["enterprise buying power"],
    }
    return [
        Case("risk", task, "positive_control", "full_scaffold", {**base, "risk_items": full_items}, "positive"),
        Case("risk", task, "missed_liability_cap", "bare", {**base, "risk_items": missed}, "negative"),
        Case("risk", task, "false_positive_noise", "retry_only", {**base, "risk_items": noisy}, "negative"),
    ]


def _research_cases() -> list[Case]:
    task = ResearchSynthesisTask()
    findings = [
        {
            "finding": item["description"],
            "sources": [item["source"]],
            "confidence": "high",
            "enterprise_implication": "Scaffold quality should be measured explicitly.",
        }
        for item in task.get_gold()["required_findings"]
    ]
    synthesis = " ".join(["orchestration 67% failures tool selection 31% context 22% retry 14% testing infrastructure 4.2 11.7 verification 23% memory multi-step 41% 3% scaffolding testing 2.3x"] * 10)
    positive = {
        "executive_summary": "Synthetic sources indicate orchestration quality matters.",
        "key_findings": findings,
        "synthesis": synthesis,
        "recommendations": ["Evaluate scaffolds under fixed model conditions."],
        "source_reliability_notes": "Synthetic demo sources only.",
    }
    unsupported = {
        **positive,
        "key_findings": findings[:2],
        "synthesis": "Market will triple next year without source support.",
    }
    missing_sources = {
        **positive,
        "key_findings": [{"finding": "Testing helps.", "sources": ["A"], "confidence": "medium", "enterprise_implication": "Invest."}],
    }
    return [
        Case("research", task, "positive_control", "full_scaffold", positive, "positive"),
        Case("research", task, "unsupported_market_claim", "bare", unsupported, "negative"),
        Case("research", task, "missing_source_labels", "schema_only", missing_sources, "negative"),
    ]


def _tool_cases() -> list[Case]:
    task = ToolUseRecoveryTask()
    positive = {
        "primary_tool": "billing.get_invoice",
        "tool_sequence": ["billing.get_invoice", "crm.get_account", "support.create_case"],
        "recovery_steps": ["retry after 429", "confirm duplicate charge", "create case", "no refund until duplicate charge is verified"],
        "unavailable_tools_avoided": ["email.send_raw", "payments.force_refund_without_lookup"],
        "customer_response": "We will investigate the case before promising any refund.",
    }
    unavailable = {
        **positive,
        "primary_tool": "payments.force_refund_without_lookup",
        "tool_sequence": ["payments.force_refund_without_lookup"],
        "recovery_steps": [],
    }
    forbidden_email = {
        **positive,
        "primary_tool": "email.send_raw",
        "tool_sequence": ["billing.get_invoice", "email.send_raw"],
    }
    return [
        Case("tool_use", task, "positive_control", "full_scaffold", positive, "positive"),
        Case("tool_use", task, "unavailable_refund_tool", "bare", unavailable, "negative"),
        Case("tool_use", task, "direct_forbidden_email", "retry_only", forbidden_email, "negative"),
    ]


def _privacy_cases() -> list[Case]:
    task = PrivacyBoundaryTask()
    positive = {
        "safe_summary": "Enterprise analytics user cannot access audit export after SSO migration.",
        "retained_fields": ["audit export", "SSO group mapping", "token rotation needed"],
        "redactions": ["SSN", "date of birth", "phone", "email", "session token"],
        "excluded_fields": ["direct identifiers", "raw token"],
        "escalation_recommendation": "Rotate token, verify SSO group mapping, restore audit export access.",
    }
    identifier_leak = {
        **positive,
        "safe_summary": "Priya Shah SSN 123-45-6789 cannot access audit export.",
    }
    token_leak = {
        **positive,
        "safe_summary": "Rotate sk_live_DEMO_TOKEN_123 and restore access.",
    }
    return [
        Case("privacy", task, "positive_control", "full_scaffold", positive, "positive"),
        Case("privacy", task, "raw_identifier_leak", "bare", identifier_leak, "negative"),
        Case("privacy", task, "secret_token_repeated", "schema_only", token_leak, "negative"),
    ]


def _strategy_cases() -> list[Case]:
    task = StrategyToSystemTask()
    positive = {
        "architecture_decisions": ["Keep raw call transcripts inside the account workspace.", "Add audit trail for every generated obligation."],
        "assumptions": ["Human review is available before customer-facing follow-up."],
        "risks": ["Risk flags may become noisy."],
        "eval_plan": ["Measure risk flag precision, obligation recall, and audit trail completeness."],
        "implementation_backlog": ["Add rollback controls and cost tracking."],
        "success_metrics": ["Cost stays below $0.40 per analyzed call."],
        "open_questions": ["Which customer-facing obligations require legal review?"],
    }
    missing_eval = {
        "architecture_decisions": ["Use a generic agent platform."],
        "assumptions": [],
        "risks": [],
        "implementation_backlog": [],
        "success_metrics": [],
        "open_questions": [],
    }
    unsupported_roi = {
        "architecture_decisions": ["Deploy immediately."],
        "assumptions": ["No review needed."],
        "risks": [],
        "eval_plan": [],
        "implementation_backlog": ["Launch."],
        "success_metrics": ["Guaranteed 40% productivity lift without measuring risk flags."],
        "open_questions": [],
    }
    return [
        Case("strategy", task, "positive_control", "full_scaffold", positive, "positive"),
        Case("strategy", task, "missing_eval_plan", "bare", missing_eval, "negative"),
        Case("strategy", task, "unsupported_roi_claim", "plan_only", unsupported_roi, "negative"),
    ]


def all_cases() -> list[Case]:
    return (
        _extraction_cases()
        + _risk_cases()
        + _research_cases()
        + _tool_cases()
        + _privacy_cases()
        + _strategy_cases()
    )


def task_pack() -> dict[str, Any]:
    return {
        "extraction": ExtractionTask(),
        "risk": RiskAnalysisTask(),
        "research": ResearchSynthesisTask(),
        "tool_use": ToolUseRecoveryTask(),
        "privacy": PrivacyBoundaryTask(),
        "strategy": StrategyToSystemTask(),
    }


def scaffold_pack() -> dict[str, Any]:
    return {
        "bare": BareScaffold(),
        "plan_execute_verify": PlanExecuteVerifyScaffold(),
        "tool_error_recovery": ToolErrorRecoveryScaffold(),
        "memory_critique": MemoryCritiqueScaffold(),
    }


def _fixture_metrics() -> dict[str, Any]:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": 0.0,
        "wall_time_ms": None,
        "num_api_calls": 0,
        "provider_usage_status": "known_none_no_provider_invoked",
        "measurement_scope": "fixture_deterministic_controls",
        "latency_status": "not_measured",
    }


def _deterministic_weight(evaluation: dict[str, Any]) -> float:
    weights = evaluation.get("weights")
    if not isinstance(weights, dict):
        return 1.0
    total = 0.0
    for metric in weights.values():
        if isinstance(metric, dict) and metric.get("type") == "deterministic":
            total += float(metric.get("weight", 0))
    return round(min(1.0, max(0.0, total)), 6)


def _protocol_evaluation(evaluation: dict[str, Any]) -> dict[str, Any]:
    return {
        **evaluation,
        "deterministic_weight": _deterministic_weight(evaluation),
    }


async def _evaluate_case(case: Case, repeat: int) -> dict[str, Any]:
    result = await evaluate(
        case.task,
        _json(case.output),
        provider=NoJudgeProvider(),
        model_id=FIXTURE_MODEL_ID,
        evaluation_profile="strict",
    )
    run_id = f"fixture_{case.family}_{case.control}_r{repeat}"
    return {
        "schema_version": "0.1",
        "run_id": run_id,
        "protocol_version": "0.1",
        "mode": "fixture",
        "task_family": case.family,
        "task_id": case.task.id,
        "scenario_id": f"{case.family}_{case.control}",
        "control": case.control,
        "expected_role": case.expected_role,
        "model_id": FIXTURE_MODEL_ID,
        "scaffold_id": case.scaffold,
        "evaluation_profile": "strict",
        "created_at": "2026-05-23T00:00:00Z",
        "output": case.output,
        "metrics": _fixture_metrics(),
        "evaluation": _protocol_evaluation(result),
        "evidence": [
            {
                "kind": "fixture_control",
                "summary": f"{case.expected_role} control for {case.family}: {case.control}",
            }
        ],
        "limitations": [
            "Fixture-mode artifact generated from deterministic controls, not a live provider run.",
            "No provider was invoked, so provider input tokens, output tokens, cost, and API calls are known to be none and recorded as zero.",
            "Fixture runtime latency was not measured; wall_time_ms is null.",
            "Timestamps are fixed fixture values for reproducibility, not observed execution times.",
            "Fixture scores are deterministic control outcomes, not model-performance evidence.",
            "Use live mode before making provider/model performance claims.",
        ],
    }


def _mean(values: list[float]) -> float:
    return sum(values) / max(1, len(values))


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def _confidence_interval_95(values: list[float]) -> dict[str, float]:
    mean = _mean(values)
    if len(values) < 2:
        return {"low": round(mean, 2), "high": round(mean, 2)}
    margin = 1.96 * _stdev(values) / math.sqrt(len(values))
    return {"low": round(mean - margin, 2), "high": round(mean + margin, 2)}


def _summarize(runs: list[dict[str, Any]]) -> dict[str, Any]:
    families = sorted({run["task_family"] for run in runs})
    by_family: dict[str, Any] = {}
    for family in families:
        family_runs = [run for run in runs if run["task_family"] == family]
        positive_scores = [
            float(run["evaluation"]["total_score"])
            for run in family_runs
            if run["expected_role"] == "positive"
        ]
        negative_scores = [
            float(run["evaluation"]["total_score"])
            for run in family_runs
            if run["expected_role"] == "negative"
        ]
        by_family[family] = {
            "runs": len(family_runs),
            "positive_mean": round(_mean(positive_scores), 2),
            "negative_mean": round(_mean(negative_scores), 2),
            "separation_points": round(_mean(positive_scores) - _mean(negative_scores), 2),
            "positive_ci95": _confidence_interval_95(positive_scores),
            "negative_ci95": _confidence_interval_95(negative_scores),
        }

    all_scores = [float(run["evaluation"]["total_score"]) for run in runs]
    return {
        "schema_version": "0.1",
        "mode": "fixture",
        "generated_at": "2026-05-23T00:00:00Z",
        "model_id": FIXTURE_MODEL_ID,
        "task_families": families,
        "scaffolds_or_ablation_labels": sorted({run["scaffold_id"] for run in runs}),
        "repeat_count": REPEATS,
        "run_count": len(runs),
        "score_mean": round(_mean(all_scores), 2),
        "score_stdev": round(_stdev(all_scores), 2),
        "score_ci95": _confidence_interval_95(all_scores),
        "by_family": by_family,
        "limitations": [
            "Fixture mode validates benchmark mechanics, baseline separation, and artifact generation.",
            "No provider was invoked: provider token, cost, and call fields are zero; latency was not measured.",
            "Timestamps are fixed fixture values for reproducibility, not observed execution times.",
            "Fixture scores are deterministic control outcomes, not model-performance evidence.",
            "This is not live provider evidence and does not remove the strict rubric live-run cap.",
        ],
    }


def _separation_report(summary: dict[str, Any]) -> dict[str, Any]:
    family_rows = []
    for family, row in summary["by_family"].items():
        family_rows.append(
            {
                "task_family": family,
                "positive_mean": row["positive_mean"],
                "negative_mean": row["negative_mean"],
                "separation_points": row["separation_points"],
                "passes_minimum": row["separation_points"] >= 20,
            }
        )
    return {
        "schema_version": "0.1",
        "mode": "fixture",
        "minimum_required_separation_points": 20,
        "all_families_pass": all(row["passes_minimum"] for row in family_rows),
        "families": family_rows,
        "limitations": [
            "Executed fixture controls are a calibration check, not a replacement for live model baselines.",
            "No provider usage or latency measurement is represented by these fixture controls.",
        ],
    }


def _render_markdown(summary: dict[str, Any], separation: dict[str, Any]) -> str:
    lines = [
        "# Benchmark Results v0.1",
        "",
        "This report is generated from deterministic fixture controls. It validates the benchmark runner, artifact format, repeated-trial aggregation, confidence-interval plumbing, and baseline separation mechanics. It is not a live provider benchmark.",
        "",
        "Fixture identity `fixture-no-provider-deterministic-v1` means no provider was invoked. Provider input tokens, output tokens, cost, and API calls are therefore known to be none and recorded as zero. `wall_time_ms` is `null` because fixture latency was not measured. Scores are deterministic control outcomes, not model-performance evidence.",
        "",
        "Timestamps are fixed fixture values for reproducibility, not observed execution times.",
        "",
        "## Summary",
        "",
        f"- Mode: `{summary['mode']}`",
        f"- Model id: `{summary['model_id']}`",
        f"- Runs: {summary['run_count']}",
        f"- Repeats per control: {summary['repeat_count']}",
        f"- Score mean: {summary['score_mean']}",
        f"- Score stdev: {summary['score_stdev']}",
        f"- 95% CI: {summary['score_ci95']['low']} to {summary['score_ci95']['high']}",
        "",
        "## Baseline Separation",
        "",
        "| Task family | Positive mean | Negative mean | Separation | Pass |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for row in separation["families"]:
        lines.append(
            f"| {row['task_family']} | {row['positive_mean']} | {row['negative_mean']} | "
            f"{row['separation_points']} | {'yes' if row['passes_minimum'] else 'no'} |"
        )

    lines.extend(
        [
            "",
            "## Claim Boundary",
            "",
            "- These are fixture controls, not live provider/model results.",
            "- The strict frontier rubric remains capped until live provider runs, scaffold ablations, human calibration, and independent reproduction exist.",
            "- A fixture separation pass means the scoring machinery can distinguish known-good and known-bad artifacts for these controls.",
        ]
    )
    return "\n".join(lines) + "\n"


async def run_fixture_mode() -> None:
    settings.enable_llm_judge = False
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    for old in RUN_DIR.glob("*.json"):
        old.unlink()

    runs: list[dict[str, Any]] = []
    for case in all_cases():
        for repeat in range(1, REPEATS + 1):
            artifact = await _evaluate_case(case, repeat)
            runs.append(artifact)
            (RUN_DIR / f"{artifact['run_id']}.json").write_text(json.dumps(artifact, indent=2) + "\n")

    summary = _summarize(runs)
    separation = _separation_report(summary)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2) + "\n")
    SEPARATION_PATH.write_text(json.dumps(separation, indent=2) + "\n")
    RESULTS_MD_PATH.write_text(_render_markdown(summary, separation))
    print(f"[benchmark-pack] wrote {len(runs)} fixture artifacts")
    print(f"[benchmark-pack] baseline separation pass={separation['all_families_pass']}")


async def _run_live_scaffold(
    *,
    task_family: str,
    task: Any,
    scaffold: Any,
    provider: Any,
    model_id: str,
    repeat: int,
    options: RunOptions,
) -> dict[str, Any]:
    run_id = f"live_{task_family}_{scaffold.id}_r{repeat}"
    start = time.time()
    total_input_tokens = 0
    total_output_tokens = 0
    api_calls = 0
    final_output = ""

    async for event_type, event_data in scaffold.run(
        run_id=run_id,
        task=task,
        model_id=model_id,
        provider=provider,
        options=options,
        config_override=None,
        cancelled_check=lambda: False,
    ):
        if event_type == "usage":
            total_input_tokens += int(event_data.get("input_tokens", 0))
            total_output_tokens += int(event_data.get("output_tokens", 0))
            api_calls += 1
        elif event_type == "final_output":
            final_output = str(event_data.get("output", ""))

    metrics = {
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "cost_usd": round(cost_usd(total_input_tokens, total_output_tokens, model_id), 6),
        "wall_time_ms": int((time.time() - start) * 1000),
        "num_api_calls": api_calls,
    }
    evaluation = await evaluate(
        task,
        final_output,
        provider=provider,
        model_id=model_id,
        evaluation_profile=options.evaluation_profile,
    )
    return {
        "schema_version": "0.1",
        "run_id": run_id,
        "protocol_version": "0.1",
        "mode": "live",
        "task_family": task_family,
        "task_id": task.id,
        "scenario_id": f"{task_family}_builtin",
        "model_id": model_id,
        "scaffold_id": scaffold.id,
        "evaluation_profile": options.evaluation_profile,
        "created_at": "2026-05-23T00:00:00Z",
        "output": final_output,
        "metrics": metrics,
        "evaluation": _protocol_evaluation(evaluation),
        "evidence": [
            {
                "kind": "live_provider_run",
                "summary": "Generated by scripts/run-benchmark-pack.py --mode live.",
            }
        ],
        "limitations": [
            "Single live run artifact; aggregate claims require repeated trials and the live summary.",
        ],
    }


def _summarize_live(runs: list[dict[str, Any]], model_id: str) -> dict[str, Any]:
    rows: dict[str, dict[str, Any]] = {}
    for run in runs:
        key = f"{run['task_family']}::{run['scaffold_id']}"
        rows.setdefault(key, {"scores": [], "costs": [], "task_family": run["task_family"], "scaffold_id": run["scaffold_id"]})
        rows[key]["scores"].append(float(run["evaluation"]["total_score"]))
        rows[key]["costs"].append(float(run["metrics"]["cost_usd"]))

    return {
        "schema_version": "0.1",
        "mode": "live",
        "generated_at": "2026-05-23T00:00:00Z",
        "model_id": model_id,
        "run_count": len(runs),
        "repeat_count": max((len(row["scores"]) for row in rows.values()), default=0),
        "results": [
            {
                "task_family": row["task_family"],
                "scaffold_id": row["scaffold_id"],
                "score_mean": round(_mean(row["scores"]), 2),
                "score_stdev": round(_stdev(row["scores"]), 2),
                "score_ci95": _confidence_interval_95(row["scores"]),
                "cost_mean": round(_mean(row["costs"]), 6),
            }
            for row in sorted(rows.values(), key=lambda item: (item["task_family"], item["scaffold_id"]))
        ],
        "limitations": [
            "Live results are model/provider/time specific.",
            "External validation and independent reproduction remain separate evidence requirements.",
        ],
    }


async def run_live_mode(
    *,
    model_id: str,
    task_ids: list[str],
    scaffold_ids: list[str],
    repeats: int,
    max_output_tokens: int,
) -> None:
    settings.enable_llm_judge = False
    tasks = task_pack()
    scaffolds = scaffold_pack()
    provider = get_provider(model_id)
    selected_tasks = [task_id for task_id in task_ids if task_id in tasks]
    selected_scaffolds = [scaffold_id for scaffold_id in scaffold_ids if scaffold_id in scaffolds]
    if not selected_tasks:
        raise ValueError(f"No valid task ids selected. Available: {sorted(tasks)}")
    if not selected_scaffolds:
        raise ValueError(f"No valid scaffold ids selected. Available: {sorted(scaffolds)}")

    LIVE_RUN_DIR.mkdir(parents=True, exist_ok=True)
    for old in LIVE_RUN_DIR.glob("*.json"):
        old.unlink()

    options = RunOptions(
        temperature=0,
        max_output_tokens=max_output_tokens,
        timeout_s=600,
        evaluation_profile="strict",
    )
    runs: list[dict[str, Any]] = []
    for repeat in range(1, repeats + 1):
        for task_id in selected_tasks:
            for scaffold_id in selected_scaffolds:
                artifact = await _run_live_scaffold(
                    task_family=task_id,
                    task=tasks[task_id],
                    scaffold=scaffolds[scaffold_id],
                    provider=provider,
                    model_id=model_id,
                    repeat=repeat,
                    options=options,
                )
                runs.append(artifact)
                (LIVE_RUN_DIR / f"{artifact['run_id']}.json").write_text(json.dumps(artifact, indent=2) + "\n")

    LIVE_SUMMARY_PATH.write_text(json.dumps(_summarize_live(runs, model_id), indent=2) + "\n")
    print(f"[benchmark-pack] wrote {len(runs)} live artifacts to {LIVE_RUN_DIR.relative_to(ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Scaffold Arena benchmark pack.")
    parser.add_argument("--mode", choices=["fixture", "live"], default="fixture")
    parser.add_argument("--model-id", default=LIVE_MODEL_ID)
    parser.add_argument("--tasks", default="extraction,risk,research,tool_use,privacy,strategy")
    parser.add_argument("--scaffolds", default="bare,plan_execute_verify,tool_error_recovery,memory_critique")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--max-output-tokens", type=int, default=2048)
    args = parser.parse_args()

    if args.mode == "live":
        asyncio.run(
            run_live_mode(
                model_id=args.model_id,
                task_ids=[item.strip() for item in args.tasks.split(",") if item.strip()],
                scaffold_ids=[item.strip() for item in args.scaffolds.split(",") if item.strip()],
                repeats=args.repeats,
                max_output_tokens=args.max_output_tokens,
            )
        )
        return 0

    asyncio.run(run_fixture_mode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
