"""Lifespan-owned local runtime and explicit trusted adapter composition."""

from __future__ import annotations

import json
import math
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, insert, select

from adapters_v1 import (
    AdapterRegistry,
    LMStudioAdapter,
    NativeScaffoldAdapter,
    OllamaAdapter,
    ContextHandoffOllamaAdapter,
    OpenAICompatibleAdapter,
    ScaffoldRuntime,
)
from adapters_v1.native.bridge import RuntimeFactory
from artifacts_v1 import ArtifactStore, LocalArtifactStore, S3CompatibleArtifactStore
from auth_v1 import AuthService
from config.settings import Settings
from evaluation_v1 import EvaluationWorker, TrustedGraderRegistry
from execution_v1 import CentralPriceResolver, DurableWorker
from factors_v1 import FactorizedRecipeRouterAdapter, FactorRuntime
from persistence_v1 import ArenaRepository, AuthRepository, create_persistence_engine
from persistence_v1.schema import projects
from protocol_v1.models import HarnessCapabilities
from tasks.base import BaseTask

from .analysis import AnalysisService
from .counterfactual import CounterfactualReplayService, HarnessCIService
from .decision import DecisionService
from .evidence import EvidenceService
from .execution import ExecutionService
from .exports import StudyPackExportService
from .forge import ExperimentPlannerService, ForgeService, ProcessSafetyService
from .genome import GenomeService
from .observatory import ObservatoryService
from .registry import ProtocolRegistryService
from .review import ReviewService
from .trace_lab import TraceLabService
from .xray import XrayService

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_MIGRATIONS_ROOT = _BACKEND_ROOT / "migrations"
_CURRENT_SCAFFOLD_IDS = frozenset(
    {"bare", "plan_execute_verify", "tool_error_recovery", "memory_critique"}
)
_TEAM_ARTIFACT_READINESS_SENTINEL = b"scaffold-arena-artifact-readiness-v1\n"


def _runtime_worker_owner(configured_owner: str) -> str:
    """Distinguish concurrently started processes before they claim a lease."""
    return f"{configured_owner}-{uuid.uuid4().hex[:12]}"


class ProtocolRuntimeConfigurationError(RuntimeError):
    """Raised when local Protocol v1 persistence cannot be safely initialized."""


@dataclass(frozen=True)
class _BoundScenarioTask(BaseTask):
    """Minimal legacy-task view over a frozen, bound protocol scenario."""

    scenario: Any

    @property
    def id(self) -> str:
        return self.scenario.scenario_id

    @property
    def name(self) -> str:
        return self.scenario.title

    @property
    def subtitle(self) -> str:
        return f"{self.scenario.source_label} {self.scenario.task_family} scenario"

    @property
    def task_type(self) -> str:
        return self.scenario.task_family

    @property
    def synthetic_sources(self) -> bool:
        return (
            self.scenario.source_label == "synthetic"
            or self.scenario.data_classification == "synthetic"
        )

    def get_input_text(self) -> str:
        labels = (
            f"SOURCE LABEL: {self.scenario.source_label.upper()}",
            f"DATA CLASSIFICATION: {self.scenario.data_classification.upper()}",
        )
        contract = self.scenario.output_contract
        contract_text = (
            ()
            if contract is None
            else (
                f"OUTPUT CONTRACT: {contract.format}; {contract.description}; schema hash {contract.schema_hash}",
            )
        )
        return "\n\n".join((*labels, self.scenario.prompt, *contract_text))

    def get_schema(self) -> dict[str, Any]:
        contract = self.scenario.output_contract
        if contract is None:
            return {"$comment": "No protocol output contract was supplied."}
        kind = {"json": "object", "text": "string", "tool_call": "object"}[
            contract.format
        ]
        return {
            "type": kind,
            "$comment": f"{contract.description} (schema hash: {contract.schema_hash})",
        }

    def get_gold(self) -> dict[str, Any]:
        reference = self.scenario.reference_solution
        return {} if reference is None else reference.model_dump(mode="json")


def register_current_scaffold_components() -> None:
    """Register the closed shipped scaffold set without constructing a provider."""
    from core.registry import register_scaffold, register_task
    from scaffolds.bare import BareScaffold
    from scaffolds.memory_critique import MemoryCritiqueScaffold
    from scaffolds.plan_execute_verify import PlanExecuteVerifyScaffold
    from scaffolds.tool_error_recovery import ToolErrorRecoveryScaffold
    from tasks.extraction import ExtractionTask
    from tasks.privacy_boundary import PrivacyBoundaryTask
    from tasks.research_synthesis import ResearchSynthesisTask
    from tasks.risk_analysis import RiskAnalysisTask
    from tasks.strategy_to_system import StrategyToSystemTask
    from tasks.tool_use_recovery import ToolUseRecoveryTask

    for task in (
        ExtractionTask(),
        RiskAnalysisTask(),
        ResearchSynthesisTask(),
        ToolUseRecoveryTask(),
        PrivacyBoundaryTask(),
        StrategyToSystemTask(),
    ):
        register_task(task)
    for scaffold in (
        BareScaffold(),
        PlanExecuteVerifyScaffold(),
        ToolErrorRecoveryScaffold(),
        MemoryCritiqueScaffold(),
    ):
        register_scaffold(scaffold)


@dataclass
class ProtocolRegistryRuntime:
    service: ProtocolRegistryService
    execution_service: ExecutionService
    export_service: StudyPackExportService
    evidence_service: EvidenceService
    review_service: ReviewService
    analysis_service: AnalysisService
    decision_service: DecisionService
    trace_lab_service: TraceLabService
    genome_service: GenomeService
    xray_service: XrayService
    observatory_service: ObservatoryService
    counterfactual_replay_service: CounterfactualReplayService
    harness_ci_service: HarnessCIService
    forge_service: ForgeService
    experiment_planner_service: ExperimentPlannerService
    process_safety_service: ProcessSafetyService
    engine: Engine
    artifact_store: ArtifactStore
    artifact_connectivity_verified: bool = False
    adapter_registry: AdapterRegistry | None = None
    auth_service: AuthService | None = None

    def close(self) -> None:
        self.engine.dispose()


@dataclass
class DurableWorkerRuntime:
    """Worker-only durable composition; it is never created by API lifespan."""

    repository: ArenaRepository
    artifact_store: ArtifactStore
    adapter_registry: AdapterRegistry
    worker: DurableWorker
    evaluator: EvaluationWorker
    engine: Engine
    project_id: str
    owner: str
    lease_seconds: float
    poll_seconds: float
    artifact_connectivity_verified: bool = False

    def close(self) -> None:
        self.engine.dispose()


async def initialize_protocol_registry(
    settings: Settings,
    *,
    native_runtime_factories: Mapping[str, RuntimeFactory] | None = None,
    factor_runtimes: Mapping[str, FactorRuntime] | None = None,
    s3_client: Any | None = None,
    s3_client_factory: Callable[..., Any] | None = None,
) -> ProtocolRegistryRuntime:
    """Migrate and configure durable storage; this must only run during lifespan."""
    database_url, artifact_root = _validate_local_configuration(settings)
    engine: Engine | None = None
    try:
        engine = create_persistence_engine(database_url)
        _upgrade_schema(engine, database_url)
        repository = ArenaRepository(engine)
        personal_project_id = settings.protocol_v1_personal_project_id.strip()
        if not settings.protocol_v1_is_team_mode:
            _ensure_personal_project(repository, project_id=personal_project_id, project_name=settings.protocol_v1_personal_project_name.strip())
        artifact_store = _build_artifact_store(
            settings,
            artifact_root,
            s3_client=s3_client,
            s3_client_factory=s3_client_factory,
        )
        artifact_connectivity_verified = False
        if settings.protocol_v1_is_team_mode and settings.protocol_v1_artifact_backend == "s3_compatible":
            _verify_team_artifact_connectivity(artifact_store)
            artifact_connectivity_verified = True
        adapter_registry = await _build_configured_adapter_registry(
            settings.protocol_v1_adapter_runtime_config,
            native_runtime_factories=native_runtime_factories,
            factor_runtimes=factor_runtimes,
        )
        service = ProtocolRegistryService(
            repository,
            artifact_store,
            adapter_registry=adapter_registry,
            personal_project_id=None if settings.protocol_v1_is_team_mode else personal_project_id,
            max_body_bytes=settings.max_request_size_bytes,
        )
        counterfactual_replay_service = CounterfactualReplayService(
            repository,
            artifact_store,
            personal_project_id=None if settings.protocol_v1_is_team_mode else personal_project_id,
        )
        return ProtocolRegistryRuntime(
            service=service,
            execution_service=ExecutionService(
                repository,
                artifact_store,
                adapter_registry=adapter_registry,
                personal_project_id=None if settings.protocol_v1_is_team_mode else personal_project_id,
            ),
            export_service=StudyPackExportService(
                repository,
                artifact_store,
                personal_project_id=None if settings.protocol_v1_is_team_mode else personal_project_id,
            ),
            evidence_service=EvidenceService(
                repository,
                artifact_store,
                personal_project_id=None if settings.protocol_v1_is_team_mode else personal_project_id,
            ),
            review_service=ReviewService(
                repository,
                artifact_store,
                personal_project_id=None if settings.protocol_v1_is_team_mode else personal_project_id,
            ),
            analysis_service=AnalysisService(
                repository,
                artifact_store,
                personal_project_id=None if settings.protocol_v1_is_team_mode else personal_project_id,
            ),
            decision_service=DecisionService(
                repository,
                artifact_store,
                personal_project_id=None if settings.protocol_v1_is_team_mode else personal_project_id,
            ),
            trace_lab_service=TraceLabService(
                repository,
                personal_project_id=None if settings.protocol_v1_is_team_mode else personal_project_id,
            ),
            genome_service=GenomeService(
                repository,
                artifact_store,
                personal_project_id=None if settings.protocol_v1_is_team_mode else personal_project_id,
            ),
            xray_service=XrayService(
                repository,
                artifact_store,
                personal_project_id=None if settings.protocol_v1_is_team_mode else personal_project_id,
            ),
            observatory_service=ObservatoryService(
                repository,
                artifact_store,
                personal_project_id=None if settings.protocol_v1_is_team_mode else personal_project_id,
            ),
            counterfactual_replay_service=counterfactual_replay_service,
            harness_ci_service=HarnessCIService(
                repository,
                artifact_store,
                personal_project_id=None if settings.protocol_v1_is_team_mode else personal_project_id,
                replay_service=counterfactual_replay_service,
            ),
            forge_service=ForgeService(
                repository,
                artifact_store,
                personal_project_id=None if settings.protocol_v1_is_team_mode else personal_project_id,
            ),
            experiment_planner_service=ExperimentPlannerService(
                repository,
                artifact_store,
                personal_project_id=None if settings.protocol_v1_is_team_mode else personal_project_id,
            ),
            process_safety_service=ProcessSafetyService(
                repository,
                artifact_store,
                personal_project_id=None if settings.protocol_v1_is_team_mode else personal_project_id,
            ),
            engine=engine,
            artifact_store=artifact_store,
            artifact_connectivity_verified=artifact_connectivity_verified,
            adapter_registry=adapter_registry,
            auth_service=AuthService(AuthRepository(repository), settings) if settings.protocol_v1_is_team_mode else None,
        )
    except ProtocolRuntimeConfigurationError:
        if engine is not None:
            engine.dispose()
        raise
    except Exception as exc:
        if engine is not None:
            engine.dispose()
        raise ProtocolRuntimeConfigurationError(
            "Protocol v1 startup failed while migrating local persistence or initializing artifacts."
        ) from exc


async def initialize_durable_worker_runtime(
    settings: Settings,
    *,
    native_runtime_factories: Mapping[str, RuntimeFactory] | None = None,
    factor_runtimes: Mapping[str, FactorRuntime] | None = None,
    s3_client: Any | None = None,
    s3_client_factory: Callable[..., Any] | None = None,
) -> DurableWorkerRuntime:
    """Build the fixed worker runtime after durable dependencies are reachable.

    This deliberately does not migrate schemas or start inside the API process.
    A deployment owner applies migrations separately, then this process probes
    PostgreSQL and the bounded S3 sentinel before it can lease a job.
    """
    database_url, artifact_root = _validate_worker_configuration(settings)
    engine: Engine | None = None
    try:
        engine = create_persistence_engine(database_url)
        with engine.connect() as connection:
            connection.execute(select(1))
        repository = ArenaRepository(engine)
        artifact_store = _build_artifact_store(
            settings,
            artifact_root,
            s3_client=s3_client,
            s3_client_factory=s3_client_factory,
        )
        artifact_connectivity_verified = False
        if settings.protocol_v1_is_team_mode:
            _verify_team_artifact_connectivity(artifact_store)
            artifact_connectivity_verified = True
        adapter_registry = await _build_configured_adapter_registry(
            settings.protocol_v1_adapter_runtime_config,
            native_runtime_factories=native_runtime_factories,
            factor_runtimes=factor_runtimes,
        )
        if adapter_registry is None:
            raise ProtocolRuntimeConfigurationError(
                "worker requires a configured trusted adapter registry"
            )
        register_current_scaffold_components()
        return DurableWorkerRuntime(
            repository=repository,
            artifact_store=artifact_store,
            adapter_registry=adapter_registry,
            worker=DurableWorker(
                repository,
                adapter_registry,
                artifact_store,
                price_resolver=CentralPriceResolver(),
                project_id=settings.resolved_protocol_v1_worker_project_id,
            ),
            evaluator=EvaluationWorker(
                repository,
                artifact_store,
                TrustedGraderRegistry(),
                project_id=settings.resolved_protocol_v1_worker_project_id,
            ),
            engine=engine,
            project_id=settings.resolved_protocol_v1_worker_project_id,
            owner=_runtime_worker_owner(settings.protocol_v1_worker_owner.strip()),
            lease_seconds=settings.protocol_v1_worker_lease_seconds,
            poll_seconds=settings.protocol_v1_worker_poll_seconds,
            artifact_connectivity_verified=artifact_connectivity_verified,
        )
    except ProtocolRuntimeConfigurationError:
        if engine is not None:
            engine.dispose()
        raise
    except Exception as exc:
        if engine is not None:
            engine.dispose()
        raise ProtocolRuntimeConfigurationError(
            "durable worker startup failed while connecting persistence or artifacts"
        ) from exc


async def build_adapter_registry_from_config(
    config: Mapping[str, Any],
    *,
    native_runtime_factories: Mapping[str, RuntimeFactory] | None = None,
    factor_runtimes: Mapping[str, FactorRuntime] | None = None,
) -> AdapterRegistry:
    """Build only an allowlisted, in-memory trusted registry.

    The configuration is declarative: it has no module names, shell commands,
    uploads, discovery, or provider-start action. Native and factor semantics
    are capability-bearing Python objects injected by the runtime owner, never
    resolved from a config string.
    """
    if (
        set(config) != {"format", "adapters"}
        or config.get("format") != "scaffold-arena-adapter-runtime-v1"
    ):
        raise ProtocolRuntimeConfigurationError(
            "adapter runtime config must use the exact scaffold-arena-adapter-runtime-v1 format"
        )
    entries = config.get("adapters")
    if not isinstance(entries, list) or not entries:
        raise ProtocolRuntimeConfigurationError(
            "adapter runtime config requires a non-empty adapters list"
        )
    registry = AdapterRegistry()
    native_runtime_factories = native_runtime_factories or {}
    factor_runtimes = factor_runtimes or {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ProtocolRuntimeConfigurationError(
                "every adapter configuration must be an object"
            )
        adapter = _configured_adapter(
            dict(entry),
            native_runtime_factories=native_runtime_factories,
            factor_runtimes=factor_runtimes,
        )
        capabilities = await adapter.describe_capabilities()
        await registry.install_trusted(adapter, capabilities.adapter_digest)
    return registry


async def _build_configured_adapter_registry(
    location: str,
    *,
    native_runtime_factories: Mapping[str, RuntimeFactory] | None,
    factor_runtimes: Mapping[str, FactorRuntime] | None,
) -> AdapterRegistry | None:
    if not location.strip():
        return None
    path = Path(location).expanduser()
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ProtocolRuntimeConfigurationError(
            "adapter runtime config must be a readable JSON object"
        ) from exc
    if not isinstance(payload, dict):
        raise ProtocolRuntimeConfigurationError(
            "adapter runtime config must be a JSON object"
        )
    return await build_adapter_registry_from_config(
        payload,
        native_runtime_factories=native_runtime_factories,
        factor_runtimes=factor_runtimes,
    )


def _configured_adapter(
    entry: dict[str, Any],
    *,
    native_runtime_factories: Mapping[str, RuntimeFactory],
    factor_runtimes: Mapping[str, FactorRuntime],
) -> Any:
    kind = entry.get("kind")
    if kind == "openai_compatible_local":
        _exact_keys(
            entry,
            {"kind", "adapter_id", "adapter_digest", "endpoint", "config_schema_hash"},
            kind,
        )
        return OpenAICompatibleAdapter(
            adapter_id=_required_text(entry, "adapter_id"),
            adapter_digest=_required_text(entry, "adapter_digest"),
            endpoint=_required_text(entry, "endpoint"),
            config_schema_hash=_optional_text(entry, "config_schema_hash"),
        )
    if kind == "ollama_local":
        _exact_keys(entry, {"kind", "adapter_id", "adapter_digest", "endpoint", "config_schema_hash"}, kind)
        return OllamaAdapter(
            adapter_id=_required_text(entry, "adapter_id"),
            adapter_digest=_required_text(entry, "adapter_digest"),
            endpoint=_required_text(entry, "endpoint"),
            config_schema_hash=_optional_text(entry, "config_schema_hash"),
        )
    if kind == "context_handoff_ollama":
        _exact_keys(entry, {"kind", "adapter_id", "adapter_digest", "endpoint", "config_schema_hash"}, kind)
        return ContextHandoffOllamaAdapter(
            adapter_id=_required_text(entry, "adapter_id"),
            adapter_digest=_required_text(entry, "adapter_digest"),
            endpoint=_required_text(entry, "endpoint"),
            config_schema_hash=_required_text(entry, "config_schema_hash"),
        )
    if kind == "lm_studio_local":
        _exact_keys(entry, {"kind", "adapter_id", "adapter_digest", "endpoint", "runtime_revision", "model_artifact_digest", "config_schema_hash"}, kind)
        return LMStudioAdapter(
            adapter_id=_required_text(entry, "adapter_id"),
            adapter_digest=_required_text(entry, "adapter_digest"),
            endpoint=_required_text(entry, "endpoint"),
            runtime_revision=_required_text(entry, "runtime_revision"),
            model_artifact_digest=_required_text(entry, "model_artifact_digest"),
            config_schema_hash=_optional_text(entry, "config_schema_hash"),
        )
    if kind == "native_current_scaffold":
        _exact_keys(
            entry,
            {
                "kind",
                "adapter_id",
                "adapter_digest",
                "scaffold_id",
                "runtime_ref",
                "capabilities",
                "config_schema_hash",
            },
            kind,
        )
        scaffold_id = entry.get("scaffold_id")
        runtime_ref = entry.get("runtime_ref")
        if (scaffold_id is None) == (runtime_ref is None):
            raise ProtocolRuntimeConfigurationError(
                "native_current_scaffold requires exactly one of scaffold_id or injected runtime_ref"
            )
        if scaffold_id is not None:
            if (
                not isinstance(scaffold_id, str)
                or scaffold_id not in _CURRENT_SCAFFOLD_IDS
            ):
                raise ProtocolRuntimeConfigurationError(
                    "native scaffold_id is not in the shipped current-scaffold allowlist"
                )
            runtime_factory = _current_scaffold_runtime_factory(scaffold_id)
        else:
            runtime_ref = _required_text(entry, "runtime_ref")
            try:
                runtime_factory = native_runtime_factories[runtime_ref]
            except KeyError as exc:
                raise ProtocolRuntimeConfigurationError(
                    "native runtime_ref is not explicitly injected into this process"
                ) from exc
        capabilities = HarnessCapabilities.model_validate(entry.get("capabilities", {}))
        return NativeScaffoldAdapter(
            adapter_id=_required_text(entry, "adapter_id"),
            adapter_digest=_required_text(entry, "adapter_digest"),
            runtime_factory=runtime_factory,
            capabilities=capabilities,
            config_schema_hash=_optional_text(entry, "config_schema_hash"),
        )
    if kind == "factorized_pvrm":
        _exact_keys(entry, {"kind", "adapter", "runtime_ref"}, kind)
        runtime_ref = _required_text(entry, "runtime_ref")
        try:
            runtime = factor_runtimes[runtime_ref]
        except KeyError as exc:
            raise ProtocolRuntimeConfigurationError(
                "factor runtime_ref is not explicitly injected into this process"
            ) from exc
        base = entry.get("adapter")
        if not isinstance(base, dict) or base.get("kind") == "factorized_pvrm":
            raise ProtocolRuntimeConfigurationError(
                "factorized_pvrm requires one non-factorized inline trusted adapter"
            )
        return FactorizedRecipeRouterAdapter(
            adapter=_configured_adapter(
                base,
                native_runtime_factories=native_runtime_factories,
                factor_runtimes=factor_runtimes,
            ),
            runtime=runtime,
        )
    if kind == "bundled_offline_demo_fixture":
        _exact_keys(entry, {"kind"}, kind)
        # This is deliberately not parameterized: it is a repository-bundled,
        # hash-checked synthetic fixture replay, never uploaded pack code or a
        # caller-provided fixture-result map.
        from adapters_v1.offline_fixture import OfflineDemoFixtureAdapter

        return OfflineDemoFixtureAdapter()
    raise ProtocolRuntimeConfigurationError("adapter kind is not allowlisted")


def _current_scaffold_runtime_factory(scaffold_id: str) -> RuntimeFactory:
    """Create a worker-only factory for one shipped current scaffold ID."""
    if scaffold_id not in _CURRENT_SCAFFOLD_IDS:
        raise ProtocolRuntimeConfigurationError(
            "native scaffold_id is not in the shipped current-scaffold allowlist"
        )

    def factory(_harness: Any, input: Any) -> ScaffoldRuntime:
        # These imports and the provider constructor are intentionally inside
        # execution. Building the API registry and healthchecking it remains
        # provider-free.
        from core.provider import get_provider
        from core.registry import get_scaffold
        from core.run_lifecycle import RunOptions

        attempt = input.attempt
        timeout_seconds = math.ceil(
            min(_harness.timeout_seconds, attempt.budget.max_latency_seconds)
        )
        options = RunOptions(
            temperature=0.0,
            max_output_tokens=attempt.budget.max_tokens,
            timeout_s=timeout_seconds,
        )
        return ScaffoldRuntime(
            scaffold=get_scaffold(scaffold_id),
            task=_BoundScenarioTask(input.scenario),
            provider=get_provider(attempt.provider_model),
            options=options,
            run_id=f"native-{attempt.attempt_id}",
        )

    return factory


def _exact_keys(value: Mapping[str, Any], allowed: set[str], kind: object) -> None:
    unknown = set(value) - allowed
    missing = {"kind"} - set(value)
    if unknown or missing:
        raise ProtocolRuntimeConfigurationError(
            f"{kind} adapter configuration contains unsupported or missing keys"
        )


def _required_text(value: Mapping[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result.strip():
        raise ProtocolRuntimeConfigurationError(
            f"adapter configuration requires non-empty {key}"
        )
    return result.strip()


def _optional_text(value: Mapping[str, Any], key: str) -> str | None:
    result = value.get(key)
    if result is None:
        return None
    return _required_text(value, key)


def _validate_local_configuration(settings: Settings) -> tuple[str, Path | None]:
    if settings.protocol_v1_is_team_mode:
        try:
            settings.validate_protocol_v1_team_configuration()
        except RuntimeError as exc:
            raise ProtocolRuntimeConfigurationError(
                "Protocol runtime configuration is invalid."
            ) from exc
        if settings.protocol_v1_artifact_backend == "s3_compatible":
            return settings.protocol_v1_database_url.strip(), None
        artifact_root = settings.resolved_protocol_v1_artifact_root.expanduser()
        if artifact_root.exists() and not artifact_root.is_dir():
            raise ProtocolRuntimeConfigurationError("protocol_v1_artifact_root must identify a writable directory.")
        return settings.protocol_v1_database_url.strip(), artifact_root
    database_url = settings.resolved_protocol_v1_database_url
    if (
        not database_url.startswith("sqlite:///")
        or database_url == "sqlite:///:memory:"
        or "?" in database_url
    ):
        raise ProtocolRuntimeConfigurationError(
            "protocol_v1_database_url must be a durable local SQLite URL in personal mode."
        )
    database_path = Path(database_url.removeprefix("sqlite:///"))
    if not database_path.name or (database_path.exists() and database_path.is_dir()):
        raise ProtocolRuntimeConfigurationError(
            "protocol_v1_database_url must identify a SQLite database file, not a directory."
        )
    artifact_root = settings.resolved_protocol_v1_artifact_root.expanduser()
    if not str(artifact_root) or (
        artifact_root.exists() and not artifact_root.is_dir()
    ):
        raise ProtocolRuntimeConfigurationError(
            "protocol_v1_artifact_root must identify a writable local directory."
        )
    if (
        not settings.protocol_v1_personal_project_id.strip()
        or not settings.protocol_v1_personal_project_name.strip()
    ):
        raise ProtocolRuntimeConfigurationError(
            "protocol_v1_personal_project_id and protocol_v1_personal_project_name are required."
        )
    return database_url, artifact_root


def _validate_worker_configuration(settings: Settings) -> tuple[str, Path | None]:
    try:
        settings.validate_protocol_v1_worker_configuration()
    except RuntimeError as exc:
        raise ProtocolRuntimeConfigurationError(
            "Protocol worker configuration is invalid."
        ) from exc
    return _validate_local_configuration(settings)


def _build_artifact_store(
    settings: Settings,
    artifact_root: Path | None,
    *,
    s3_client: Any | None,
    s3_client_factory: Callable[..., Any] | None,
) -> ArtifactStore:
    if settings.protocol_v1_is_team_mode and settings.protocol_v1_artifact_backend == "s3_compatible":
        return S3CompatibleArtifactStore(
            settings.protocol_v1_s3_bucket.strip(),
            endpoint_url=settings.protocol_v1_s3_endpoint_url.strip(),
            region_name=settings.protocol_v1_s3_region_name.strip(),
            prefix=settings.protocol_v1_s3_prefix.strip(),
            path_style=settings.protocol_v1_s3_path_style,
            max_artifact_bytes=settings.protocol_v1_s3_max_artifact_bytes,
            client=s3_client,
            client_factory=s3_client_factory,
        )
    if artifact_root is None:
        raise ProtocolRuntimeConfigurationError("local artifacts are unavailable without protocol_v1_artifact_root")
    return LocalArtifactStore(artifact_root)


def _verify_team_artifact_connectivity(artifact_store: ArtifactStore) -> None:
    """Verify only read/write connectivity for a fixed, non-sensitive sentinel."""
    try:
        digest = artifact_store.put_bytes(
            _TEAM_ARTIFACT_READINESS_SENTINEL,
            media_type="application/octet-stream",
        )
        if artifact_store.get_bytes(digest) != _TEAM_ARTIFACT_READINESS_SENTINEL:
            raise ValueError("sentinel content mismatch")
    except (OSError, RuntimeError, ValueError, FileNotFoundError):
        raise ProtocolRuntimeConfigurationError(
            "team artifact storage readiness probe failed; startup is blocked"
        ) from None


def _upgrade_schema(engine: Engine, database_url: str) -> None:
    config = Config()
    config.set_main_option("script_location", str(_MIGRATIONS_ROOT))
    config.set_main_option("sqlalchemy.url", database_url)
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def _ensure_personal_project(
    repository: ArenaRepository, *, project_id: str, project_name: str
) -> None:
    with repository.transaction(immediate=True) as connection:
        exists = connection.execute(
            select(projects.c.id).where(projects.c.id == project_id)
        ).scalar_one_or_none()
        if exists is None:
            connection.execute(
                insert(projects).values(id=project_id, name=project_name)
            )
