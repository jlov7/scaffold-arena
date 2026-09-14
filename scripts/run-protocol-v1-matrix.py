"""Create an offline Protocol-v1 fixture matrix bundle; never calls a runtime."""

from __future__ import annotations

import argparse
from pathlib import Path

from protocol_v1.scientific_completion import (
    ConfirmatoryHold,
    load_scientific_study,
    write_fixture_bundle,
)

ROOT = Path(__file__).resolve().parents[1]
_STUDIES = {
    "flagship-prereg-v1": ROOT / "study_packs/flagship-prereg-v1/fixtures/scientific-study.json",
    "transfer-prereg-v1": ROOT / "study_packs/transfer-prereg-v1/fixtures/scientific-study.json",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", choices=sorted(_STUDIES), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("fixture", "confirmatory"), default="fixture")
    args = parser.parse_args()
    try:
        written = write_fixture_bundle(load_scientific_study(_STUDIES[args.study]), args.output, mode=args.mode)
    except ConfirmatoryHold as exc:
        parser.error(f"HOLD_PREREGISTRATION_NOT_PUBLIC_IMMUTABLE: {exc}")
    except FileExistsError as exc:
        parser.error(str(exc))
    print(f"[protocol-v1-matrix] fixture bundle: {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
