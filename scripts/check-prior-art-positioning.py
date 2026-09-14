#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = ROOT / "docs/benchmarking/comparison_to_existing_tools.md"
OUTPUT_PATH = ROOT / "outputs/prior_art_positioning_audit.json"

TOOLS = [
    {
        "name": "promptfoo",
        "category": "Prompt, model, RAG, and application evaluation plus red teaming",
        "source_url": "https://www.promptfoo.dev/docs/intro/",
        "source_summary": "Official docs describe promptfoo as an open-source CLI/library for evaluating and red-teaming LLM apps, including prompts, models, RAGs, metrics, CI, and provider integrations.",
        "scaffold_arena_overlap": "Both can compare outputs across configurations and providers.",
        "scaffold_arena_boundary": "Scaffold Arena does not claim to replace promptfoo; it narrows the unit under test to scaffold/orchestration choices under a fixed model and emits scaffold-specific run artifacts.",
        "reviewer_question": "Does the protocol isolate scaffold effects rather than prompt/provider matrix effects?",
    },
    {
        "name": "Inspect",
        "category": "General LLM, agent, tool, and frontier evaluation framework",
        "source_url": "https://inspect.aisi.org.uk/",
        "source_summary": "Official docs describe Inspect as an open-source framework for broad LLM evaluations with datasets, solvers, scorers, agents, tools, logs, and many pre-built evals.",
        "scaffold_arena_overlap": "Both model evaluations as tasks plus execution strategies plus scoring.",
        "scaffold_arena_boundary": "Scaffold Arena does not claim to replace Inspect; it can be read as a narrower scaffold-effect protocol with explicit same-model comparisons and product-facing trace evidence.",
        "reviewer_question": "Could the Scaffold Arena task pack be ported to Inspect while preserving the same scaffold-effect claim?",
    },
    {
        "name": "OpenAI Evals",
        "category": "Model and system evaluation workflow",
        "source_url": "https://developers.openai.com/api/docs/guides/evals",
        "source_summary": "Official docs present evals as an OpenAI API evaluation workflow for datasets, graders, experiments, and model/system assessment.",
        "scaffold_arena_overlap": "Both emphasize repeatable evaluation datasets, graders, and result comparison.",
        "scaffold_arena_boundary": "Scaffold Arena does not claim to replace OpenAI Evals; it focuses on scaffold cards, trace audit, cost/latency evidence, and same-model scaffold decomposition.",
        "reviewer_question": "Does the benchmark produce artifact-level evidence beyond a grader score?",
    },
    {
        "name": "LangSmith",
        "category": "Offline/online application evaluation, observability, experiments, and human feedback",
        "source_url": "https://docs.langchain.com/langsmith/evaluation",
        "source_summary": "Official docs describe LangSmith evaluation as offline curated-dataset experiments and online production monitoring, with datasets, evaluators, repetitions, experiments, annotation, and feedback workflows.",
        "scaffold_arena_overlap": "Both can compare experiments and use traces or annotations as evidence.",
        "scaffold_arena_boundary": "Scaffold Arena does not claim to replace LangSmith; it uses a local benchmark protocol to test scaffold alternatives rather than production observability or hosted experiment management.",
        "reviewer_question": "Does this release distinguish local fixture integrity from production monitoring and adoption evidence?",
    },
    {
        "name": "LangGraph",
        "category": "Agent orchestration runtime and framework",
        "source_url": "https://docs.langchain.com/oss/python/langgraph/overview",
        "source_summary": "Official docs describe LangGraph as a low-level orchestration framework/runtime for long-running, stateful agents with durable execution, streaming, human-in-the-loop, and persistence.",
        "scaffold_arena_overlap": "Both care about orchestration patterns, tool use, memory, and human-in-the-loop behavior.",
        "scaffold_arena_boundary": "Scaffold Arena does not claim to replace LangGraph; LangGraph helps build agents, while Scaffold Arena evaluates scaffold behavior and failure profiles.",
        "reviewer_question": "Could a LangGraph implementation be submitted as one scaffold variant under the same protocol?",
    },
]


def _dump_json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, sort_keys=False) + "\n"


def _is_https_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


def build_audit() -> dict[str, Any]:
    return {
        "schema_version": "0.1",
        "generated_at": "2026-06-01T00:00:00Z",
        "status": "source_backed_prior_art_positioning_not_external_validation",
        "source_checked_at": "2026-06-01",
        "comparison_doc": "docs/benchmarking/comparison_to_existing_tools.md",
        "official_source_count": len(TOOLS),
        "tools": TOOLS,
        "required_boundaries": [
            "Scaffold Arena does not claim to replace existing eval, observability, or orchestration tools.",
            "The comparison is positioning evidence, not external validation evidence.",
            "Live benchmark claims still require live provider artifacts and independent reproduction.",
        ],
        "claim_boundary": (
            "This audit checks whether the prior-art comparison is sourced and bounded. It is not "
            "external validation evidence, not adoption evidence, and not proof of field influence."
        ),
    }


def _validate_doc(audit: dict[str, Any]) -> list[str]:
    text = DOC_PATH.read_text()
    errors: list[str] = []
    for tool in audit["tools"]:
        for required in [tool["name"], tool["source_url"], tool["scaffold_arena_boundary"]]:
            if required not in text:
                errors.append(f"comparison doc missing {tool['name']} required text: {required}")
    for phrase in audit["required_boundaries"]:
        if phrase not in text:
            errors.append(f"comparison doc missing boundary phrase: {phrase}")
    return errors


def _validate_audit(audit: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if audit.get("status") != "source_backed_prior_art_positioning_not_external_validation":
        errors.append("prior-art audit status is invalid")
    tools = audit.get("tools", [])
    if len(tools) < 5:
        errors.append("prior-art audit must cover at least five adjacent tools")
    for tool in tools:
        if not _is_https_url(str(tool.get("source_url", ""))):
            errors.append(f"{tool.get('name')}: source_url must be https")
        boundary = str(tool.get("scaffold_arena_boundary", "")).lower()
        if "does not claim to replace" not in boundary:
            errors.append(f"{tool.get('name')}: boundary must state non-replacement")
    text = json.dumps(audit).lower()
    for phrase in ["not external validation evidence", "not adoption evidence", "not proof of field influence"]:
        if phrase not in text:
            errors.append(f"prior-art audit missing claim-boundary phrase: {phrase}")
    return errors


def _check_file() -> list[str]:
    expected = _dump_json(build_audit())
    current = OUTPUT_PATH.read_text() if OUTPUT_PATH.exists() else ""
    if current != expected:
        return [f"{OUTPUT_PATH.relative_to(ROOT)} is stale"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or check source-backed prior-art positioning.")
    parser.add_argument("--write", action="store_true", help="Write outputs/prior_art_positioning_audit.json.")
    parser.add_argument("--check", action="store_true", help="Fail if the prior-art audit is stale.")
    args = parser.parse_args()

    audit = build_audit()
    if args.write:
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(_dump_json(audit))
        print(f"[prior-art] wrote {OUTPUT_PATH.relative_to(ROOT)}")
        return 0

    errors = _validate_audit(audit)
    errors.extend(_validate_doc(audit))
    if args.check:
        errors.extend(_check_file())
    if errors:
        for error in errors:
            print(f"[prior-art] FAIL: {error}", file=sys.stderr)
        return 1
    print(f"[prior-art] checked {audit['official_source_count']} source-backed comparisons")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
