from __future__ import annotations

from utils.json_extract import parse_json_lenient


def test_parse_json_lenient_direct_parse() -> None:
    result = parse_json_lenient('{"a": 1}')
    assert result.ok is True
    assert result.data == {"a": 1}


def test_parse_json_lenient_code_fence_parse() -> None:
    result = parse_json_lenient('```json\n{"a": 2}\n```')
    assert result.ok is True
    assert result.data == {"a": 2}
    assert "stripping code fences" in " ".join(result.notes).lower()


def test_parse_json_lenient_brace_scan_parse() -> None:
    result = parse_json_lenient('noise {"a": 3} trailing')
    assert result.ok is True
    assert result.data == {"a": 3}
    assert "brace" in " ".join(result.notes).lower()


def test_parse_json_lenient_brace_scan_on_defenced_text() -> None:
    payload = "```json\nprefix {\"a\": 4} suffix\n```"
    result = parse_json_lenient(payload)
    assert result.ok is True
    assert result.data == {"a": 4}


def test_parse_json_lenient_empty_input() -> None:
    result = parse_json_lenient("   ")
    assert result.ok is False
    assert result.error == "Empty input"


def test_parse_json_lenient_all_strategies_fail() -> None:
    result = parse_json_lenient("not json at all")
    assert result.ok is False
    assert result.error == "Could not extract valid JSON"
