#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]

APPROVED_ROOT_ENTRIES = {
    ".dockerignore",
    ".env.example",
    ".gitignore",
    "AGENTS.md",
    "CHANGELOG.md",
    "CITATION.cff",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "Dockerfile",
    "LICENSE",
    "MAINTAINERS.md",
    "README.md",
    "SECURITY.md",
    "SUPPORT.md",
    "compose.integration-test.yml",
    "compose.postgres-test.yml",
    "docker-compose.yml",
    "railway.toml",
}
REQUIRED_PUBLIC_DOCUMENTS = {
    "CHANGELOG.md",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "SECURITY.md",
    "docs/README.md",
    "docs/concepts/harness-stack.md",
    "docs/concepts/product-contract.md",
    "docs/design-system.md",
    "docs/evidence-status.md",
    "docs/reviews/external-validation-ledger.md",
}
REQUIRED_CONTENT = {
    "frontend/index.html": (
        'href="https://scaffold-arena.vercel.app/"',
        'content="https://scaffold-arena.vercel.app/"',
        'content="https://scaffold-arena.vercel.app/og-image.png"',
        'property="og:image:alt"',
        'name="twitter:image:alt"',
        "AI Harness Engineering",
        "evidence",
    ),
}
FORBIDDEN_PATH_PARTS = {".codex", ".cursor", ".claude", ".superpowers", "superpowers"}
FORBIDDEN_PATH_WORDS = ("handover", "scratch", "tribunal")
FORBIDDEN_PRIVATE_PATHS = {
    "specs/trace-driven-frontier-audit_plan.md",
}
TEXT_SUFFIXES = {".env", ".html", ".json", ".md", ".rst", ".toml", ".txt", ".yaml", ".yml"}
PERSONAL_EMAILS = {"jase.lovell" + "@" + "me.com"}
LOCAL_REFERENCE_PATTERNS = (
    re.compile("sandbox:" + r"/[^\s`'\")<>]+", re.IGNORECASE),
    re.compile(r"/mnt" + r"/data/[^\s`'\")<>]+", re.IGNORECASE),
    re.compile(r"/private" + r"/tmp/[^\s`'\")<>]+"),
    re.compile(r"/var" + r"/folders/[^\s`'\")<>]+"),
    re.compile(r"/(?:Users|home)/[^\s`'\")<>]+"),
    re.compile(r"[A-Za-z]:[\\/]+Users[\\/][^\s`'\")<>]+"),
)
PUBLIC_CONTENT_DENY_PATTERNS = (
    ("placeholder production URL", re.compile(r"scaffold-arena\.example", re.IGNORECASE)),
    ("unsupported live-win claim", re.compile(r"prove orchestration wins", re.IGNORECASE)),
    ("unsupported live-run claim", re.compile(r"live arena runs", re.IGNORECASE)),
)
SECRET_CONTENT_PATTERNS = (
    re.compile(r"-----BEGIN (?:(?:RSA|EC|OPENSSH) )?PRIVATE KEY-----"),
    re.compile(r"\b(?:ghp|gho)_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)
SECRET_FILE_PATTERN = re.compile(
    r"(?:^|/)(?:\.env(?:$|[./])|id_rsa(?:$|/)|credentials(?:$|/))|\.(?:key|pem)$",
    re.IGNORECASE,
)
FIXTURE_LIVE_ESCALATION = re.compile(
    r"\bfixture(?:s|\s+evidence|\s+results?|\s+study)?\b.{0,80}\b"
    r"(?:proves?|demonstrates?|establishes?|validates?)\b.{0,80}\b"
    r"(?:live|production|human-calibrated|independent)\b",
    re.IGNORECASE,
)
TMP_EXAMPLE = re.compile(r"/" + r"tmp/scaffold-arena-[A-Za-z0-9_.-]+")
# This fixture deliberately contains a machine-local path so the scanner's
# regression test can exercise its narrow exception. Other tests and code are
# scanned normally.
LOCAL_REFERENCE_FIXTURE_PATHS = {
    "scripts/tests/fixtures/public_hygiene/allowed-machine-local-reference.txt",
}


def tracked_paths(root: Path) -> list[str]:
    tracked = _git_paths(root, ["--cached"])
    untracked = _git_paths(root, ["--others", "--exclude-standard"])
    deleted = _git_paths(root, ["--deleted"])
    return sorted((tracked | untracked) - deleted)


def _git_paths(root: Path, arguments: list[str]) -> set[str]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", *arguments],
        check=False,
        capture_output=True,
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"could not list tracked files: {detail}")
    return {path for path in result.stdout.decode("utf-8").split("\0") if path}


def audit(root: Path | str, paths: list[str]) -> list[str]:
    root = Path(root).resolve()
    errors: list[str] = []
    path_set = set(paths)
    for required in sorted(REQUIRED_PUBLIC_DOCUMENTS - path_set):
        errors.append(f"missing required public document: {required}")

    for relative_path in sorted(path_set):
        errors.extend(_path_errors(root, relative_path))
    errors.extend(scan_public_content(root, sorted(path_set)))
    errors.extend(_required_content_errors(root, path_set))
    return errors


def scan_public_content(root: Path | str, paths: list[str]) -> list[str]:
    """Apply public-content policy without requiring a complete repository tree."""

    root = Path(root).resolve()
    errors: list[str] = []
    for relative_path in sorted(set(paths)):
        errors.extend(_content_errors(root, relative_path))
    return errors


def _path_errors(root: Path, relative_path: str) -> list[str]:
    errors: list[str] = []
    path = PurePosixPath(relative_path)
    if path.is_absolute() or ".." in path.parts or "\\" in relative_path:
        return [f"invalid tracked path: {relative_path}"]
    absolute = root / path
    parts = set(path.parts)
    if parts & FORBIDDEN_PATH_PARTS or any(word in path.name.lower() for word in FORBIDDEN_PATH_WORDS):
        errors.append(f"forbidden private or agent path: {relative_path}")
    if relative_path in FORBIDDEN_PRIVATE_PATHS:
        errors.append(f"forbidden private planning path: {relative_path}")
    if len(path.parts) == 1 and relative_path not in APPROVED_ROOT_ENTRIES:
        errors.append(f"unapproved root entry: {relative_path}")
    if SECRET_FILE_PATTERN.search(relative_path) and path.name != ".env.example":
        errors.append(f"secret or credential filename: {relative_path}")
    if absolute.is_symlink():
        errors.append(f"tracked symlink: {relative_path}")
    if not absolute.exists() and not absolute.is_symlink():
        errors.append(f"tracked path is missing: {relative_path}")
    return errors


def _content_errors(root: Path, relative_path: str) -> list[str]:
    path = root / relative_path
    if path.is_symlink() or not path.is_file() or _skip_sensitive_content(relative_path):
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        if path.suffix.lower() in TEXT_SUFFIXES:
            return [f"non-UTF-8 public text file: {relative_path}"]
        return []

    public_text = path.suffix.lower() in TEXT_SUFFIXES
    errors = (
        [
            f"{relative_path}: contains {label}"
            for label, pattern in PUBLIC_CONTENT_DENY_PATTERNS
            if pattern.search(text)
        ]
        if public_text
        else []
    )
    for line_number, line in enumerate(text.splitlines(), start=1):
        for pattern in SECRET_CONTENT_PATTERNS:
            if pattern.search(line):
                errors.append(f"secret-like content: {relative_path}:{line_number}")
        if any(email in line.lower() for email in PERSONAL_EMAILS):
            errors.append(f"personal email literal: {relative_path}:{line_number}")
        if relative_path not in LOCAL_REFERENCE_FIXTURE_PATHS:
            errors.extend(_local_reference_errors(relative_path, line_number, line))
        if path.suffix.lower() in {".md", ".rst", ".txt"}:
            errors.extend(_temporary_path_errors(relative_path, line_number, line))
            if FIXTURE_LIVE_ESCALATION.search(line) and not _is_negated_fixture_claim(line):
                errors.append(f"fixture-to-live claim escalation: {relative_path}:{line_number}")
    return errors


def _skip_sensitive_content(relative_path: str) -> bool:
    """Do not inspect environment or credential files for publication text."""

    name = PurePosixPath(relative_path).name.lower()
    if name == ".env.example":
        return False
    return name == ".env" or name.startswith(".env.") or bool(SECRET_FILE_PATTERN.search(relative_path))


def _required_content_errors(root: Path, path_set: set[str]) -> list[str]:
    errors: list[str] = []
    for relative_path, markers in REQUIRED_CONTENT.items():
        if relative_path not in path_set:
            errors.append(f"missing required public surface: {relative_path}")
            continue
        path = root / relative_path
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            errors.append(f"could not verify required public surface: {relative_path}")
            continue
        for marker in markers:
            if marker not in text:
                errors.append(f"{relative_path}: missing required public marker: {marker}")
    return errors


def _local_reference_errors(relative_path: str, line_number: int, line: str) -> list[str]:
    errors: list[str] = []
    for pattern in LOCAL_REFERENCE_PATTERNS:
        if pattern.search(line):
            errors.append(f"machine-local reference: {relative_path}:{line_number}")
    return errors


def _temporary_path_errors(relative_path: str, line_number: int, line: str) -> list[str]:
    errors: list[str] = []
    for match in re.finditer(r"/" + r"tmp/[^\s`'\")<>]+", line):
        value = match.group(0)
        if TMP_EXAMPLE.match(value):
            continue
        errors.append(f"machine-local temporary path: {relative_path}:{line_number}")
    return errors


def _is_negated_fixture_claim(line: str) -> bool:
    return bool(
        re.search(
            r"\b(?:does|do|did)\s+not\s+"
            r"(?:prove|demonstrate|establish|validate)",
            line,
            re.IGNORECASE,
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail closed on public repository hygiene violations.")
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root to audit")
    args = parser.parse_args(argv)
    try:
        errors = audit(args.root, tracked_paths(args.root))
    except RuntimeError as exc:
        print(f"[public-hygiene] FAIL: {exc}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"[public-hygiene] FAIL: {error}", file=sys.stderr)
        return 1
    print("[public-hygiene] PASS: tracked public tree meets hygiene policy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
