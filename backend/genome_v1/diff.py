"""Pure semantic comparison and intervention-locality checks for Genome v1."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import Field

from .canonical import descriptor_payload, digest_for
from .models import GenomeDescriptor, GenomeModel, Sha256Digest

Classification = Literal["metadata", "source", "configuration", "capability", "protocol", "lifecycle", "policy", "authority", "custody"]


class FieldChange(GenomeModel):
    path: str = Field(pattern=r"^/")
    before: Any | None = None
    after: Any | None = None
    classification: Classification


class GenomeDiff(GenomeModel):
    before_digest: Sha256Digest
    after_digest: Sha256Digest
    diff_digest: Sha256Digest
    added: tuple[FieldChange, ...] = ()
    removed: tuple[FieldChange, ...] = ()
    changed: tuple[FieldChange, ...] = ()
    classifications: tuple[Classification, ...] = ()
    affected_graphs: tuple[Literal["mechanism", "execution", "evidence"], ...] = ()
    breaking: bool
    limitations: tuple[str, ...] = ("Diff describes descriptor changes; it does not establish runtime behavior or authority.",)


class LocalityResult(GenomeModel):
    verdict: Literal["PASS", "HOLD"]
    code: Literal["PASS_INTERVENTION_LOCAL", "HOLD_INTERVENTION_NONLOCAL", "HOLD_APPLIED_CONTROL_RECEIPT_REQUIRED"]
    target_path: str = Field(pattern=r"^/")
    changed_paths: tuple[str, ...]
    unexpected_paths: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ("Locality is descriptor-only and does not prove an applied runtime control.",)


_ID_ARRAYS = {"components": "component_id", "relations": "relation_id", "capabilities": "capability_id", "protocols": "protocol_id", "source_bindings": "source_id"}


def _escape(part: str) -> str:
    return part.replace("~", "~0").replace("/", "~1")


def _items(value: Any, *, array_name: str | None = None) -> Mapping[str, Any] | Sequence[Any] | Any:
    if array_name in _ID_ARRAYS and isinstance(value, list):
        key = _ID_ARRAYS[array_name]
        return {str(item[key]): item for item in value if isinstance(item, Mapping) and key in item}
    return value


def _classify(path: str) -> Classification:
    root = path.split("/")[1] if path.startswith("/") and len(path.split("/")) > 1 else ""
    if root == "components":
        if path.endswith("/config_digest"):
            return "configuration"
        if path.endswith("/source"):
            return "source"
        if path.endswith("/lifecycle"):
            return "lifecycle"
        return "configuration"
    if root == "capabilities": return "capability"
    if root == "protocols": return "protocol"
    if root in {"source_bindings", "relations"}: return "custody"
    if root in {"acp_identity", "acp_policy"}: return "policy"
    if root == "authority": return "authority"
    return "metadata"


def _walk(before: Any, after: Any, path: str, output: list[tuple[str, str, Any, Any]]) -> None:
    if type(before) is not type(after):
        output.append(("changed", path, before, after)); return
    if isinstance(before, Mapping):
        for key in sorted(set(before) | set(after)):
            child = f"{path}/{_escape(str(key))}"
            if key not in before: output.append(("added", child, None, after[key]))
            elif key not in after: output.append(("removed", child, before[key], None))
            else: _walk(before[key], after[key], child, output)
        return
    if isinstance(before, list):
        mapped_before, mapped_after = _items(before, array_name=path.rsplit("/", 1)[-1]), _items(after, array_name=path.rsplit("/", 1)[-1])
        if isinstance(mapped_before, Mapping) and isinstance(mapped_after, Mapping):
            _walk(mapped_before, mapped_after, path, output); return
        if before != after: output.append(("changed", path, before, after))
        return
    if before != after: output.append(("changed", path, before, after))


def _redact(path: str, value: Any) -> Any:
    lowered = path.casefold()
    if any(token in lowered for token in ("secret", "token", "password", "authorization", "cookie", "api_key", "/key")):
        return {"redacted": True, "digest": digest_for(value, domain="scaffold-arena.genome.diff-redaction")}
    return value


def semantic_diff(before: GenomeDescriptor, after: GenomeDescriptor) -> GenomeDiff:
    """Compare descriptors by stable IDs; no graph or authority is inferred."""
    changes: list[tuple[str, str, Any, Any]] = []
    _walk(descriptor_payload(before), descriptor_payload(after), "", changes)
    buckets: dict[str, list[FieldChange]] = {"added": [], "removed": [], "changed": []}
    for kind, path, old, new in changes:
        buckets[kind].append(FieldChange(path=path or "/", before=_redact(path, old), after=_redact(path, new), classification=_classify(path)))
    all_changes = [*buckets["added"], *buckets["removed"], *buckets["changed"]]
    classifications = tuple(sorted({change.classification for change in all_changes}))
    affects = set()
    for classification in classifications:
        if classification in {"configuration", "capability", "protocol", "lifecycle", "policy"}: affects.update({"mechanism", "execution", "evidence"})
        elif classification in {"source", "authority", "custody"}: affects.add("evidence")
        else: affects.add("mechanism")
    breaking = bool(buckets["removed"]) or any(change.path.startswith("/schema") or change.path.startswith("/genome_id") for change in all_changes)
    raw = {"before_digest": before.content_digest, "after_digest": after.content_digest, "added": tuple(buckets["added"]), "removed": tuple(buckets["removed"]), "changed": tuple(buckets["changed"]), "classifications": classifications, "affected_graphs": tuple(sorted(affects)), "breaking": breaking}
    return GenomeDiff(**raw, diff_digest=digest_for(raw, domain="scaffold-arena.genome.diff"))


def _path_exists(payload: Any, pointer: str) -> bool:
    value = payload
    parent_key: str | None = None
    for segment in pointer.lstrip("/").split("/"):
        segment = segment.replace("~1", "/").replace("~0", "~")
        if isinstance(value, Mapping):
            if segment not in value: return False
            value = value[segment]
            parent_key = segment
        elif isinstance(value, list):
            value = _items(value, array_name=parent_key)
            if not isinstance(value, Mapping) or segment not in value: return False
            value = value[segment]
            parent_key = segment
        else: return False
    return True


def check_intervention_locality(
    before: GenomeDescriptor, after: GenomeDescriptor, *, target_path: str,
    operation: Literal["set", "enable", "disable", "select"], mutation_closure: tuple[str, ...] = (),
    expected_derived_paths: tuple[str, ...] = (), fixed_infrastructure_paths: tuple[str, ...] = (),
) -> LocalityResult:
    """Fail closed; this public pure function accepts no caller-owned admission expansion."""
    if operation not in {"set", "enable", "disable", "select"}:
        return LocalityResult(verdict="HOLD", code="HOLD_INTERVENTION_NONLOCAL", target_path=target_path,
                              changed_paths=(), unexpected_paths=(target_path,), limitations=("Operation is not admitted by the frozen locality policy.",))
    segments = target_path.strip("/").split("/")
    if len(segments) != 3 or segments[0] != "components" or segments[2] != "config_digest":
        return LocalityResult(verdict="HOLD", code="HOLD_INTERVENTION_NONLOCAL", target_path=target_path,
                              changed_paths=(), unexpected_paths=(target_path,), limitations=("Only a frozen component config digest may be assessed by the descriptor-only locality checker.",))
    if mutation_closure or expected_derived_paths or fixed_infrastructure_paths:
        return LocalityResult(verdict="HOLD", code="HOLD_INTERVENTION_NONLOCAL", target_path=target_path,
                              changed_paths=(), unexpected_paths=tuple(sorted(set((*mutation_closure, *expected_derived_paths, *fixed_infrastructure_paths)))),
                              limitations=("Caller-supplied mutation closures and infrastructure allowlists are not locality authority.",))
    before_payload, after_payload = descriptor_payload(before), descriptor_payload(after)
    if not _path_exists(before_payload, target_path) or not _path_exists(after_payload, target_path):
        return LocalityResult(verdict="HOLD", code="HOLD_INTERVENTION_NONLOCAL", target_path=target_path,
                              changed_paths=(), unexpected_paths=(target_path,), limitations=("Target path does not resolve in both descriptors.",))
    diff = semantic_diff(before, after)
    changed_paths = tuple(change.path for change in (*diff.added, *diff.removed, *diff.changed))
    allowed = (target_path,)
    unexpected = tuple(path for path in changed_paths if not any(path == item or path.startswith(item + "/") for item in allowed))
    if unexpected:
        return LocalityResult(verdict="HOLD", code="HOLD_INTERVENTION_NONLOCAL", target_path=target_path,
                              changed_paths=changed_paths, unexpected_paths=unexpected)
    return LocalityResult(verdict="HOLD", code="HOLD_APPLIED_CONTROL_RECEIPT_REQUIRED", target_path=target_path, changed_paths=changed_paths,
                          limitations=("Descriptor locality is not an applied-control receipt; runtime admission remains HOLD.",))


validate_intervention_locality = check_intervention_locality
