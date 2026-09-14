#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = ROOT / "outputs/external_validation.json"
AUDIT_PATH = ROOT / "outputs/external_validation_audit.json"
SCHEMA_PATH = ROOT / "specs/external-validation.schema.json"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def _dump_json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, sort_keys=False) + "\n"


def _is_public_url(value: str) -> bool:
    parsed = urlparse(value)
    host = parsed.netloc.lower()
    if parsed.scheme not in {"https", "http"} or not host:
        return False
    if host in {"localhost", "127.0.0.1", "0.0.0.0"} or host.endswith(".local"):
        return False
    return True


def _artifact_reference_errors(prefix: str, artifact_uri: str) -> list[str]:
    if _is_public_url(artifact_uri):
        return []
    if artifact_uri.startswith("/") or artifact_uri.startswith("file:"):
        return [f"{prefix}: artifact_uri must not be a local absolute/file URL"]
    candidate = ROOT / artifact_uri
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        return [f"{prefix}: artifact_uri is neither a public URL nor an existing repo artifact"]
    resolved_root = ROOT.resolve(strict=True)
    if resolved != resolved_root and resolved_root not in resolved.parents:
        return [f"{prefix}: artifact_uri must resolve inside the repository"]
    if not resolved.is_file():
        return [f"{prefix}: artifact_uri must reference a regular repo file"]
    return []


def build_audit() -> dict[str, Any]:
    schema = _load_json(SCHEMA_PATH)
    ledger = _load_json(LEDGER_PATH)
    validation_errors: list[str] = []
    try:
        jsonschema.Draft7Validator.check_schema(schema)
        jsonschema.validate(instance=ledger, schema=schema)
    except jsonschema.SchemaError as exc:
        validation_errors.append(f"external validation schema invalid: {exc.message}")
    except jsonschema.ValidationError as exc:
        validation_errors.append(f"external validation ledger invalid: {exc.message}")

    reproductions = ledger.get("independent_reproductions", [])
    critiques = ledger.get("public_critiques", [])
    annotation_batches = ledger.get("human_annotation_batches", [])
    evidence_count = len(reproductions) + len(critiques) + len(annotation_batches)

    if evidence_count == 0 and ledger.get("status") != "no_external_validation_completed":
        validation_errors.append("zero evidence records require status no_external_validation_completed")
    if evidence_count > 0 and ledger.get("status") != "external_validation_completed":
        validation_errors.append("nonzero evidence records require status external_validation_completed")

    for item in reproductions:
        item_id = str(item.get("id", "unknown"))
        validation_errors.extend(_artifact_reference_errors(f"independent_reproductions[{item_id}]", str(item.get("artifact_uri", ""))))
        if item.get("result") == "pass" and "live" not in str(item.get("scope", "")).lower():
            validation_errors.append(f"independent_reproductions[{item_id}]: pass results must state live or fixture scope explicitly")

    for item in critiques:
        item_id = str(item.get("id", "unknown"))
        if not _is_public_url(str(item.get("url", ""))):
            validation_errors.append(f"public_critiques[{item_id}]: url must be a public http(s) URL")

    for item in annotation_batches:
        item_id = str(item.get("id", "unknown"))
        prefix = f"human_annotation_batches[{item_id}]"
        if item.get("protocol_version") != "1.0":
            validation_errors.append(f"{prefix}: protocol_version must be 1.0")
        if int(item.get("annotator_count", 0)) < 3:
            validation_errors.append(f"{prefix}: annotator_count must be at least 3")
        if item.get("resolved_conflicts") is not True:
            validation_errors.append(f"{prefix}: resolved_conflicts must be true")
        for field in (
            "agreement_artifact_uri",
            "adjudication_artifact_uri",
            "review_completion_artifact_uri",
            "authority_attestation_uri",
        ):
            validation_errors.extend(_artifact_reference_errors(f"{prefix}.{field}", str(item.get(field, ""))))

    if evidence_count == 0:
        status = "blocked_no_external_validation"
    elif validation_errors:
        status = "invalid_external_validation_evidence"
    else:
        status = "external_validation_evidence_recorded_not_live_or_field_validation"

    return {
        "schema_version": "0.1",
        "generated_at": "2026-05-23T00:00:00Z",
        "status": status,
        "ledger": "outputs/external_validation.json",
        "evidence_count": evidence_count,
        "independent_reproduction_count": len(reproductions),
        "public_critique_count": len(critiques),
        "human_annotation_batch_count": len(annotation_batches),
        "validation_error_count": len(validation_errors),
        "validation_errors": validation_errors,
        "blockers_before_95": [
            "Obtain at least one independent clean-room reproduction or serious external critique.",
            "Record public URLs or repo artifacts for every external evidence item.",
            "Do not mark outputs/external_validation.json completed until concrete evidence records exist.",
            "Do not treat external validation as live benchmark or human calibration evidence by itself.",
        ],
        "claim_boundary": (
            "This audit validates external reproduction, public critique, and human annotation batch "
            "records when they exist. With zero evidence records it is a blocker ledger, not external "
            "validation evidence, not live benchmark evidence, and not human calibration evidence."
        ),
    }


def _validate_audit(audit: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if audit.get("status") not in {
        "blocked_no_external_validation",
        "invalid_external_validation_evidence",
        "external_validation_evidence_recorded_not_live_or_field_validation",
    }:
        errors.append("external validation audit status is invalid")
    if audit.get("evidence_count", 0) == 0 and audit.get("status") != "blocked_no_external_validation":
        errors.append("zero evidence records must keep blocked_no_external_validation status")
    if audit.get("validation_error_count", 0) != 0:
        errors.append("external validation audit contains validation errors")
    text = json.dumps(audit).lower()
    for phrase in ["not external validation evidence", "not live benchmark evidence", "not human calibration evidence"]:
        if phrase not in text:
            errors.append(f"external validation audit missing claim-boundary phrase: {phrase}")
    return errors


def _check_file() -> list[str]:
    expected = _dump_json(build_audit())
    current = AUDIT_PATH.read_text() if AUDIT_PATH.exists() else ""
    if current != expected:
        return [f"{AUDIT_PATH.relative_to(ROOT)} is stale"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or check external validation evidence integrity.")
    parser.add_argument("--write", action="store_true", help="Write outputs/external_validation_audit.json.")
    parser.add_argument("--check", action="store_true", help="Fail if the external validation audit is stale.")
    args = parser.parse_args()

    audit = build_audit()
    if args.write:
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        AUDIT_PATH.write_text(_dump_json(audit))
        print(f"[external-validation] wrote {AUDIT_PATH.relative_to(ROOT)}")
        return 0

    errors = _validate_audit(audit)
    if args.check:
        errors.extend(_check_file())
    if errors:
        for error in errors:
            print(f"[external-validation] FAIL: {error}", file=sys.stderr)
        return 1
    print(f"[external-validation] checked {audit['evidence_count']} external evidence records; status={audit['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
