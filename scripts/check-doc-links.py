#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def _markdown_files() -> list[Path]:
    roots = [
        *sorted(ROOT.glob("*.md")),
        *sorted((ROOT / "docs").rglob("*.md")),
        *sorted((ROOT / "examples").rglob("*.md")),
        *sorted((ROOT / "study_packs").rglob("*.md")),
        ROOT / "backend/README.md",
        ROOT / "frontend/README.md",
    ]
    return sorted({path for path in roots if path.is_file()})


def _is_external(target: str) -> bool:
    return (
        target.startswith("http://")
        or target.startswith("https://")
        or target.startswith("mailto:")
        or target.startswith("#")
        or target.startswith("app://")
    )


def main() -> int:
    errors: list[str] = []
    for path in _markdown_files():
        text = path.read_text()
        for match in LINK_RE.finditer(text):
            raw_target = match.group(1).strip()
            if _is_external(raw_target):
                continue
            clean_target = raw_target.split("#", 1)[0]
            if not clean_target:
                continue
            candidate = (path.parent / clean_target).resolve()
            try:
                candidate.relative_to(ROOT)
            except ValueError:
                errors.append(f"{path.relative_to(ROOT)}: link escapes repo: {raw_target}")
                continue
            if not candidate.exists():
                errors.append(f"{path.relative_to(ROOT)}: missing link target: {raw_target}")

    if errors:
        for error in errors:
            print(f"[docs] FAIL: {error}", file=sys.stderr)
        return 1
    print(f"[docs] checked {len(_markdown_files())} markdown files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
