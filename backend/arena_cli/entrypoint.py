"""Composable installed CLI entry point for Scaffold Arena."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from collections.abc import Callable, Sequence
from typing import Any

from .analysis_plan import assess_file
from .cli import build_parser as build_base_parser


def _emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, default=str, sort_keys=True))


def _genome_from_path(path: str):
    from genome_v1 import GenomeDescriptor

    return GenomeDescriptor.model_validate_json(Path(path).read_text(encoding="utf-8"))


def command_genome_validate(args: argparse.Namespace) -> int:
    try:
        from genome_v1 import genome_digest

        descriptor = _genome_from_path(args.path)
        if descriptor.genome_digest != genome_digest(descriptor):
            raise ValueError("digest mismatch")
    except (OSError, TypeError, ValueError):
        _emit({"verdict": "HOLD", "code": "genome_invalid", "provider_execution_started": False})
        return 2
    _emit({"verdict": "PASS", "genome_id": descriptor.genome_id, "genome_digest": descriptor.genome_digest, "claim_ceiling": "local descriptor validation only; no runtime, safety, deployment, or truth claim", "provider_execution_started": False})
    return 0


def command_genome_catalog(args: argparse.Namespace) -> int:
    from genome_v1 import load_standards_catalog

    rows = [row.model_dump(mode="json") for row in load_standards_catalog() if args.protocol is None or row.standard_id == args.protocol]
    _emit({"verdict": "PASS", "standards": rows, "claim_ceiling": "catalog metadata only; no runtime support implied", "provider_execution_started": False})
    return 0


def command_genome_diff(args: argparse.Namespace) -> int:
    try:
        from genome_v1 import semantic_diff

        result = semantic_diff(_genome_from_path(args.before), _genome_from_path(args.after))
    except (OSError, TypeError, ValueError):
        _emit({"verdict": "HOLD", "code": "genome_diff_invalid", "provider_execution_started": False})
        return 2
    _emit({"verdict": "PASS", **result.model_dump(mode="json"), "provider_execution_started": False})
    return 0


def command_genome_project(args: argparse.Namespace) -> int:
    if args.format != "json":
        _emit({"verdict": "HOLD", "code": "genome_projection_format_unavailable", "provider_execution_started": False})
        return 2
    try:
        from genome_v1 import project_graph

        result = project_graph(_genome_from_path(args.path))
    except (OSError, TypeError, ValueError):
        _emit({"verdict": "HOLD", "code": "genome_projection_invalid", "provider_execution_started": False})
        return 2
    _emit({"verdict": "PASS", **result.model_dump(mode="json"), "provider_execution_started": False})
    return 0


def command_genome_certify(args: argparse.Namespace) -> int:
    try:
        from genome_v1 import certify_descriptor

        result = certify_descriptor(_genome_from_path(args.path))
    except (OSError, TypeError, ValueError):
        _emit({"verdict": "HOLD", "code": "genome_certification_invalid", "provider_execution_started": False})
        return 2
    _emit(result.model_dump(mode="json"))
    return 0 if result.verdict == "PASS" else 2


def command_acp_registry(_: argparse.Namespace) -> int:
    _emit({"verdict": "HOLD", "code": "acp_operator_registry_required", "prerequisite": "ACP registry snapshots are server/operator-owned, content-addressed deployment configuration; this public CLI cannot admit a caller-supplied identity or argv.", "provider_execution_started": False})
    return 2


def command_acp_hold(_: argparse.Namespace) -> int:
    _emit({"verdict": "HOLD", "code": "acp_operator_identity_required", "prerequisite": "Use a captured, digest-bound, operator-approved ACP identity and fixed isolation policy through the API deployment configuration.", "provider_execution_started": False})
    return 2


def _subcommands(
    parser: argparse.ArgumentParser,
    *,
    destination: str,
) -> argparse.Action:
    for action in parser._actions:
        if action.dest == destination and hasattr(action, "choices"):
            return action
    raise RuntimeError(f"CLI subcommand destination is unavailable: {destination}")


def command_experiment_analysis_plan(args: argparse.Namespace) -> int:
    code, payload = assess_file(args.spec)
    print(json.dumps(payload, default=str, sort_keys=True))
    return code


def build_parser() -> argparse.ArgumentParser:
    """Compose additive public commands over the stable protocol-v1 CLI."""

    parser = build_base_parser()
    commands = _subcommands(parser, destination="command")
    experiment = commands.choices["experiment"]  # type: ignore[attr-defined]
    experiment_commands = _subcommands(
        experiment,
        destination="experiment_command",
    )
    if "analysis-plan" in experiment_commands.choices:  # type: ignore[attr-defined]
        raise RuntimeError("analysis-plan command is already registered")
    planning = experiment_commands.add_parser(  # type: ignore[attr-defined]
        "analysis-plan",
        help="assess frozen binary-outcome adequacy without starting a provider",
        description=(
            "Assess the strict org.scaffold-arena.analysis-plan extension in a "
            "protocol-v1 ExperimentSpec without reading results or starting a provider."
        ),
    )
    planning.add_argument("--spec", required=True)
    planning.set_defaults(handler=command_experiment_analysis_plan)
    genome = commands.add_parser("genome", help="inspect strict Harness Genome v1 descriptors without starting providers")  # type: ignore[attr-defined]
    genome_commands = genome.add_subparsers(dest="genome_command", required=True)
    validate = genome_commands.add_parser("validate")
    validate.add_argument("--path", required=True); validate.set_defaults(handler=command_genome_validate)
    inspect = genome_commands.add_parser("inspect")
    inspect.add_argument("--path", required=True); inspect.set_defaults(handler=command_genome_validate)
    catalog = genome_commands.add_parser("catalog")
    catalog.add_argument("--protocol"); catalog.set_defaults(handler=command_genome_catalog)
    diff = genome_commands.add_parser("diff")
    diff.add_argument("--before", required=True); diff.add_argument("--after", required=True); diff.set_defaults(handler=command_genome_diff)
    project = genome_commands.add_parser("project")
    project.add_argument("--path", required=True); project.add_argument("--format", choices=["json", "mermaid"], default="json"); project.set_defaults(handler=command_genome_project)
    certify = genome_commands.add_parser("certify")
    certify.add_argument("--path", required=True); certify.add_argument("--checks", choices=["schema,canonical,fixture"], default="schema,canonical,fixture"); certify.set_defaults(handler=command_genome_certify)
    acp = commands.add_parser("acp", help="bounded ACP v1 bridge controls")  # type: ignore[attr-defined]
    acp_commands = acp.add_subparsers(dest="acp_command", required=True)
    registry = acp_commands.add_parser("registry"); registry.set_defaults(handler=command_acp_registry)
    for name in ("certify", "run", "cancel"):
        child = acp_commands.add_parser(name)
        if name == "certify": child.add_argument("--agent-id", required=True); child.add_argument("--fixture", required=True)
        elif name == "run": child.add_argument("--agent-id", required=True); child.add_argument("--prompt-file", required=True); child.add_argument("--workspace", required=True); child.add_argument("--policy", required=True)
        else: child.add_argument("--bridge-id", required=True)
        child.set_defaults(handler=command_acp_hold)
    harness = commands.add_parser("harness", help="compatibility alias for provider-free Harness Genome inspection")  # type: ignore[attr-defined]
    harness_commands = harness.add_subparsers(dest="harness_command", required=True)
    harness_catalog = harness_commands.add_parser("catalog")
    harness_catalog.add_argument("--protocol"); harness_catalog.set_defaults(handler=command_genome_catalog)
    harness_inspect = harness_commands.add_parser("inspect")
    harness_inspect.add_argument("--path", required=True); harness_inspect.set_defaults(handler=command_genome_validate)
    harness_diff = harness_commands.add_parser("diff")
    harness_diff.add_argument("--before", required=True); harness_diff.add_argument("--after", required=True); harness_diff.set_defaults(handler=command_genome_diff)
    adapter = commands.choices["adapter"]  # type: ignore[attr-defined]
    adapter_commands = _subcommands(adapter, destination="adapter_command")
    adapter_init = adapter_commands.add_parser("init")
    adapter_init.set_defaults(handler=command_acp_hold)
    adapter_verify = adapter_commands.add_parser("verify")
    adapter_verify.set_defaults(handler=command_acp_hold)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler: Callable[[argparse.Namespace], int] = args.handler
    return handler(args)


__all__ = ["build_parser", "main"]
