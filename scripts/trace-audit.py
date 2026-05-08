#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from audit.trace_audit import audit_records, load_stored_run_records, load_trace_records, render_markdown_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit Scaffold Arena saved run traces.")
    parser.add_argument(
        "--input",
        action="append",
        type=Path,
        help="JSON run record, list of run records, or object with a runs list. May be repeated.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional Markdown output path. If omitted, the report is printed to stdout.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Number of stored SQLite runs to audit when --input is omitted.",
    )
    args = parser.parse_args(argv)

    records: list[dict] = []
    if args.input:
        for input_path in args.input:
            records.extend(load_trace_records(input_path))
    else:
        records = load_stored_run_records(limit=args.limit)

    report = audit_records(records)
    markdown = render_markdown_report(report)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(markdown)
        print(
            f"Trace audit wrote {report.finding_count} findings "
            f"across {report.run_count} runs to {args.output}"
        )
    else:
        print(markdown)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
