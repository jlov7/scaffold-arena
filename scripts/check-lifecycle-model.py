#!/usr/bin/env python3
"""Deterministically run the bounded invocation/reservation safety model."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from execution_v1.formal_model import InvariantViolation, verify_bounded_lifecycle  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check the bounded invocation/reservation lifecycle model."
    )
    parser.add_argument("--depth", type=int, default=8)
    parser.add_argument("--generations", type=int, default=2)
    args = parser.parse_args()
    try:
        report = verify_bounded_lifecycle(
            max_depth=args.depth,
            max_generations=args.generations,
        )
    except (InvariantViolation, ValueError) as exc:
        print(f"[lifecycle-model] FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": "pass",
                "claim_ceiling": "bounded engineering model only; not production, security, causal, or independent assurance",
                "max_depth": report.max_depth,
                "max_generations": report.max_generations,
                "states_checked": report.states_checked,
                "transitions_checked": report.transitions_checked,
                "invariants": report.invariants,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
