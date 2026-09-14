"""Standalone provider-free CLI for frozen prospective analysis plans."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from analysis_v1 import assess_analysis_plan
from protocol_v1 import ExperimentSpec

_HOLD = 2


def _emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, default=str, sort_keys=True))


def assess_file(path: str | Path) -> tuple[int, dict[str, Any]]:
    try:
        spec = ExperimentSpec.model_validate_json(Path(path).read_bytes())
    except (OSError, TypeError, ValueError):
        return _HOLD, {
            "assessment": None,
            "code": "invalid_analysis_plan_request",
            "provider_execution_started": False,
            "verdict": "HOLD",
        }

    assessment = assess_analysis_plan(spec)
    verdict = "PASS" if assessment.status == "PASS" else "HOLD"
    return (0 if verdict == "PASS" else _HOLD), {
        "assessment": assessment.model_dump(mode="json"),
        "experiment_id": spec.experiment_id,
        "provider_execution_started": False,
        "verdict": verdict,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m arena_cli.analysis_plan",
        description=(
            "Assess a frozen binary-outcome analysis plan without starting a provider"
        ),
    )
    parser.add_argument("--spec", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    code, payload = assess_file(args.spec)
    _emit(payload)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
