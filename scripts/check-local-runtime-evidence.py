#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = Path("outputs/local_runtime_evidence")
BLOCKED_KEYS = {
    "api_key",
    "authorization",
    "bearer_token",
    "chain_of_thought",
    "credentials",
    "password",
    "private_key",
    "raw_provider_body",
    "raw_response",
    "reasoning",
    "secret",
    "thinking",
}
BLOCKED_TEXT = (
    "chain of thought",
    "private reasoning",
    "api_key=",
    "authorization:",
    "bearer ",
    "client_secret",
    "private_key",
)
HEX_DIGITS = frozenset("0123456789abcdef")
PUBLICATION_BINDING_MARKER = "Scaffold-Arena-Publication-Binding: "
PUBLICATION_BINDING_MAX_BYTES = 16_384
PUBLICATION_BINDING_KIND = "scaffold-arena-publication-source-binding"
PORTABLE_CLAIM_CEILING = "historical_integrity_not_current_code_or_live_evidence"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _is_digest(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= HEX_DIGITS


def _is_git_oid(value: object) -> bool:
    return isinstance(value, str) and len(value) in {40, 64} and set(value) <= HEX_DIGITS


def _safe_path(value: object) -> str | None:
    if not isinstance(value, str) or not value or "\x00" in value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        return None
    return value


def _canonical_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate key: {key}")
        value[key] = item
    return value


def _git_output(root: Path, arguments: list[str]) -> bytes | None:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=False,
        capture_output=True,
    )
    return result.stdout if result.returncode == 0 else None


def _root_commit(root: Path) -> tuple[str | None, list[str]]:
    output = _git_output(root, ["rev-list", "--max-parents=0", "HEAD"])
    if output is None:
        return None, ["could not resolve repository root commit"]
    roots = [line for line in output.decode("ascii", errors="replace").splitlines() if line]
    if len(roots) != 1 or not _is_git_oid(roots[0] if roots else None):
        return None, ["publication binding requires exactly one reachable root commit"]
    return roots[0], []


def _root_commit_message(root: Path, revision: str) -> bytes | None:
    return _git_output(root, ["show", "-s", "--format=%B", revision])


def _tree_inventory_sha256(root: Path, revision: str) -> tuple[str | None, list[str]]:
    """Hash canonical `git ls-tree -r -z` mode/type/object/path records."""

    output = _git_output(root, ["ls-tree", "-r", "-z", "--full-tree", revision])
    if output is None:
        return None, ["could not read bound root tree inventory"]
    canonical_records: list[bytes] = []
    seen_paths: set[bytes] = set()
    for record in output.split(b"\0"):
        if not record:
            continue
        try:
            header, path = record.split(b"\t", maxsplit=1)
            mode, object_type, object_id = header.split(b" ")
        except ValueError:
            return None, ["bound root tree inventory has an invalid record"]
        if (
            len(mode) != 6
            or not mode.isdigit()
            or object_type != b"blob"
            or not _is_git_oid(object_id.decode("ascii", errors="replace"))
            or not path
            or path in seen_paths
        ):
            return None, ["bound root tree inventory has an invalid mode/type/object/path record"]
        try:
            decoded_path = path.decode("utf-8")
        except UnicodeDecodeError:
            return None, ["bound root tree inventory has a non-UTF-8 path"]
        if _safe_path(decoded_path) is None:
            return None, ["bound root tree inventory has an unsafe path"]
        seen_paths.add(path)
        canonical_records.append(b" ".join((mode, object_type, object_id)) + b"\t" + path + b"\0")
    return _digest(b"".join(canonical_records)), []


def _parse_publication_binding(message: bytes) -> tuple[dict[str, Any] | None, list[str]]:
    if len(message) > PUBLICATION_BINDING_MAX_BYTES * 2:
        return None, ["publication binding commit message exceeds size limit"]
    try:
        lines = message.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return None, ["publication binding commit message is not UTF-8"]
    markers = [line[len(PUBLICATION_BINDING_MARKER) :] for line in lines if line.startswith(PUBLICATION_BINDING_MARKER)]
    if not markers:
        return None, []
    if len(markers) != 1:
        return None, ["publication binding must appear exactly once in the root commit message"]
    encoded = markers[0]
    if not encoded or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for character in encoded):
        return None, ["publication binding is not unpadded base64url"]
    try:
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    except ValueError:
        return None, ["publication binding cannot be decoded"]
    if not raw or len(raw) > PUBLICATION_BINDING_MAX_BYTES:
        return None, ["publication binding payload exceeds size limit"]
    if base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=") != encoded:
        return None, ["publication binding is not canonically base64url encoded"]
    try:
        binding = json.loads(raw, object_pairs_hook=_canonical_object_pairs)
    except (UnicodeDecodeError, ValueError, TypeError):
        return None, ["publication binding payload is not valid JSON"]
    if not isinstance(binding, dict) or _canonical(binding) != raw:
        return None, ["publication binding payload must use canonical JSON"]
    expected_keys = {
        "claim_ceiling",
        "historical_bundles",
        "kind",
        "inventory_sha256",
        "schema_version",
        "source_revision",
        "source_tree",
    }
    if set(binding) != expected_keys:
        return None, ["publication binding schema keys are invalid"]
    if type(binding.get("schema_version")) is not int or binding.get("schema_version") != 1 or binding.get("kind") != PUBLICATION_BINDING_KIND:
        return None, ["publication binding schema version or kind is invalid"]
    if binding.get("claim_ceiling") != PORTABLE_CLAIM_CEILING:
        return None, ["publication binding claim ceiling is invalid"]
    if not _is_git_oid(binding.get("source_revision")) or not _is_git_oid(binding.get("source_tree")):
        return None, ["publication binding source revision or tree is invalid"]
    if not _is_digest(binding.get("inventory_sha256")):
        return None, ["publication binding inventory digest is invalid"]
    bundles = binding.get("historical_bundles")
    if not isinstance(bundles, list) or not bundles or len(bundles) > 128:
        return None, ["publication binding historical bundles are invalid"]
    paths: list[str] = []
    for item in bundles:
        if not isinstance(item, dict) or set(item) != {"path", "bundle_manifest_sha256"}:
            return None, ["publication binding historical bundle schema is invalid"]
        path = item.get("path")
        if not isinstance(path, str) or not path.startswith(f"{EVIDENCE_ROOT.as_posix()}/"):
            return None, ["publication binding historical bundle path is outside the evidence root"]
        safe_path = _safe_path(path)
        if safe_path is None or len(PurePosixPath(safe_path).parts) != len(EVIDENCE_ROOT.parts) + 1:
            return None, ["publication binding historical bundle path is invalid"]
        if not _is_digest(item.get("bundle_manifest_sha256")):
            return None, ["publication binding historical bundle digest is invalid"]
        paths.append(safe_path)
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        return None, ["publication binding historical bundles must be unique and sorted"]
    return binding, []


def _publication_binding(root: Path) -> tuple[dict[str, Any] | None, list[str]]:
    inside_work_tree = _git_output(root, ["rev-parse", "--is-inside-work-tree"])
    if inside_work_tree is None or inside_work_tree.strip() != b"true":
        return None, []
    revision, errors = _root_commit(root)
    if errors or revision is None:
        return None, errors
    message = _root_commit_message(root, revision)
    if message is None:
        return None, ["could not read root commit message for publication binding"]
    binding, errors = _parse_publication_binding(message)
    if binding is None:
        return None, errors

    tree = _git_output(root, ["rev-parse", f"{revision}^{{tree}}"])
    if tree is None or tree.decode("ascii", errors="replace").strip() != binding["source_tree"]:
        return None, ["publication binding source tree does not match the root snapshot tree"]
    inventory_sha256, inventory_errors = _tree_inventory_sha256(root, revision)
    if inventory_errors:
        return None, inventory_errors
    if inventory_sha256 != binding["inventory_sha256"]:
        return None, ["publication binding inventory digest does not match the root snapshot tree"]
    return binding, []


def _bound_bundle_manifest_errors(root: Path, binding: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        root_real = root.resolve(strict=True)
    except (OSError, RuntimeError):
        return ["publication binding repository root is unresolved"]
    bundles = binding.get("historical_bundles")
    if not isinstance(bundles, list):
        return ["publication binding historical bundles are invalid"]
    for item in bundles:
        if not isinstance(item, Mapping):
            return ["publication binding historical bundle schema is invalid"]
        relative = item.get("path")
        expected = item.get("bundle_manifest_sha256")
        if not isinstance(relative, str) or not _is_digest(expected):
            return ["publication binding historical bundle schema is invalid"]
        bundle = root / relative
        expected_bundle = root_real / relative
        try:
            bundle_real = bundle.resolve(strict=True)
        except (OSError, RuntimeError):
            errors.append(f"publication binding historical bundle is missing: {relative}")
            continue
        if bundle.is_symlink() or not bundle.is_dir() or bundle_real != expected_bundle:
            errors.append(f"publication binding historical bundle is not a contained real directory: {relative}")
            continue
        manifest = bundle / "bundle-manifest.json"
        if manifest.is_symlink() or not manifest.is_file():
            errors.append(f"publication binding historical bundle is missing: {relative}")
            continue
        if _digest(manifest.read_bytes()) != expected:
            errors.append(f"publication binding historical bundle changed: {relative}")
    return errors


def _bound_bundle_manifest_digest(binding: Mapping[str, Any], relative: str) -> str | None:
    bundles = binding.get("historical_bundles")
    if not isinstance(bundles, list):
        return None
    for item in bundles:
        if isinstance(item, Mapping) and item.get("path") == relative:
            digest = item.get("bundle_manifest_sha256")
            return digest if _is_digest(digest) else None
    return None


def _privacy_errors(value: Any, location: str) -> list[str]:
    errors: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in BLOCKED_KEYS:
                errors.append(f"{location}: prohibited field {key}")
            errors.extend(_privacy_errors(item, location))
    elif isinstance(value, list):
        for item in value:
            errors.extend(_privacy_errors(item, location))
    elif isinstance(value, str):
        lowered = value.lower()
        if any(marker in lowered for marker in BLOCKED_TEXT):
            errors.append(f"{location}: prohibited sensitive text")
    return errors


def _git_ancestor(root: Path, revision: str) -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", revision, "HEAD"],
        cwd=root,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _receipt_hash(receipt_id: str, manifest_hash: str, artifact_hashes: list[str]) -> str:
    return _digest(
        _canonical(
            {
                "receipt_id": receipt_id,
                "manifest_hash": manifest_hash,
                "artifact_hashes": artifact_hashes,
                "integrity_not_truth": True,
            }
        )
    )


def _verification_receipt_hash(
    receipt_id: str,
    manifest_hash: str,
    artifact_hashes: list[str],
    receipt_hash: str,
) -> str:
    return _digest(
        _canonical(
            {
                "receipt_id": receipt_id,
                "manifest_hash": manifest_hash,
                "artifact_hashes": artifact_hashes,
                "receipt_hash": receipt_hash,
                "integrity_not_truth": True,
            }
        )
    )


def audit_bundle(
    bundle: Path,
    *,
    is_ancestor: Callable[[str], bool],
    bound_manifest_sha256: str | None = None,
) -> list[str]:
    errors: list[str] = []
    prefix = bundle.name
    if bundle.is_symlink() or not bundle.is_dir():
        return [f"{prefix}: bundle must be a real directory"]
    manifest_path = bundle / "bundle-manifest.json"
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
    except (OSError, ValueError):
        return [f"{prefix}: missing or invalid bundle-manifest.json"]
    if bound_manifest_sha256 is not None and _digest(manifest_bytes) != bound_manifest_sha256:
        errors.append(f"{prefix}: publication-bound bundle manifest changed")
    entries = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(entries, list):
        return [f"{prefix}: manifest files must be a list"]

    declared: dict[str, str] = {}
    for entry in entries:
        path = _safe_path(entry.get("path") if isinstance(entry, dict) else None)
        digest = entry.get("sha256") if isinstance(entry, dict) else None
        if path is None or not _is_digest(digest):
            errors.append(f"{prefix}: invalid manifest entry")
            continue
        if path in declared:
            errors.append(f"{prefix}: duplicate manifest path {path}")
        declared[path] = digest

    actual: set[str] = set()
    for path in bundle.rglob("*"):
        relative = path.relative_to(bundle).as_posix()
        if path.is_symlink():
            errors.append(f"{prefix}: symlink forbidden: {relative}")
            continue
        if path.is_dir():
            if relative != "artifacts":
                errors.append(f"{prefix}: unexpected directory: {relative}")
            continue
        if not path.is_file():
            errors.append(f"{prefix}: non-regular file forbidden: {relative}")
            continue
        if path != manifest_path:
            actual.add(relative)
    if actual != set(declared):
        errors.append(f"{prefix}: manifest paths do not exactly match bundle files")
    for relative, expected in declared.items():
        path = bundle / relative
        if path.is_file() and _digest(path.read_bytes()) != expected:
            errors.append(f"{prefix}: digest mismatch: {relative}")
    expected_bundle_hash = _digest(_canonical({"files": declared}))
    if manifest.get("bundle_hash") != expected_bundle_hash:
        errors.append(f"{prefix}: bundle hash mismatch")

    def load(name: str) -> Any:
        try:
            return json.loads((bundle / name).read_bytes())
        except (OSError, ValueError):
            errors.append(f"{prefix}: missing or invalid {name}")
            return None

    summary = load("summary.json")
    receipt = load("receipt.json")
    verification = load("receipt-verification.json")
    inventory = load("artifact-digest-inventory.json")
    receipt_artifacts: list[str] | None = None
    if isinstance(receipt, dict):
        receipt_id = receipt.get("receipt_id")
        manifest_hash = receipt.get("manifest_hash")
        if not isinstance(receipt_id, str) or not receipt_id:
            errors.append(f"{prefix}: receipt id is invalid")
        if not _is_digest(manifest_hash):
            errors.append(f"{prefix}: receipt manifest hash is invalid")
        if receipt.get("integrity_not_truth") is not True:
            errors.append(f"{prefix}: receipt integrity marker is missing")
        artifacts = receipt.get("artifacts")
        if not isinstance(artifacts, list):
            errors.append(f"{prefix}: receipt artifacts must be a list")
        else:
            receipt_artifacts = []
            for artifact in artifacts:
                digest = artifact.get("sha256") if isinstance(artifact, dict) else None
                if not _is_digest(digest):
                    errors.append(f"{prefix}: receipt artifact digest is invalid")
                    continue
                if digest in receipt_artifacts:
                    errors.append(f"{prefix}: duplicate receipt artifact digest {digest}")
                receipt_artifacts.append(digest)
            if (
                isinstance(receipt_id, str)
                and isinstance(manifest_hash, str)
                and _is_digest(receipt.get("receipt_hash"))
                and receipt.get("receipt_hash")
                != _receipt_hash(receipt_id, manifest_hash, receipt_artifacts)
            ):
                errors.append(f"{prefix}: receipt hash mismatch")
    if isinstance(summary, dict):
        if summary.get("status") != "COMPLETE_LOCAL_EXPLORATORY_CUSTODY":
            errors.append(f"{prefix}: invalid summary status")
        boundary = str(summary.get("claim_boundary", "")).lower()
        if "never confirmatory" not in boundary or "never a scaffold-effect claim" not in boundary:
            errors.append(f"{prefix}: claim boundary is not restrictive")
        if summary.get("paid_cost_usd") != 0.0 or summary.get("energy_status") != "unknown":
            errors.append(f"{prefix}: local cost or energy policy mismatch")
        revision = summary.get("code_revision")
        if not _is_git_oid(revision):
            errors.append(f"{prefix}: code revision is invalid")
        elif not is_ancestor(revision) and bound_manifest_sha256 is None:
            errors.append(f"{prefix}: code revision is not an ancestor of HEAD")
    if not isinstance(receipt, dict) or receipt.get("evidence_type") != "derived_local_live" or receipt.get("evidence_class") != "local_live":
        errors.append(f"{prefix}: receipt classification mismatch")
    if not isinstance(verification, dict) or verification.get("verified") is not True:
        errors.append(f"{prefix}: receipt is not freshly verified")
    if isinstance(verification, dict):
        if verification.get("integrity_not_truth") is not True:
            errors.append(f"{prefix}: verification integrity marker is missing")
        if not _is_digest(verification.get("receipt_hash")):
            errors.append(f"{prefix}: verification receipt hash is invalid")
        if not _is_digest(verification.get("manifest_hash")):
            errors.append(f"{prefix}: verification manifest hash is invalid")
        if verification.get("verified") is True and verification.get("errors") != []:
            errors.append(f"{prefix}: verified receipt carries verification errors")
        if (
            receipt_artifacts is not None
            and isinstance(receipt, dict)
            and isinstance(receipt.get("receipt_id"), str)
            and isinstance(receipt.get("manifest_hash"), str)
            and _is_digest(receipt.get("receipt_hash"))
            and verification.get("receipt_hash")
            != _verification_receipt_hash(
                receipt["receipt_id"],
                receipt["manifest_hash"],
                receipt_artifacts,
                receipt["receipt_hash"],
            )
        ):
            errors.append(f"{prefix}: verification receipt hash mismatch")
    if (
        isinstance(receipt, dict)
        and isinstance(verification, dict)
        and (
            receipt.get("receipt_id") != verification.get("receipt_id")
            or receipt.get("manifest_hash") != verification.get("manifest_hash")
        )
    ):
        errors.append(f"{prefix}: receipt verification binding mismatch")

    inventory_digests: set[str] = set()
    if isinstance(inventory, list):
        for item in inventory:
            if not isinstance(item, dict):
                errors.append(f"{prefix}: invalid artifact inventory entry")
                continue
            digest = item.get("sha256")
            relative = item.get("path")
            path = bundle / relative if _safe_path(relative) else None
            if not _is_digest(digest) or path is None or relative != f"artifacts/{digest}":
                errors.append(f"{prefix}: invalid artifact inventory binding")
                continue
            if digest in inventory_digests:
                errors.append(f"{prefix}: duplicate artifact inventory digest {digest}")
            inventory_digests.add(digest)
            if not path.is_file() or _digest(path.read_bytes()) != digest or path.stat().st_size != item.get("size_bytes"):
                errors.append(f"{prefix}: artifact integrity mismatch: {relative}")
    else:
        errors.append(f"{prefix}: artifact inventory must be a list")

    manifest_artifacts = {
        relative.removeprefix("artifacts/")
        for relative in declared
        if relative.startswith("artifacts/")
    }
    if inventory_digests != manifest_artifacts:
        errors.append(f"{prefix}: artifact inventory does not match manifest artifacts")
    if receipt_artifacts is not None:
        for digest in receipt_artifacts:
            relative = f"artifacts/{digest}"
            if digest not in inventory_digests or declared.get(relative) != digest:
                errors.append(f"{prefix}: receipt artifact is not bound to manifest/inventory: {digest}")

    for relative in actual:
        data = (bundle / relative).read_bytes()
        try:
            value = json.loads(data)
        except (UnicodeDecodeError, ValueError):
            value = data.decode("utf-8", errors="replace")
        errors.extend(_privacy_errors(value, f"{prefix}/{relative}"))
    return errors


def audit(root: Path = ROOT) -> list[str]:
    evidence_root = root / EVIDENCE_ROOT
    try:
        root_real = root.resolve(strict=True)
        evidence_real = evidence_root.resolve(strict=True)
    except (OSError, RuntimeError):
        return [f"missing or unresolved evidence root: {EVIDENCE_ROOT}"]
    expected_real = root_real / EVIDENCE_ROOT
    if evidence_root.is_symlink() or evidence_real != expected_real or not evidence_root.is_dir():
        return [f"evidence root must be a contained real directory: {EVIDENCE_ROOT}"]
    binding, binding_errors = _publication_binding(root)
    if binding_errors:
        return binding_errors
    entries = sorted(evidence_root.iterdir())
    errors: list[str] = []
    for path in entries:
        if path.is_symlink():
            errors.append(f"evidence root: symlink forbidden: {path.name}")
        elif not path.is_dir():
            errors.append(f"evidence root: unexpected non-directory entry: {path.name}")
    bundles = [path for path in entries if path.is_dir() and not path.is_symlink()]
    if binding is not None:
        errors.extend(_bound_bundle_manifest_errors(root, binding))
    if not bundles:
        errors.append(f"no local-runtime evidence bundles under {EVIDENCE_ROOT}")
        return errors
    for bundle in bundles:
        relative = (EVIDENCE_ROOT / bundle.name).as_posix()
        errors.extend(
            audit_bundle(
                bundle,
                is_ancestor=lambda revision: _git_ancestor(root, revision),
                bound_manifest_sha256=(
                    _bound_bundle_manifest_digest(binding, relative) if binding is not None else None
                ),
            )
        )
    return errors


def main() -> int:
    argparse.ArgumentParser(description="Validate local-runtime evidence custody.").parse_args()
    errors = audit()
    if errors:
        for error in errors:
            print(f"[local-runtime-evidence] FAIL: {error}")
        return 1
    binding, binding_errors = _publication_binding(ROOT)
    if binding_errors:
        for error in binding_errors:
            print(f"[local-runtime-evidence] FAIL: {error}")
        return 1
    if binding is not None:
        print(
            "[local-runtime-evidence] PASS: historical_source_revision_unverifiable_in_snapshot; "
            "historical integrity only, not current code or live evidence"
        )
    else:
        print(f"[local-runtime-evidence] PASS: {len(list((ROOT / EVIDENCE_ROOT).iterdir()))} bundles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
