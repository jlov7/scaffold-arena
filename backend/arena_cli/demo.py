"""One-command, no-provider Scaffold Arena fixture demonstration."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from adapters_v1.offline_fixture import (
    OfflineDemoFixtureAdapter,
    bundled_study_pack_root,
)
from protocol_v1 import StudyPack, expand_design
from protocol_v1.canonical import sha256_bytes

from .provenance import collect_study_pack_provenance

_FACTOR_IDS = ("planning", "verification", "recovery", "memory")
_FULL_EXECUTION_COMMAND = (
    "cd backend && uv run pytest "
    "tests/study_packs_v1/test_offline_demo_v1.py "
    "tests/integration_v1/test_offline_demo_fixture_chain.py -q"
)


class DemoWorkspaceError(ValueError):
    """The demo cannot safely create or verify its workspace."""


def _default_repository_root() -> Path:
    current = Path(__file__).resolve()
    for ancestor in current.parents:
        if (ancestor / ".git").is_dir():
            return ancestor
        if ancestor.name == "backend" and (ancestor / "pyproject.toml").is_file():
            return ancestor.parent
    # Installed wheels do not carry repository metadata. Bind the local CLI
    # package and state the unversioned-source limitation rather than scanning
    # an entire site-packages or interpreter tree.
    return current.parent


def run_demo(
    path: str | Path,
    *,
    repository_root: str | Path | None = None,
) -> dict[str, Any]:
    """Create a verified fixture workspace and return a bounded decision card.

    This is a fast replay of the hash-pinned synthetic truth table. It verifies
    fixture bytes, declarative coverage, control behavior, and a descriptive
    main-effect summary without invoking a model or provider. All mutable work
    occurs in a same-parent staging directory; the requested path appears only
    after the complete workspace has been written and verified.
    """

    requested = Path(path).expanduser()
    if requested.is_symlink():
        raise DemoWorkspaceError("workspace_symlink_forbidden")
    workspace = requested.resolve()
    preexisting_empty = False
    if workspace.exists():
        if not workspace.is_dir() or any(workspace.iterdir()):
            raise DemoWorkspaceError("workspace_not_empty")
        preexisting_empty = True

    source_pack = bundled_study_pack_root()
    root = (
        Path(repository_root).expanduser().resolve()
        if repository_root is not None
        else _default_repository_root()
    )
    # Capture code/environment state before creating staging content so an
    # in-repository destination cannot contaminate its own provenance.
    provenance = collect_study_pack_provenance(
        repository_root=root,
        study_pack_path=source_pack / "study-pack.json",
    )

    workspace.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{workspace.name}.staging-",
            dir=workspace.parent,
        )
    )
    published = False
    removed_preexisting = False
    try:
        summary = _build_staged_demo(
            staging=staging,
            final_workspace=workspace,
            source_pack=source_pack,
            provenance=provenance.model_dump(mode="json"),
        )
        _sync_tree(staging)

        if workspace.exists():
            if not workspace.is_dir() or any(workspace.iterdir()):
                raise DemoWorkspaceError("workspace_changed_before_publish")
            workspace.rmdir()
            removed_preexisting = True
        try:
            os.rename(staging, workspace)
        except OSError:
            if removed_preexisting and preexisting_empty and not workspace.exists():
                workspace.mkdir()
            raise
        published = True
        _sync_directory(workspace.parent)
        return summary
    finally:
        if not published and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if (
            not published
            and removed_preexisting
            and preexisting_empty
            and not workspace.exists()
        ):
            workspace.mkdir()


def _build_staged_demo(
    *,
    staging: Path,
    final_workspace: Path,
    source_pack: Path,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    arena_dir = staging / ".arena"
    arena_dir.mkdir(parents=True, exist_ok=True)
    (arena_dir / "config.json").write_text(
        json.dumps({"format": "scaffold-arena-workspace-v1"}, indent=2) + "\n",
        encoding="utf-8",
    )

    copied_pack = staging / "study_packs" / "offline-demo-v1"
    shutil.copytree(source_pack, copied_pack)

    # Construction verifies every bundled fixture and the complete 5 x 16
    # scenario/treatment truth table against source-pinned SHA-256 identities.
    OfflineDemoFixtureAdapter()
    pack_path = copied_pack / "study-pack.json"
    pack = StudyPack.model_validate_json(pack_path.read_bytes())
    if pack.study_pack_id != "offline-demo-v1" or pack.version != "1.0.0":
        raise DemoWorkspaceError("unexpected bundled StudyPack identity")

    truth_path = copied_pack / "fixtures" / "runtime-truth-table.json"
    truth_bytes = truth_path.read_bytes()
    expected_truth_digest = str(
        pack.harnesses[0].configuration["fixture_truth_table_sha256"]
    )
    if sha256_bytes(truth_bytes) != expected_truth_digest:
        raise DemoWorkspaceError("copied fixture truth table digest mismatch")
    truth = json.loads(truth_bytes)
    rows = truth.get("rows")
    if not isinstance(rows, list):
        raise DemoWorkspaceError("fixture truth table rows are invalid")

    experiment = pack.experiments[0]
    expected_attempts = (
        len(expand_design(experiment))
        * len(experiment.scenario_ids)
        * len(experiment.harness_ids)
        * max(len(experiment.model_endpoints), 1)
        * experiment.repetitions
    )
    if len(rows) != expected_attempts:
        raise DemoWorkspaceError(
            "fixture truth table does not match the declared design expansion"
        )

    candidate_ids = {
        scenario.scenario_id
        for scenario in pack.scenarios
        if scenario.control_role == "candidate"
    }
    candidate_rows = [row for row in rows if row["scenario_id"] in candidate_ids]
    main_effects = []
    for factor_id in _FACTOR_IDS:
        enabled = [
            row["case_state"] == "completed"
            for row in candidate_rows
            if row["assignment"][factor_id] is True
        ]
        disabled = [
            row["case_state"] == "completed"
            for row in candidate_rows
            if row["assignment"][factor_id] is False
        ]
        if not enabled or not disabled:
            raise DemoWorkspaceError(
                f"fixture truth table is unbalanced for factor {factor_id}"
            )
        enabled_rate = sum(enabled) / len(enabled)
        disabled_rate = sum(disabled) / len(disabled)
        main_effects.append(
            {
                "factor_id": factor_id,
                "enabled_success_rate": enabled_rate,
                "disabled_success_rate": disabled_rate,
                "risk_difference": enabled_rate - disabled_rate,
                "enabled_rows": len(enabled),
                "disabled_rows": len(disabled),
            }
        )

    controls: dict[str, dict[str, int | float]] = {}
    grouped: dict[str, list[bool]] = defaultdict(list)
    for row in rows:
        grouped[str(row["scenario_id"])].append(row["case_state"] == "completed")
    for scenario_id, outcomes in sorted(grouped.items()):
        controls[scenario_id] = {
            "rows": len(outcomes),
            "completion_rate": sum(outcomes) / len(outcomes),
        }

    provenance_path = arena_dir / "provenance.json"
    provenance_path.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    final_pack = final_workspace / "study_packs" / "offline-demo-v1"
    final_provenance = final_workspace / ".arena" / "provenance.json"
    summary: dict[str, Any] = {
        "verdict": "PASS",
        "mode": "verified_fixture_replay",
        "evidence_class": "fixture",
        "provider_execution_started": False,
        "study_pack": f"{pack.study_pack_id}@{pack.version}",
        "workspace": str(final_workspace),
        "bundled_study_pack": str(final_pack),
        "provenance": str(final_provenance),
        "expected_attempts": expected_attempts,
        "verified_truth_table_rows": len(rows),
        "truth_table_digest": expected_truth_digest,
        "decision": {
            "status": "DESCRIPTIVE_ONLY",
            "summary": (
                "In the synthetic recorded candidate cohort, planning and "
                "verification have the largest descriptive success-rate "
                "differences; this is protocol demonstration evidence, not "
                "a model or causal performance claim."
            ),
            "main_effects": main_effects,
            "scenario_controls": controls,
        },
        "claim_ceiling": str(truth["claim_ceiling"]),
        "limitations": [
            "synthetic recorded fixtures only",
            "no provider or model was invoked",
            "descriptive fixture effects are not empirical or causal effects",
            "workspace publication is atomic only within the selected parent filesystem",
            "run the full execution command to exercise durable workers, evaluation, analysis, and evidence",
        ],
        "full_execution_command": _FULL_EXECUTION_COMMAND,
        "next_actions": [
            "Inspect the copied StudyPack and preregistration.",
            "Run the full execution command for the durable 80-attempt fixture chain.",
            "Connect and certify a real adapter before attempting live evidence.",
        ],
    }
    summary_path = arena_dir / "demo-summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    # Verify the exact public files that must exist after the final rename.
    for required in (
        arena_dir / "config.json",
        provenance_path,
        summary_path,
        pack_path,
        truth_path,
    ):
        if not required.is_file():
            raise DemoWorkspaceError("staged demo workspace is incomplete")
    return summary


def _sync_tree(root: Path) -> None:
    """Best-effort durability before atomic publication on POSIX filesystems."""

    if not hasattr(os, "fsync"):
        return
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            with path.open("rb") as source:
                os.fsync(source.fileno())
        except OSError:
            # The workspace remains hash-verified; unsupported fsync is an
            # environmental durability limitation, not permission to publish
            # partial content.
            continue
    for path in sorted(
        (item for item in root.rglob("*") if item.is_dir()),
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        _sync_directory(path)
    _sync_directory(root)


def _sync_directory(path: Path) -> None:
    if not hasattr(os, "O_DIRECTORY"):
        return
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        os.fsync(descriptor)
    except OSError:
        return
    finally:
        if descriptor is not None:
            os.close(descriptor)
