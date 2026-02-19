"""Deterministic scoring functions (≥70% of total weight)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import jsonschema

from utils.json_extract import parse_json_lenient
from utils.text import fuzzy_similarity


@dataclass
class MetricResult:
    name: str
    score: float  # 0-100
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# C1. schema_validity
# ---------------------------------------------------------------------------

def schema_validity(raw_output: str, schema: dict) -> MetricResult:
    """Validate LLM output against a JSON schema."""
    result = parse_json_lenient(raw_output)
    if not result.ok:
        return MetricResult(name="schema_validity", score=0.0, notes=["JSON parse failed"])

    try:
        jsonschema.validate(instance=result.data, schema=schema)
        return MetricResult(name="schema_validity", score=100.0, notes=["Schema fully valid"])
    except jsonschema.ValidationError:
        pass
    except jsonschema.SchemaError as e:
        return MetricResult(name="schema_validity", score=0.0, notes=[f"Invalid schema: {e.message}"])

    # Collect all validation errors
    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(result.data))

    # Count required fields from schema
    required_fields = schema.get("required", list(schema.get("properties", {}).keys()))
    R = max(1, len(required_fields))

    missing_required = 0
    type_mismatches = 0
    error_notes: list[str] = []

    for err in errors:
        if err.validator == "required":
            missing_required += 1
            error_notes.append(f"Missing required field: {err.message}")
        elif err.validator == "type":
            type_mismatches += 1
            error_notes.append(f"Type mismatch: {err.message}")
        else:
            error_notes.append(f"Validation error: {err.message}")

    score = max(0.0, 100.0 * (1 - missing_required / R) - 10.0 * type_mismatches)
    score = min(99.0, score)  # Never 100 if schema errors exist
    score = max(0.0, score)

    return MetricResult(name="schema_validity", score=score, notes=error_notes)


# ---------------------------------------------------------------------------
# C2. field_accuracy
# ---------------------------------------------------------------------------

_GOLD_KEYS = [
    "document_type",
    "effective_date",
    "references_agreement.date",
    "new_expiration_date",
    "financial_summary.monthly_retainer_old",
    "financial_summary.monthly_retainer_new",
    "financial_summary.insurance_minimum",
]


def _get_nested(data: dict, dotted_key: str):
    """Traverse a dict using a dot-separated key path."""
    parts = dotted_key.split(".")
    current = data
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _field_score(predicted, gold) -> float:
    """Return a similarity score 0-1 for a single field."""
    if predicted is None or gold is None:
        return 0.0

    # Exact match
    if predicted == gold:
        return 1.0

    # Case-insensitive string match
    if isinstance(predicted, str) and isinstance(gold, str):
        if predicted.lower() == gold.lower():
            return 0.95

    # Numeric within 1%
    try:
        p_float = float(predicted)
        g_float = float(gold)
        if g_float == 0:
            if p_float == 0:
                return 1.0
        elif abs(p_float - g_float) / abs(g_float) <= 0.01:
            return 0.9
    except (TypeError, ValueError):
        pass

    # Fuzzy string similarity
    if isinstance(predicted, str) and isinstance(gold, str):
        sim = fuzzy_similarity(predicted, gold)
        if sim >= 0.85:
            return 0.75

    return 0.0


def field_accuracy(raw_output: str, gold: dict) -> MetricResult:
    """Compare specific gold fields for the Extraction task."""
    result = parse_json_lenient(raw_output)
    if not result.ok:
        return MetricResult(name="field_accuracy", score=0.0, notes=["JSON parse failed"])

    predicted = result.data
    scores: list[float] = []
    notes: list[str] = []

    for key in _GOLD_KEYS:
        gold_val = _get_nested(gold, key)
        pred_val = _get_nested(predicted, key)
        s = _field_score(pred_val, gold_val)
        scores.append(s)
        if s < 1.0:
            notes.append(f"Field '{key}': predicted={pred_val!r}, gold={gold_val!r}, score={s:.2f}")

    avg = sum(scores) / max(1, len(scores))
    return MetricResult(name="field_accuracy", score=avg * 100, notes=notes)


# ---------------------------------------------------------------------------
# C3. must_flag_hit_rate
# ---------------------------------------------------------------------------

def _extract_clause_number(clause_str: str) -> str:
    """Extract bare clause number from a string like 'Clause 3' -> '3'."""
    parts = clause_str.strip().split()
    # If last part is a digit-like token, return it
    if parts:
        last = parts[-1]
        if last.isdigit() or last.replace(".", "").isdigit():
            return last
    return clause_str.strip()


def _risk_item_matches_clause(item: dict, clause_number: str) -> bool:
    """Check if a risk_item dict matches the given clause number."""
    item_clause = str(item.get("clause_number", "")).strip()
    if item_clause == clause_number:
        return True
    # Fuzzy match against all string fields
    for v in item.values():
        if isinstance(v, str) and fuzzy_similarity(v, clause_number) >= 0.7:
            return True
    return False


def must_flag_hit_rate(raw_output: str, gold_items: list[dict]) -> MetricResult:
    """For Risk task. Measure how many gold risk items are present in output."""
    result = parse_json_lenient(raw_output)
    if not result.ok:
        return MetricResult(name="must_flag_hit_rate", score=0.0, notes=["JSON parse failed"])

    risk_items: list[dict] = result.data.get("risk_items", [])
    notes: list[str] = []
    hits = 0

    for gold_item in gold_items:
        clause_number = _extract_clause_number(str(gold_item.get("clause", "")))
        matched = any(_risk_item_matches_clause(item, clause_number) for item in risk_items)
        if matched:
            hits += 1
        else:
            notes.append(f"Missing clause: {gold_item.get('clause')!r}")

    total = max(1, len(gold_items))
    score = hits / total * 100
    return MetricResult(name="must_flag_hit_rate", score=score, notes=notes)


# ---------------------------------------------------------------------------
# C4. false_positive_rate
# ---------------------------------------------------------------------------

_DEFAULT_KNOWN_CLAUSES: set[str] = {"1", "2", "3", "4", "5", "6", "7", "8", "9"}


def false_positive_rate(
    raw_output: str,
    known_clause_numbers: set[str] = _DEFAULT_KNOWN_CLAUSES,
) -> MetricResult:
    """For Risk task. Penalise risk_items referencing unknown clause numbers."""
    result = parse_json_lenient(raw_output)
    if not result.ok:
        return MetricResult(name="false_positive_rate", score=0.0, notes=["JSON parse failed"])

    risk_items: list[dict] = result.data.get("risk_items", [])
    notes: list[str] = []
    fp = 0

    for item in risk_items:
        clause_number = str(item.get("clause_number", "")).strip()
        if clause_number not in known_clause_numbers:
            fp += 1
            notes.append(f"False positive clause_number: {clause_number!r}")

    rate = fp / max(1, len(risk_items))
    score = 100.0 * (1 - rate)
    return MetricResult(name="false_positive_rate", score=score, notes=notes)


# ---------------------------------------------------------------------------
# C5. risk_level_accuracy
# ---------------------------------------------------------------------------

def risk_level_accuracy(raw_output: str, gold_items: list[dict]) -> MetricResult:
    """For Risk task. Compare risk_level for matched gold items."""
    result = parse_json_lenient(raw_output)
    if not result.ok:
        return MetricResult(name="risk_level_accuracy", score=0.0, notes=["JSON parse failed"])

    risk_items: list[dict] = result.data.get("risk_items", [])
    notes: list[str] = []
    total_matched = 0
    correct = 0

    for gold_item in gold_items:
        clause_number = _extract_clause_number(str(gold_item.get("clause", "")))
        matched_items = [i for i in risk_items if _risk_item_matches_clause(i, clause_number)]
        if not matched_items:
            continue
        total_matched += 1
        predicted_level = str(matched_items[0].get("risk_level", "")).strip().lower()
        gold_level = str(gold_item.get("risk_level", "")).strip().lower()
        if predicted_level == gold_level:
            correct += 1
        else:
            notes.append(
                f"Clause {clause_number}: predicted risk_level={predicted_level!r}, gold={gold_level!r}"
            )

    score = correct / max(1, total_matched) * 100
    return MetricResult(name="risk_level_accuracy", score=score, notes=notes)


# ---------------------------------------------------------------------------
# C6. structure_compliance
# ---------------------------------------------------------------------------

def structure_compliance(raw_output: str, schema: dict) -> MetricResult:
    """For Risk task. Check that each risk_item has all required subfields."""
    result = parse_json_lenient(raw_output)
    if not result.ok:
        return MetricResult(name="structure_compliance", score=0.0, notes=["JSON parse failed"])

    risk_items: list[dict] = result.data.get("risk_items", [])
    notes: list[str] = []

    # Derive required keys for each risk_item from schema
    items_schema = (
        schema.get("properties", {})
        .get("risk_items", {})
        .get("items", {})
    )
    required_keys: list[str] = items_schema.get(
        "required",
        list(items_schema.get("properties", {}).keys()),
    )

    if not required_keys:
        return MetricResult(
            name="structure_compliance",
            score=100.0,
            notes=["No required subfields defined in schema"],
        )

    compliant = 0
    for idx, item in enumerate(risk_items):
        missing = [k for k in required_keys if k not in item]
        if missing:
            notes.append(f"risk_items[{idx}] missing keys: {missing}")
        else:
            compliant += 1

    score = compliant / max(1, len(risk_items)) * 100
    return MetricResult(name="structure_compliance", score=score, notes=notes)


# ---------------------------------------------------------------------------
# C7. citation_coverage
# ---------------------------------------------------------------------------

def citation_coverage(raw_output: str, required_sources: list[str]) -> MetricResult:
    """For Research task. Check that required sources are cited in output."""
    result = parse_json_lenient(raw_output)
    if not result.ok:
        return MetricResult(name="citation_coverage", score=0.0, notes=["JSON parse failed"])

    data = result.data

    # Flatten text from key_findings[].sources and synthesis
    text_parts: list[str] = []

    for finding in data.get("key_findings", []):
        for src in finding.get("sources", []):
            if isinstance(src, str):
                text_parts.append(src)
            elif isinstance(src, dict):
                text_parts.extend(str(v) for v in src.values())

    synthesis = data.get("synthesis", "")
    if isinstance(synthesis, str):
        text_parts.append(synthesis)

    combined = " ".join(text_parts).lower()
    notes: list[str] = []
    cited = 0

    for source in required_sources:
        if source.lower() in combined:
            cited += 1
        else:
            notes.append(f"Source not cited: {source!r}")

    score = cited / max(1, len(required_sources)) * 100
    return MetricResult(name="citation_coverage", score=score, notes=notes)


# ---------------------------------------------------------------------------
# C8. required_findings_coverage
# ---------------------------------------------------------------------------

def required_findings_coverage(raw_output: str, gold_findings: list[dict]) -> MetricResult:
    """For Research task. Check that key findings cover gold keywords."""
    result = parse_json_lenient(raw_output)
    if not result.ok:
        return MetricResult(name="required_findings_coverage", score=0.0, notes=["JSON parse failed"])

    data = result.data

    # Flatten all text from key_findings and synthesis
    text_parts: list[str] = []

    for finding in data.get("key_findings", []):
        if isinstance(finding, str):
            text_parts.append(finding)
        elif isinstance(finding, dict):
            text_parts.extend(str(v) for v in finding.values())

    synthesis = data.get("synthesis", "")
    if isinstance(synthesis, str):
        text_parts.append(synthesis)

    combined = " ".join(text_parts).lower()
    notes: list[str] = []
    hits = 0

    for gold_finding in gold_findings:
        keywords: list[str] = gold_finding.get("keywords", [])
        matched_count = sum(1 for kw in keywords if kw.lower() in combined)
        if matched_count >= 2:
            hits += 1
        else:
            notes.append(
                f"Finding not covered (only {matched_count}/2+ keywords matched): {keywords}"
            )

    score = hits / max(1, len(gold_findings)) * 100
    return MetricResult(name="required_findings_coverage", score=score, notes=notes)


# ---------------------------------------------------------------------------
# C9. word_count_compliance
# ---------------------------------------------------------------------------

def word_count_compliance(raw_output: str) -> MetricResult:
    """For Research task. synthesis field must be 150-250 words."""
    result = parse_json_lenient(raw_output)
    if not result.ok:
        return MetricResult(name="word_count_compliance", score=0.0, notes=["JSON parse failed"])

    synthesis = result.data.get("synthesis", "")
    if not isinstance(synthesis, str):
        return MetricResult(
            name="word_count_compliance",
            score=0.0,
            notes=["'synthesis' field is missing or not a string"],
        )

    word_count = len(synthesis.split())

    if 150 <= word_count <= 250:
        return MetricResult(
            name="word_count_compliance",
            score=100.0,
            notes=[f"Word count {word_count} is within 150-250 bounds"],
        )

    return MetricResult(
        name="word_count_compliance",
        score=0.0,
        notes=[f"Word count {word_count} is outside 150-250 bounds"],
    )
