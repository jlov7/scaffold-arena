"""Robust JSON extraction from LLM output."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field


@dataclass
class ParseResult:
    ok: bool
    data: dict | None = None
    extracted_json: str | None = None
    error: str | None = None
    notes: list[str] = field(default_factory=list)


def strip_code_fences(text: str) -> str:
    """Remove markdown code fences (```json ... ``` or ``` ... ```)."""
    # Match ```json\n...\n``` or ```\n...\n```
    pattern = r"```(?:json)?\s*\n?(.*?)\n?\s*```"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def extract_first_json_object(text: str) -> str | None:
    """Extract the first balanced JSON object from text using brace scanning."""
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape_next = False

    for i in range(start, len(text)):
        ch = text[i]

        if escape_next:
            escape_next = False
            continue

        if ch == "\\":
            if in_string:
                escape_next = True
            continue

        if ch == '"' and not escape_next:
            in_string = not in_string
            continue

        if in_string:
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]

    return None


def parse_json_lenient(text: str) -> ParseResult:
    """Parse JSON from LLM output with multiple fallback strategies."""
    notes: list[str] = []

    if not text or not text.strip():
        return ParseResult(ok=False, error="Empty input", notes=["Input was empty"])

    # Strategy 1: Try direct parse
    stripped = text.strip()
    try:
        data = json.loads(stripped)
        if isinstance(data, dict):
            return ParseResult(ok=True, data=data, extracted_json=stripped)
    except json.JSONDecodeError:
        notes.append("Direct parse failed")

    # Strategy 2: Strip code fences then parse
    defenced = strip_code_fences(text)
    try:
        data = json.loads(defenced)
        if isinstance(data, dict):
            notes.append("Parsed after stripping code fences")
            return ParseResult(ok=True, data=data, extracted_json=defenced, notes=notes)
    except json.JSONDecodeError:
        notes.append("Fence-stripped parse failed")

    # Strategy 3: Extract first JSON object via brace scanning
    extracted = extract_first_json_object(text)
    if extracted:
        try:
            data = json.loads(extracted)
            if isinstance(data, dict):
                notes.append("Extracted via balanced brace scan")
                return ParseResult(
                    ok=True, data=data, extracted_json=extracted, notes=notes
                )
        except json.JSONDecodeError:
            notes.append("Brace-scan extraction found JSON but it was invalid")

    # Strategy 4: Try brace scan on defenced text
    extracted = extract_first_json_object(defenced)
    if extracted:
        try:
            data = json.loads(extracted)
            if isinstance(data, dict):
                notes.append("Extracted via brace scan on defenced text")
                return ParseResult(
                    ok=True, data=data, extracted_json=extracted, notes=notes
                )
        except json.JSONDecodeError:
            pass

    notes.append("All parse strategies failed")
    return ParseResult(ok=False, error="Could not extract valid JSON", notes=notes)
