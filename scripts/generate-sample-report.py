#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "docs/benchmarking/sample_release_report.md"
RUN_ARTIFACT_PATH = ROOT / "docs/benchmarking/sample_run_artifact.json"


def build_report() -> str:
    artifact = json.loads(RUN_ARTIFACT_PATH.read_text())
    metrics = artifact["metrics"]
    evaluation = artifact["evaluation"]
    total_tokens = int(metrics["input_tokens"] + metrics["output_tokens"])
    deterministic_pct = int(round(evaluation["deterministic_weight"] * 100))

    lines = [
        "# Protocol schema example report",
        "",
        "This report is generated from static fixture inputs to demonstrate the protocol schema. Its scores, token counts, and cost are illustrative fields, not measured benchmark or provider results.",
        "",
        "## Inputs",
        "",
        f"- Protocol version: {artifact['protocol_version']}",
        f"- Scenario: `{artifact['scenario_id']}`",
        f"- Scaffold: `{artifact['scaffold_id']}`",
        f"- Model: `{artifact['model_id']}`",
        "- Artifact: `docs/benchmarking/sample_run_artifact.json`",
        "",
        "## Illustrative fixture fields",
        "",
        f"- Total score: {evaluation['total_score']}",
        f"- Deterministic weight: {deterministic_pct} percent",
        f"- Token usage: {total_tokens:,} total tokens",
        f"- Cost: ${metrics['cost_usd']:.3f}",
        "",
        "## Evidence",
        "",
        "- The sample run artifact validates against `specs/run-artifact.schema.json`.",
        "- The sample eval card validates against `specs/eval-card.schema.json`.",
        "- The sample scaffold card validates against `specs/scaffold-card.schema.json`.",
        "",
        "## Claim Boundary",
        "",
        "This report only demonstrates that the protocol artifact shape is inspectable and valid. It does not prove live provider performance, measured cost, or a benchmark result.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the sample Scaffold Arena release report.")
    parser.add_argument("--check", action="store_true", help="Fail if the checked-in sample report is stale.")
    args = parser.parse_args()

    report = build_report()
    if args.check:
        current = REPORT_PATH.read_text() if REPORT_PATH.exists() else ""
        if current != report:
            print("[sample-report] FAIL: docs/benchmarking/sample_release_report.md is stale", file=sys.stderr)
            return 1
        print("[sample-report] checked sample release report")
        return 0

    REPORT_PATH.write_text(report)
    print(f"[sample-report] wrote {REPORT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
