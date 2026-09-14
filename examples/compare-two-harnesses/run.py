#!/usr/bin/env python3
"""Check whether the bundled fixture binds two distinct harnesses.

This example deliberately stops before comparison.  The bundled StudyPack has
one recorded harness, so emitting a winner, effect, cost, or latency would be
fabrication.  The checker reads JSON only and never imports or starts an
adapter, provider, worker, or network client.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PACK_PATH = ROOT / "study_packs" / "offline-demo-v1" / "study-pack.json"
TRUTH_TABLE_PATH = ROOT / "study_packs" / "offline-demo-v1" / "fixtures" / "runtime-truth-table.json"
CLAIM_CEILING = (
    "Synthetic recorded protocol admissibility only; no two-harness result, "
    "model comparison, performance effect, or causal claim."
)


def _digest(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _emit(report: dict[str, Any]) -> None:
    print(json.dumps(report, indent=2, sort_keys=True))


def _base_report() -> dict[str, Any]:
    return {
        "example_id": "compare-two-harnesses",
        "evidence_class": "fixture",
        "provider_execution_started": False,
        "execution_started": False,
        "network_requested": False,
        "claim_ceiling": CLAIM_CEILING,
        "source_digests": {
            "study_pack": _digest(PACK_PATH),
            "runtime_truth_table": _digest(TRUTH_TABLE_PATH),
        },
    }


def _hold(code: str, reason: str, *, harnesses: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    report = _base_report()
    report.update(
        {
            "verdict": "HOLD",
            "code": code,
            "reason": reason,
            "harnesses": harnesses or [],
            "comparison_emitted": False,
        }
    )
    return report


def _harness_bindings(pack: dict[str, Any]) -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    for item in pack.get("harnesses", []):
        if not isinstance(item, dict):
            continue
        bindings.append(
            {
                "harness_id": item.get("harness_id"),
                "adapter_identity": item.get("adapter_identity"),
                "adapter_digest": item.get("adapter_digest"),
                "execution_mode": item.get("execution_mode"),
                "claim_eligibility": item.get("claim_eligibility"),
                "source": "study_packs/offline-demo-v1/study-pack.json",
            }
        )
    return bindings


def run(output: str | Path) -> int:
    output_path = Path(output).expanduser()
    if output_path.exists():
        _emit(
            _hold(
                "output_exists",
                "Choose a new output path; this checker never overwrites an existing artifact.",
            )
        )
        return 2

    try:
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        if not isinstance(pack, dict):
            raise ValueError("StudyPack must be an object")
        harnesses = _harness_bindings(pack)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        report = _hold(
            "fixture_input_invalid",
            "The pinned StudyPack or truth-table input cannot be validated; comparison is blocked.",
        )
        _emit(report)
        return 2

    distinct = {
        (item["harness_id"], item["adapter_identity"], item["adapter_digest"])
        for item in harnesses
        if item["harness_id"] and item["adapter_identity"] and item["adapter_digest"]
    }
    report: dict[str, Any]
    if len(distinct) < 2:
        report = _hold(
            "second_checked_harness_not_supplied",
            "The bundled StudyPack binds one recorded harness; a second independently declared checked harness is required before any comparison.",
            harnesses=harnesses,
        )
    elif any(
        item["execution_mode"] != "recorded" or item["claim_eligibility"] != "fixture_only"
        for item in harnesses
    ):
        report = _hold(
            "harness_claim_boundary_invalid",
            "Only independently declared recorded fixture harnesses may enter this provider-free admissibility check.",
            harnesses=harnesses,
        )
    else:
        report = _base_report()
        report.update(
            {
                "verdict": "PASS",
                "code": "two_recorded_harnesses_bound",
                "reason": "Two distinct recorded fixture harness identities are bound; no outcome comparison is emitted by this protocol-only checker.",
                "harnesses": harnesses,
                "comparison_emitted": False,
            }
        )

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        _emit(
            _hold(
                "output_unwritable",
                "The requested output path is not writable; no comparison artifact was produced.",
                harnesses=report.get("harnesses", []),
            )
        )
        return 2
    _emit(report)
    return 0 if report["verdict"] == "PASS" else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="new JSON output path")
    args = parser.parse_args(argv)
    return run(args.output)


if __name__ == "__main__":
    raise SystemExit(main())
