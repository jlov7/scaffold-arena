#!/usr/bin/env python3
"""Scan pre-approved UTF-8 repository files without echoing matched values."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path, PurePosixPath


def safe_path(value: str) -> str | None:
    if not value or "\0" in value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        return None
    return value


def scan(root: Path, pattern: re.Pattern[str], paths: list[str]) -> list[str]:
    hits: list[str] = []
    for relative in paths:
        safe_relative = safe_path(relative)
        if safe_relative is None:
            raise ValueError("unsafe path supplied to content scanner")
        path = root / safe_relative
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"non-regular file supplied to content scanner: {safe_relative}")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                hits.append(f"{safe_relative}:{line_number}")
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan allowed UTF-8 files for secret patterns.")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--pattern", required=True)
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve(strict=True)
        pattern = re.compile(args.pattern)
        raw_paths = sys.stdin.buffer.read().split(b"\0")
        paths = [item.decode("utf-8") for item in raw_paths if item]
        for hit in scan(root, pattern, paths):
            print(hit)
    except (OSError, UnicodeDecodeError, ValueError, re.error) as exc:
        print(f"[scan-secrets] FAIL: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
