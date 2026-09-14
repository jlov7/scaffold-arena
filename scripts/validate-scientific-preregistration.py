"""Validate offline preregistration custody and Protocol-v1 matrix contracts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from protocol_v1 import load_study_pack
from protocol_v1.canonical import sha256_bytes
from protocol_v1.scientific_completion import (
    build_fixture_bundle,
    load_scientific_study,
    resolve_study_artifact,
)

ROOT = Path(__file__).resolve().parents[1]
PACKS = ("flagship-prereg-v1", "transfer-prereg-v1")


def validate(pack_id: str) -> list[str]:
    root = ROOT / "study_packs" / pack_id
    errors: list[str] = []
    try:
        pack = load_study_pack(root)
        study = load_scientific_study(root / "fixtures/scientific-study.json")
    except ValueError as exc:
        return [f"{pack_id}: invalid declarative pack or scientific contract: {exc}"]
    try:
        artifact = resolve_study_artifact(root, study.preregistration.artifact_uri)
    except ValueError:
        errors.append(f"{pack_id}: preregistration artifact path is unsafe")
    else:
        if sha256_bytes(artifact.read_bytes()) != study.preregistration.artifact_hash:
            errors.append(f"{pack_id}: preregistration artifact hash mismatch")
    extension = pack.extensions.get("org.scaffold-arena.scientific-v1")
    if not isinstance(extension, dict):
        errors.append(f"{pack_id}: scientific extension missing")
        return errors
    contract_uri, contract_hash = extension.get("contract_uri"), extension.get("contract_hash")
    if not isinstance(contract_uri, str) or not isinstance(contract_hash, str):
        errors.append(f"{pack_id}: scientific extension contract binding malformed")
    else:
        try:
            contract = resolve_study_artifact(root, contract_uri)
        except ValueError:
            errors.append(f"{pack_id}: scientific contract path is unsafe")
        else:
            if sha256_bytes(contract.read_bytes()) != contract_hash:
                errors.append(f"{pack_id}: scientific contract hash mismatch")
    if extension.get("publication_state") != study.preregistration.publication_state:
        errors.append(f"{pack_id}: publication state differs between pack and contract")
    if extension.get("no_retuning") != study.no_retuning:
        errors.append(f"{pack_id}: no-retuning invariant differs between pack and contract")
    try:
        custody_path = resolve_study_artifact(root, "fixtures/custody-manifest.json")
        custody = json.loads(custody_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        errors.append(f"{pack_id}: custody manifest is missing or invalid")
    else:
        expected_files = {
            "preregistration.md": study.preregistration.artifact_hash,
            "scientific-study.json": contract_hash,
        }
        observed_files = {
            item.get("path"): item.get("sha256")
            for item in custody.get("files", [])
            if isinstance(item, dict)
        }
        if custody.get("study_id") != study.study_id or custody.get("publication_state") != study.preregistration.publication_state:
            errors.append(f"{pack_id}: custody manifest study or publication state mismatch")
        if custody.get("integrity_not_truth") is not True or observed_files != expected_files:
            errors.append(f"{pack_id}: custody manifest does not exactly bind preregistration and contract")
    try:
        plan = build_fixture_bundle(study)
    except ValueError as exc:
        errors.append(f"{pack_id}: matrix planning failed: {exc}")
    else:
        if len(plan["matrix"]["cells"]) != plan["matrix"]["expected_cells"]:
            errors.append(f"{pack_id}: matrix is incomplete")
        if plan["fixture_live_separation"]["provider_requests_started"]:
            errors.append(f"{pack_id}: fixture plan must not start providers")
        if plan["confirmatory_status"] != "HOLD_PREREGISTRATION_NOT_PUBLIC_IMMUTABLE":
            errors.append(f"{pack_id}: unpublished preregistration must hold confirmatory dispatch")
    return errors


def main() -> int:
    errors = [error for pack_id in PACKS for error in validate(pack_id)]
    if errors:
        for error in errors:
            print(f"[scientific-preregistration] FAIL: {error}", file=sys.stderr)
        return 1
    print(f"[scientific-preregistration] validated {len(PACKS)} offline Protocol-v1 preregistration packs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
