"""Generate the public Protocol v1 JSON Schema exports from Pydantic models."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend"))

from analysis_v1 import DecisionAdmissionRequest
from evidence_v1 import (
    DerivedEvidenceRequest,
    EvidenceAdmissionRequest,
    EvidenceReceipt,
    ReproductionReceipt,
    ReproductionRequest,
)
from protocol_v1.models import (
    AggregateBudgetSpec,
    AttemptEnvelope,
    BudgetSpec,
    Episode,
    EvaluationRecord,
    ExecutionProvenance,
    ExperimentSpec,
    FactorSpec,
    GraderSpec,
    HarnessSpec,
    OutcomeVector,
    ProtocolReadinessReport,
    ScenarioSpec,
    StudyPack,
    TraceEvent,
)
from review_v1 import (
    AdjudicationSubmission,
    AnnotationBatch,
    AnnotationSubmission,
    CalibrationAdjudicationResult,
    CalibrationAnnotationResult,
    HumanRubric,
)
from genome_v1 import AtlasCitationManifest, AtlasReleaseDigest, GenomeDescriptor, GraphProjection, HarnessMechanismAtlas, StandardsCatalog
from observatory_v1 import ObservatoryReport, ObservatoryRequest
from replay_v1 import (
    CounterfactualReplayReport,
    CounterfactualReplayRequest,
    HarnessCIReport,
    HarnessCIRequest,
)
from forge_v1.models import (
    EvolutionReceipt,
    ForgeApproval,
    ForgeEvaluation,
    ForgeProposal,
    NextBestExperimentReport,
    NextBestExperimentRequest,
    ProcessSafetyReport,
    ProcessSafetyRequest,
)
from xray_v1 import XRayReport, XRayRequest, XraySourceSnapshot

DEFAULT_OUTPUT_DIRECTORY = REPOSITORY_ROOT / "specs" / "v1"
PUBLIC_SCHEMA_BASE = "https://scaffold-arena.local/specs/v1/"

SCHEMA_MODELS = (
    ("analysis-v1-decision-admission-request.schema.json", DecisionAdmissionRequest),
    ("aggregate-budget.schema.json", AggregateBudgetSpec),
    ("attempt-envelope.schema.json", AttemptEnvelope),
    ("budget.schema.json", BudgetSpec),
    ("episode.schema.json", Episode),
    ("evaluation-record.schema.json", EvaluationRecord),
    ("evidence-v1-admission-request.schema.json", EvidenceAdmissionRequest),
    ("evidence-v1-derived-request.schema.json", DerivedEvidenceRequest),
    ("evidence-v1-evidence-receipt.schema.json", EvidenceReceipt),
    ("evidence-v1-reproduction-receipt.schema.json", ReproductionReceipt),
    ("evidence-v1-reproduction-request.schema.json", ReproductionRequest),
    ("execution-provenance.schema.json", ExecutionProvenance),
    ("experiment.schema.json", ExperimentSpec),
    ("factor.schema.json", FactorSpec),
    ("grader-spec.schema.json", GraderSpec),
    ("genome-descriptor.schema.json", GenomeDescriptor),
    ("genome-graph-projection.schema.json", GraphProjection),
    ("genome-standards-catalog.schema.json", StandardsCatalog),
    ("harness-mechanism-atlas.schema.json", HarnessMechanismAtlas),
    ("harness-mechanism-atlas-citation-manifest.schema.json", AtlasCitationManifest),
    ("harness-mechanism-atlas-release-digest.schema.json", AtlasReleaseDigest),
    ("harness.schema.json", HarnessSpec),
    ("outcome-vector.schema.json", OutcomeVector),
    ("protocol-readiness-report.schema.json", ProtocolReadinessReport),
    ("review-v1-adjudication-submission.schema.json", AdjudicationSubmission),
    ("review-v1-annotation-batch.schema.json", AnnotationBatch),
    ("review-v1-annotation-submission.schema.json", AnnotationSubmission),
    ("review-v1-calibration-adjudication-result.schema.json", CalibrationAdjudicationResult),
    ("review-v1-calibration-annotation-result.schema.json", CalibrationAnnotationResult),
    ("review-v1-human-rubric.schema.json", HumanRubric),
    ("scenario.schema.json", ScenarioSpec),
    ("study-pack.schema.json", StudyPack),
    ("trace-event.schema.json", TraceEvent),
    ("xray-v1-request.schema.json", XRayRequest),
    ("xray-v1-report.schema.json", XRayReport),
    ("xray-v1-source-snapshot.schema.json", XraySourceSnapshot),
    ("observatory-v1-request.schema.json", ObservatoryRequest),
    ("observatory-v1-report.schema.json", ObservatoryReport),
    ("counterfactual-replay-v1-request.schema.json", CounterfactualReplayRequest),
    ("counterfactual-replay-v1-report.schema.json", CounterfactualReplayReport),
    ("harness-ci-v1-request.schema.json", HarnessCIRequest),
    ("harness-ci-v1-report.schema.json", HarnessCIReport),
    ("forge-v1-proposal.schema.json", ForgeProposal),
    ("forge-v1-approval.schema.json", ForgeApproval),
    ("forge-v1-evaluation.schema.json", ForgeEvaluation),
    ("forge-v1-evolution-receipt.schema.json", EvolutionReceipt),
    ("next-best-experiment-v1-request.schema.json", NextBestExperimentRequest),
    ("next-best-experiment-v1-report.schema.json", NextBestExperimentReport),
    ("process-safety-v1-request.schema.json", ProcessSafetyRequest),
    ("process-safety-v1-report.schema.json", ProcessSafetyReport),
)


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def _model_schema(filename: str, model: type[Any]) -> dict[str, Any]:
    schema = model.model_json_schema(mode="validation")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"{PUBLIC_SCHEMA_BASE}{filename}"
    return schema


def _protocol_index() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"{PUBLIC_SCHEMA_BASE}protocol.schema.json",
        "title": "Scaffold Arena Protocol v1",
        "description": "Stable public index generated from active Protocol v1, evidence, review, X-Ray, and Observatory contracts.",
        "oneOf": [{"$ref": filename} for filename, _ in SCHEMA_MODELS],
    }


def generated_schemas() -> dict[str, bytes]:
    schemas = {filename: _json_bytes(_model_schema(filename, model)) for filename, model in SCHEMA_MODELS}
    bound = _model_schema("genome-descriptor-bound.schema.json", GenomeDescriptor)
    bound["title"] = "Bound Harness Genome v1 descriptor"
    bound["description"] = "Registration schema: genome_digest is required and must bind canonical descriptor bytes."
    bound.setdefault("required", []).append("genome_digest")
    bound["required"] = sorted(set(bound["required"]))
    schemas["genome-descriptor-bound.schema.json"] = _json_bytes(bound)
    schemas["protocol.schema.json"] = _json_bytes(_protocol_index())
    for contents in schemas.values():
        Draft202012Validator.check_schema(json.loads(contents))
    return schemas


def generate(output_directory: Path) -> None:
    output_directory.mkdir(parents=True, exist_ok=True)
    for filename, contents in generated_schemas().items():
        (output_directory / filename).write_bytes(contents)


def check(output_directory: Path) -> list[str]:
    expected = generated_schemas()
    return [
        filename
        for filename, contents in expected.items()
        if not (path := output_directory / filename).is_file() or path.read_bytes() != contents
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if generated schemas differ without writing")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIRECTORY, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.check:
        stale = check(args.output_dir)
        if stale:
            print("Protocol v1 schemas are stale or missing:", ", ".join(stale), file=sys.stderr)
            return 1
        print(f"Protocol v1 schemas are current ({len(generated_schemas())} files).")
        return 0

    generate(args.output_dir)
    print(f"Generated {len(generated_schemas())} Protocol v1 schemas in {args.output_dir}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
