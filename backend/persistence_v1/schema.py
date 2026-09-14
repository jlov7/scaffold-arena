"""Canonical SQLAlchemy Core metadata for the durable v1 boundary."""

from __future__ import annotations

from sqlalchemy import (
    DDL,
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    event,
    func,
)

metadata = MetaData(
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)


def _created() -> Column[DateTime]:
    return Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    )


projects = Table(
    "projects",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("name", String(255), nullable=False),
    Column("description", Text, nullable=True),
    _created(),
)
users = Table(
    "users",
    metadata,
    Column("id", String(64), primary_key=True),
    Column(
        "project_id",
        String(64),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("email", String(320), nullable=True),
    Column("display_name", String(255), nullable=True),
    _created(),
    UniqueConstraint("project_id", "email", name="project_email"),
)
artifacts = Table(
    "artifacts",
    metadata,
    Column("digest", String(64), primary_key=True),
    Column("size_bytes", Integer, nullable=False),
    Column(
        "media_type",
        String(255),
        nullable=False,
        server_default="application/octet-stream",
    ),
    Column("storage_uri", Text, nullable=False),
    Column("metadata_json", JSON, nullable=False, default=dict),
    _created(),
    CheckConstraint("size_bytes >= 0", name="nonnegative_size"),
    CheckConstraint("length(digest) = 64", name="sha256_digest"),
)
study_packs = Table(
    "study_packs",
    metadata,
    Column("id", String(64), primary_key=True),
    Column(
        "project_id",
        String(64),
        ForeignKey("projects.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("pack_key", String(128), nullable=False),
    Column("version", String(64), nullable=False),
    Column(
        "content_digest",
        String(64),
        ForeignKey("artifacts.digest", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("content_metadata", JSON, nullable=False, default=dict),
    _created(),
    UniqueConstraint("project_id", "pack_key", "version", name="project_pack_version"),
    CheckConstraint("length(version) > 0", name="nonempty_version"),
)
experiments = Table(
    "experiments",
    metadata,
    Column("id", String(64), primary_key=True),
    Column(
        "project_id",
        String(64),
        ForeignKey("projects.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "study_pack_id",
        String(64),
        ForeignKey("study_packs.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("name", String(255), nullable=False),
    Column("protocol_version", String(32), nullable=False),
    Column("spec_hash", String(64), nullable=True),
    Column("study_pack_hash", String(64), nullable=True),
    Column(
        "predecessor_id",
        String(64),
        ForeignKey("experiments.id", ondelete="RESTRICT"),
        nullable=True,
    ),
    Column("owner_approval", String(16), nullable=False, server_default="pending"),
    Column("definition", JSON, nullable=False, default=dict),
    Column("frozen_at", DateTime(timezone=True), nullable=True),
    _created(),
    CheckConstraint(
        "owner_approval IN ('pending', 'approved', 'rejected')",
        name="valid_owner_approval",
    ),
    CheckConstraint(
        "spec_hash IS NULL OR length(spec_hash) = 64", name="spec_hash_digest"
    ),
    CheckConstraint(
        "study_pack_hash IS NULL OR length(study_pack_hash) = 64",
        name="study_pack_hash_digest",
    ),
)
event.listen(
    experiments,
    "after_create",
    DDL("""
    CREATE TRIGGER experiments_reject_frozen_updates
    BEFORE UPDATE ON experiments
    WHEN OLD.frozen_at IS NOT NULL
    BEGIN
      SELECT RAISE(ABORT, 'frozen experiments are immutable');
    END
    """).execute_if(dialect="sqlite"),
)
event.listen(
    experiments,
    "after_create",
    DDL("""
    CREATE OR REPLACE FUNCTION scaffold_arena_reject_frozen_experiment_update()
    RETURNS trigger AS $$
    BEGIN
      IF OLD.frozen_at IS NOT NULL THEN
        RAISE EXCEPTION 'frozen experiments are immutable';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """).execute_if(dialect="postgresql"),
)
event.listen(
    experiments,
    "after_create",
    DDL("""
    CREATE TRIGGER experiments_reject_frozen_updates
    BEFORE UPDATE ON experiments
    FOR EACH ROW EXECUTE FUNCTION scaffold_arena_reject_frozen_experiment_update()
    """).execute_if(dialect="postgresql"),
)
executions = Table(
    "executions",
    metadata,
    Column("id", String(64), primary_key=True),
    Column(
        "experiment_id",
        String(64),
        ForeignKey("experiments.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("status", String(32), nullable=False),
    Column("parameters", JSON, nullable=False, default=dict),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    _created(),
    CheckConstraint(
        "status IN ('queued', 'running', 'completed', 'failed', 'cancelled', 'legacy_local_unverified')",
        name="valid_status",
    ),
)
episodes = Table(
    "episodes",
    metadata,
    Column("id", String(64), primary_key=True),
    Column(
        "execution_id",
        String(64),
        ForeignKey("executions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("ordinal", Integer, nullable=False),
    Column("scenario_id", String(128), nullable=True),
    Column("metadata_json", JSON, nullable=False, default=dict),
    _created(),
    UniqueConstraint("execution_id", "ordinal", name="execution_ordinal"),
    CheckConstraint("ordinal >= 0", name="nonnegative_ordinal"),
)
attempts = Table(
    "attempts",
    metadata,
    Column("id", String(64), primary_key=True),
    Column(
        "episode_id",
        String(64),
        ForeignKey("episodes.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("ordinal", Integer, nullable=False),
    Column("status", String(32), nullable=False, server_default="pending"),
    Column("request_metadata", JSON, nullable=False, default=dict),
    Column("result_metadata", JSON, nullable=False, default=dict),
    _created(),
    UniqueConstraint("episode_id", "ordinal", name="episode_ordinal"),
    CheckConstraint("ordinal >= 0", name="nonnegative_ordinal"),
)
jobs = Table(
    "jobs",
    metadata,
    Column("id", String(64), primary_key=True),
    Column(
        "execution_id",
        String(64),
        ForeignKey("executions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "attempt_id",
        String(64),
        ForeignKey("attempts.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("kind", String(64), nullable=False),
    Column("status", String(32), nullable=False, server_default="queued"),
    Column("lease_owner", String(255), nullable=True),
    Column("lease_token", String(64), nullable=True),
    Column("lease_expires_at", DateTime(timezone=True), nullable=True),
    Column("heartbeat_at", DateTime(timezone=True), nullable=True),
    Column("attempt_count", Integer, nullable=True),
    Column("available_at", DateTime(timezone=True), nullable=True),
    Column("cancel_requested_at", DateTime(timezone=True), nullable=True),
    Column("payload", JSON, nullable=False, default=dict),
    _created(),
    CheckConstraint(
        "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
        name="valid_status",
    ),
    CheckConstraint(
        "attempt_count IS NULL OR attempt_count >= 0", name="nonnegative_attempt_count"
    ),
    UniqueConstraint("attempt_id", "kind", name="attempt_kind"),
)
attempt_events = Table(
    "attempt_events",
    metadata,
    Column("id", String(64), primary_key=True),
    Column(
        "attempt_id",
        String(64),
        ForeignKey("attempts.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "execution_id",
        String(64),
        ForeignKey("executions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("sequence", Integer, nullable=False),
    Column("execution_sequence", Integer, nullable=False),
    Column("event_type", String(128), nullable=False),
    Column("payload", JSON, nullable=False, default=dict),
    _created(),
    UniqueConstraint("attempt_id", "sequence", name="attempt_sequence"),
    UniqueConstraint(
        "execution_id", "execution_sequence", name="execution_event_sequence"
    ),
    CheckConstraint("sequence > 0", name="positive_sequence"),
    CheckConstraint("execution_sequence > 0", name="positive_execution_sequence"),
)
execution_event_cursors = Table(
    "execution_event_cursors",
    metadata,
    Column(
        "execution_id",
        String(64),
        ForeignKey("executions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("last_sequence", Integer, nullable=False),
    CheckConstraint("last_sequence >= 0", name="nonnegative_last_sequence"),
)
evaluations = Table(
    "evaluations",
    metadata,
    Column("id", String(64), primary_key=True),
    Column(
        "attempt_id",
        String(64),
        ForeignKey("attempts.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("evaluator", String(128), nullable=False),
    Column("score", Float, nullable=True),
    Column("result", JSON, nullable=False, default=dict),
    _created(),
    Column(
        "project_id",
        String(64),
        ForeignKey("projects.id", ondelete="RESTRICT"),
        nullable=True,
    ),
    Column("batch_id", String(64), nullable=True),
    Column("evaluator_version", String(128), nullable=True),
    Column("evaluator_digest", String(64), nullable=True),
    Column("input_artifact_digest", String(64), nullable=True),
    Column("output_artifact_digest", String(64), nullable=True),
    Column("trace_artifact_digest", String(64), nullable=True),
    Column("grader_plan", JSON, nullable=True),
    Column("result_hash", String(64), nullable=True),
    Column("result_artifact_digest", String(64), nullable=True),
    Column("cost_status", String(16), nullable=True),
    Column("cost_usd", Float, nullable=True),
    Column("exclusion_state", String(32), nullable=True),
    Column("adjudication_state", String(32), nullable=True),
    UniqueConstraint("attempt_id", name="evaluation_attempt"),
)
annotations = Table(
    "annotations",
    metadata,
    Column("id", String(64), primary_key=True),
    Column(
        "attempt_id",
        String(64),
        ForeignKey("attempts.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "user_id",
        String(64),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("kind", String(64), nullable=False),
    Column("body", JSON, nullable=False, default=dict),
    _created(),
    Column(
        "project_id",
        String(64),
        ForeignKey("projects.id", ondelete="RESTRICT"),
        nullable=True,
    ),
    Column("batch_id", String(64), nullable=True),
    Column("item_id", String(128), nullable=True),
    Column("annotator_pseudonym", String(128), nullable=True),
    Column("assignment_hash", String(64), nullable=True),
    Column("score", Float, nullable=True),
    UniqueConstraint("assignment_hash", name="annotations_assignment_hash"),
)
annotation_batches = Table(
    "annotation_batches",
    metadata,
    Column("id", String(64), primary_key=True),
    Column(
        "project_id",
        String(64),
        ForeignKey("projects.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("batch_hash", String(64), nullable=False),
    Column("protocol_hash", String(64), nullable=False),
    Column("evaluator", String(128), nullable=False),
    Column("evaluator_version", String(128), nullable=False),
    Column("evaluator_digest", String(64), nullable=False),
    Column("grader_plan", JSON, nullable=False),
    Column("request_json", JSON, nullable=False),
    _created(),
    UniqueConstraint("project_id", "batch_hash", name="project_batch_hash"),
    CheckConstraint(
        "length(batch_hash) = 64 AND length(protocol_hash) = 64 AND length(evaluator_digest) = 64",
        name="batch_digests",
    ),
)
annotation_assignments = Table(
    "annotation_assignments",
    metadata,
    Column("id", String(64), primary_key=True),
    Column(
        "batch_id",
        String(64),
        ForeignKey("annotation_batches.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("item_id", String(128), nullable=False),
    Column(
        "attempt_id",
        String(64),
        ForeignKey("attempts.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("annotator_pseudonym", String(128), nullable=False),
    Column(
        "blind_payload_digest",
        String(64),
        ForeignKey("artifacts.digest", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("assignment_hash", String(64), nullable=False),
    Column(
        "identity_state",
        String(32),
        nullable=False,
        server_default="identity_unverified",
    ),
    _created(),
    UniqueConstraint(
        "batch_id", "item_id", "annotator_pseudonym", name="batch_item_pseudonym"
    ),
    UniqueConstraint("assignment_hash", name="assignment_hash"),
    CheckConstraint(
        "length(blind_payload_digest) = 64 AND length(assignment_hash) = 64",
        name="assignment_digests",
    ),
)
annotation_adjudications = Table(
    "annotation_adjudications",
    metadata,
    Column("id", String(64), primary_key=True),
    Column(
        "batch_id",
        String(64),
        ForeignKey("annotation_batches.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("item_id", String(128), nullable=False),
    Column("adjudicator_pseudonym", String(128), nullable=False),
    Column("final_score", Float, nullable=False),
    Column("decision", String(128), nullable=False),
    Column("rationale", Text, nullable=False),
    Column(
        "evidence_ref",
        String(64),
        ForeignKey("artifacts.digest", ondelete="RESTRICT"),
        nullable=False,
    ),
    _created(),
    UniqueConstraint("batch_id", "item_id", name="batch_item_adjudication"),
    CheckConstraint("final_score >= 0 AND final_score <= 1", name="adjudication_score"),
)
annotation_adjudication_dimensions = Table(
    "annotation_adjudication_dimensions",
    metadata,
    Column(
        "adjudication_id",
        String(64),
        ForeignKey(
            "annotation_adjudications.id",
            ondelete="CASCADE",
            name="fk_adjudication_dimensions_adjudication",
        ),
        primary_key=True,
    ),
    Column("metric_id", String(128), primary_key=True),
    Column("score", Float, nullable=False),
    CheckConstraint("score >= 0 AND score <= 1", name="score_range"),
)
Index("ix_evaluations_project_batch", evaluations.c.project_id, evaluations.c.batch_id)
Index("ix_annotations_project_batch", annotations.c.project_id, annotations.c.batch_id)
evidence_receipts = Table(
    "evidence_receipts",
    metadata,
    Column("id", String(64), primary_key=True),
    Column(
        "execution_id",
        String(64),
        ForeignKey("executions.id", ondelete="RESTRICT"),
        nullable=True,
    ),
    Column(
        "artifact_digest",
        String(64),
        ForeignKey("artifacts.digest", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("receipt_kind", String(64), nullable=False),
    Column("claims", JSON, nullable=False, default=list),
    _created(),
    # Legacy columns above remain so the additive migration can preserve prior rows.
    # New durable receipts are validated by EvidenceService before they are stored.
    Column(
        "project_id",
        String(64),
        ForeignKey("projects.id", ondelete="RESTRICT"),
        nullable=True,
    ),
    Column("manifest_hash", String(64), nullable=True),
    Column("receipt_hash", String(64), nullable=True),
    Column("manifest_json", JSON, nullable=True),
    Column("artifact_hashes", JSON, nullable=True),
    Column("claim_ceiling", Text, nullable=True),
    Column("integrity_not_truth", Boolean, nullable=True),
    CheckConstraint(
        "manifest_hash IS NULL OR length(manifest_hash) = 64",
        name="manifest_hash_digest",
    ),
    CheckConstraint(
        "receipt_hash IS NULL OR length(receipt_hash) = 64", name="receipt_hash_digest"
    ),
    UniqueConstraint("receipt_hash", name="evidence_receipts_receipt_hash"),
)
evidence_receipt_artifacts = Table(
    "evidence_receipt_artifacts",
    metadata,
    Column(
        "receipt_id",
        String(64),
        ForeignKey("evidence_receipts.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "artifact_digest",
        String(64),
        ForeignKey("artifacts.digest", ondelete="RESTRICT"),
        primary_key=True,
    ),
)
reproductions = Table(
    "reproductions",
    metadata,
    Column("id", String(64), primary_key=True),
    Column(
        "source_execution_id",
        String(64),
        ForeignKey("executions.id", ondelete="RESTRICT"),
        nullable=True,
    ),
    Column(
        "reproduction_execution_id",
        String(64),
        ForeignKey("executions.id", ondelete="RESTRICT"),
        nullable=True,
    ),
    Column("status", String(32), nullable=False),
    Column("result", JSON, nullable=False, default=dict),
    _created(),
    Column(
        "project_id",
        String(64),
        ForeignKey("projects.id", ondelete="RESTRICT"),
        nullable=True,
    ),
    Column(
        "original_evidence_receipt_id",
        String(64),
        ForeignKey(
            "evidence_receipts.id",
            ondelete="RESTRICT",
            name="fk_reproductions_original_receipt",
        ),
        nullable=True,
    ),
    Column(
        "reproduced_evidence_receipt_id",
        String(64),
        ForeignKey(
            "evidence_receipts.id",
            ondelete="RESTRICT",
            name="fk_reproductions_reproduced_receipt",
        ),
        nullable=True,
    ),
    Column("reproduction_hash", String(64), nullable=True),
    Column("receipt_json", JSON, nullable=True),
    Column("external_attestation", JSON, nullable=True),
    Column("claim_ceiling", Text, nullable=True),
    Column("integrity_not_truth", Boolean, nullable=True),
    CheckConstraint(
        "reproduction_hash IS NULL OR length(reproduction_hash) = 64",
        name="reproduction_hash_digest",
    ),
    UniqueConstraint("reproduction_hash", name="reproductions_reproduction_hash"),
)
audit_events = Table(
    "audit_events",
    metadata,
    Column("id", String(64), primary_key=True),
    Column(
        "project_id",
        String(64),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "actor_user_id",
        String(64),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("event_type", String(128), nullable=False),
    Column("payload", JSON, nullable=False, default=dict),
    _created(),
)
idempotency_records = Table(
    "idempotency_records",
    metadata,
    Column("id", String(64), primary_key=True),
    Column(
        "project_id",
        String(64),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("key", String(255), nullable=False),
    Column("request_digest", String(64), nullable=False),
    Column("response", JSON, nullable=False, default=dict),
    _created(),
    UniqueConstraint("project_id", "key", name="project_key"),
    CheckConstraint("length(request_digest) = 64", name="request_digest"),
)

# The bundled offline demonstration is an explicitly local, single-flight
# fixture.  Its admission state is intentionally separate from generic
# execution idempotency: provenance is captured before an execution exists and
# must remain bound to the browser key across process restarts.
offline_demo_admissions = Table(
    "offline_demo_admissions",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("project_id", String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
    Column("key", String(128), nullable=False),
    Column("experiment_id", String(64), nullable=False),
    Column("provenance", JSON, nullable=True),
    Column("execution_id", String(64), ForeignKey("executions.id", ondelete="SET NULL"), nullable=True),
    Column("reservation_expires_at", DateTime(timezone=True), nullable=True),
    _created(),
    UniqueConstraint("project_id", "key", name="offline_demo_project_key"),
    CheckConstraint("length(key) BETWEEN 1 AND 128", name="offline_demo_key_length"),
)

# A fixed row is locked transactionally by every offline-demo admission.  It
# bounds the fixture globally without changing generic execution semantics.
offline_demo_runtime_locks = Table(
    "offline_demo_runtime_locks",
    metadata,
    Column("scope", String(64), primary_key=True),
    Column("admission_id", String(64), ForeignKey("offline_demo_admissions.id", name="fk_offline_demo_lock_admission", ondelete="SET NULL"), nullable=True),
    _created(),
)
usage_ledger = Table(
    "usage_ledger",
    metadata,
    Column("id", String(64), primary_key=True),
    Column(
        "execution_id",
        String(64),
        ForeignKey("executions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "attempt_id",
        String(64),
        ForeignKey("attempts.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("model_id", String(255), nullable=False),
    Column("input_tokens", Integer, nullable=True),
    Column("output_tokens", Integer, nullable=True),
    Column("total_tokens", Integer, nullable=True),
    Column("context_tokens", Integer, nullable=True),
    Column("tool_calls", Integer, nullable=True),
    Column("reserved_max_tokens", Integer, nullable=True),
    Column("reserved_max_tool_calls", Integer, nullable=True),
    Column("cost_status", String(16), nullable=False),
    Column("cost_usd", Float, nullable=True),
    Column("reserved_cost_usd", Float, nullable=True),
    Column("estimated_cost_usd", Float, nullable=True),
    Column("actual_cost_usd", Float, nullable=True),
    Column("price_catalog_revision", String(128), nullable=True),
    Column("provider_usage_digest", String(64), nullable=True),
    _created(),
    CheckConstraint(
        "(input_tokens IS NULL OR input_tokens >= 0) AND "
        "(output_tokens IS NULL OR output_tokens >= 0) AND "
        "(total_tokens IS NULL OR total_tokens >= 0) AND "
        "(context_tokens IS NULL OR context_tokens >= 0) AND "
        "(tool_calls IS NULL OR tool_calls >= 0) AND "
        "(reserved_max_tokens IS NULL OR reserved_max_tokens >= 0) AND "
        "(reserved_max_tool_calls IS NULL OR reserved_max_tool_calls >= 0)",
        name="nonnegative_usage",
    ),
    CheckConstraint(
        "cost_status IN ('reserved', 'estimated', 'reconciled', 'unknown', 'mismatch')",
        name="valid_cost_status",
    ),
    CheckConstraint(
        "cost_status != 'unknown' OR (cost_usd IS NULL AND actual_cost_usd IS NULL)",
        name="unknown_cost_is_null",
    ),
    CheckConstraint(
        "cost_status != 'reconciled' OR (cost_usd IS NOT NULL AND actual_cost_usd IS NOT NULL AND price_catalog_revision IS NOT NULL AND provider_usage_digest IS NOT NULL AND length(provider_usage_digest) = 64 AND input_tokens IS NOT NULL AND output_tokens IS NOT NULL AND total_tokens IS NOT NULL AND total_tokens = input_tokens + output_tokens AND context_tokens IS NOT NULL AND tool_calls IS NOT NULL)",
        name="reconciled_cost_evidence",
    ),
    CheckConstraint(
        "(cost_usd IS NULL OR cost_usd >= 0) AND (reserved_cost_usd IS NULL OR reserved_cost_usd >= 0) AND (estimated_cost_usd IS NULL OR estimated_cost_usd >= 0) AND (actual_cost_usd IS NULL OR actual_cost_usd >= 0)",
        name="nonnegative_costs",
    ),
)
price_catalog = Table(
    "price_catalog",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("revision", String(128), nullable=False),
    Column("model_id", String(255), nullable=False),
    Column("provider", String(128), nullable=False),
    Column("billing_profile", String(128), nullable=False, server_default="standard"),
    Column("input_usd_per_million", Float, nullable=False),
    Column("output_usd_per_million", Float, nullable=False),
    Column("effective_at", DateTime(timezone=True), nullable=False),
    Column("source", Text, nullable=False),
    _created(),
    UniqueConstraint(
        "revision",
        "model_id",
        "provider",
        "billing_profile",
        "effective_at",
        name="revision_model_provider_profile_effective",
    ),
    CheckConstraint(
        "input_usd_per_million >= 0 AND output_usd_per_million >= 0",
        name="nonnegative_prices",
    ),
)

# An AnalysisReport is an immutable interpretation of one completed execution.
# It is intentionally separate from evaluations: evaluations remain the source
# evidence and an analysis can never replace or amend them.
analysis_reports = Table(
    "analysis_reports",
    metadata,
    Column("id", String(64), primary_key=True),
    Column(
        "project_id",
        String(64),
        ForeignKey("projects.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "experiment_id",
        String(64),
        ForeignKey("experiments.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "execution_id",
        String(64),
        ForeignKey("executions.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("spec_hash", String(64), nullable=False),
    Column("study_pack_hash", String(64), nullable=False),
    Column("configuration_digest", String(64), nullable=False),
    Column("input_digest", String(64), nullable=False),
    Column("report_digest", String(64), nullable=False),
    Column(
        "artifact_digest",
        String(64),
        ForeignKey("artifacts.digest", ondelete="RESTRICT"),
        nullable=False,
    ),
    _created(),
    UniqueConstraint("execution_id", name="analysis_reports_execution"),
    CheckConstraint(
        "length(spec_hash) = 64 AND length(study_pack_hash) = 64 AND "
        "length(configuration_digest) = 64 AND length(input_digest) = 64 AND "
        "length(report_digest) = 64 AND length(artifact_digest) = 64",
        name="analysis_report_digests",
    ),
)
Index(
    "ix_analysis_reports_project_experiment",
    analysis_reports.c.project_id,
    analysis_reports.c.experiment_id,
)

# A DecisionBrief is an immutable, project-scoped interpretation of one durable
# AnalysisReport.  The paired brief and ledger are content-addressed artifacts;
# their contents are intentionally not exposed by the metadata endpoint.
decision_briefs = Table(
    "decision_briefs",
    metadata,
    Column("id", String(64), primary_key=True),
    Column(
        "project_id",
        String(64),
        ForeignKey("projects.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "analysis_report_id",
        String(64),
        ForeignKey("analysis_reports.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "experiment_id",
        String(64),
        ForeignKey("experiments.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "execution_id",
        String(64),
        ForeignKey("executions.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("report_digest", String(64), nullable=False),
    Column("request_digest", String(64), nullable=False),
    Column("brief_hash", String(64), nullable=False),
    Column("ledger_hash", String(64), nullable=False),
    Column(
        "brief_artifact_digest",
        String(64),
        ForeignKey("artifacts.digest", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "ledger_artifact_digest",
        String(64),
        ForeignKey("artifacts.digest", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("verdict", String(16), nullable=False),
    Column("claim_ceiling", String(64), nullable=False),
    Column("claim_refs", JSON, nullable=False, default=list),
    _created(),
    UniqueConstraint("analysis_report_id", name="decision_briefs_analysis_report"),
    CheckConstraint(
        "length(report_digest) = 64 AND length(request_digest) = 64 AND "
        "length(brief_hash) = 64 AND length(ledger_hash) = 64 AND "
        "length(brief_artifact_digest) = 64 AND length(ledger_artifact_digest) = 64",
        name="decision_brief_digests",
    ),
    CheckConstraint("verdict IN ('PASS', 'HOLD', 'REJECT')", name="decision_brief_verdict"),
)
Index("ix_decision_briefs_project_created", decision_briefs.c.project_id, decision_briefs.c.created_at)

Index("ix_study_packs_project_pack", study_packs.c.project_id, study_packs.c.pack_key)
Index(
    "ix_executions_experiment_created",
    executions.c.experiment_id,
    executions.c.created_at,
)
Index(
    "ix_attempt_events_attempt_sequence",
    attempt_events.c.attempt_id,
    attempt_events.c.sequence,
)
Index(
    "ix_attempt_events_execution_sequence",
    attempt_events.c.execution_id,
    attempt_events.c.execution_sequence,
)
Index("ix_jobs_status_available", jobs.c.status, jobs.c.available_at)
Index(
    "ix_audit_events_project_created",
    audit_events.c.project_id,
    audit_events.c.created_at,
)
Index(
    "ix_usage_ledger_execution_created",
    usage_ledger.c.execution_id,
    usage_ledger.c.created_at,
)
Index(
    "ix_evidence_receipts_project_created",
    evidence_receipts.c.project_id,
    evidence_receipts.c.created_at,
)
Index(
    "ix_reproductions_project_created",
    reproductions.c.project_id,
    reproductions.c.created_at,
)

# Team identity is deliberately separate from the historical project-local
# ``users`` table. An OIDC identity is globally keyed by issuer + subject;
# project access is granted only through this membership table.
identity_users = Table(
    "identity_users",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("issuer", Text, nullable=False),
    Column("subject", String(512), nullable=False),
    Column("email", String(320), nullable=True),
    Column("display_name", String(255), nullable=True),
    _created(),
    UniqueConstraint("issuer", "subject", name="identity_issuer_subject"),
)
project_memberships = Table(
    "project_memberships",
    metadata,
    Column("project_id", String(64), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
    Column("identity_user_id", String(64), ForeignKey("identity_users.id", ondelete="CASCADE"), primary_key=True),
    Column("role", String(16), nullable=False),
    _created(),
    CheckConstraint("role IN ('admin', 'operator', 'reviewer', 'viewer')", name="membership_role"),
)
auth_sessions = Table(
    "auth_sessions",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("token_digest", String(64), nullable=False, unique=True),
    Column("identity_user_id", String(64), ForeignKey("identity_users.id", ondelete="CASCADE"), nullable=False),
    Column("csrf_token", String(128), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
    Column("rotated_from_id", String(64), ForeignKey("auth_sessions.id", ondelete="SET NULL"), nullable=True),
    Column("last_seen_at", DateTime(timezone=True), nullable=True),
    _created(),
    CheckConstraint("length(token_digest) = 64", name="session_token_digest"),
)
oidc_login_transactions = Table(
    "oidc_login_transactions",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("state_digest", String(64), nullable=False, unique=True),
    Column("browser_binding_digest", String(64), nullable=False),
    Column("nonce", String(128), nullable=False),
    Column("code_verifier", String(256), nullable=False),
    Column("redirect_uri", Text, nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("consumed_at", DateTime(timezone=True), nullable=True),
    _created(),
    CheckConstraint("length(state_digest) = 64", name="oidc_state_digest"),
    CheckConstraint("length(browser_binding_digest) = 64", name="oidc_browser_binding_digest"),
)
team_settings = Table(
    "team_settings",
    metadata,
    Column("project_id", String(64), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
    Column("retention_days", Integer, nullable=True),
    Column("updated_by_identity_user_id", String(64), ForeignKey("identity_users.id", ondelete="SET NULL"), nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
    CheckConstraint("retention_days IS NULL OR retention_days BETWEEN 1 AND 3650", name="retention_days_range"),
)
deletion_plans = Table(
    "deletion_plans",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("project_id", String(64), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
    Column("state", String(16), nullable=False),
    Column("snapshot_digest", String(64), nullable=False),
    Column("confirmation_digest", String(64), nullable=False),
    Column("grace_seconds", Integer, nullable=False),
    Column("due_at", DateTime(timezone=True), nullable=False),
    Column("scheduled_by_identity_user_id", String(64), ForeignKey("identity_users.id", ondelete="SET NULL"), nullable=True),
    Column("cancelled_at", DateTime(timezone=True), nullable=True),
    Column("cancelled_by_identity_user_id", String(64), ForeignKey("identity_users.id", ondelete="SET NULL"), nullable=True),
    Column("executed_at", DateTime(timezone=True), nullable=True),
    Column("executed_by_identity_user_id", String(64), ForeignKey("identity_users.id", ondelete="SET NULL"), nullable=True),
    Column("purged_idempotency_records", Integer, nullable=True),
    _created(),
    CheckConstraint("state IN ('scheduled', 'cancelled', 'executed', 'blocked')", name="deletion_plan_state"),
    CheckConstraint("length(snapshot_digest) = 64 AND length(confirmation_digest) = 64", name="deletion_plan_digests"),
    CheckConstraint("grace_seconds BETWEEN 60 AND 2592000", name="deletion_plan_grace"),
    CheckConstraint("purged_idempotency_records IS NULL OR purged_idempotency_records >= 0", name="deletion_plan_purge_count"),
)
Index("ix_deletion_plans_project_due", deletion_plans.c.project_id, deletion_plans.c.due_at)
deletion_tombstones = Table(
    "deletion_tombstones",
    metadata,
    Column("id", String(64), primary_key=True),
    # No project FK: this record must outlive a project and its membership graph.
    Column("project_id", String(64), nullable=False),
    Column("plan_id", String(64), nullable=False, unique=True),
    Column("snapshot_digest", String(64), nullable=False),
    Column("export_manifest_digest", String(64), ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=False),
    Column("purged_idempotency_records", Integer, nullable=False),
    Column("claim_ceiling", Text, nullable=False),
    Column(
        "executed_by_identity_user_id",
        String(64),
        ForeignKey(
            "identity_users.id",
            ondelete="SET NULL",
            name="fk_tombstones_executed_identity",
        ),
        nullable=True,
    ),
    _created(),
    CheckConstraint("length(snapshot_digest) = 64 AND length(export_manifest_digest) = 64", name="deletion_tombstone_digests"),
    CheckConstraint("purged_idempotency_records >= 0", name="deletion_tombstone_purge_count"),
)
event.listen(
    deletion_tombstones,
    "after_create",
    DDL("""
    CREATE TRIGGER deletion_tombstones_no_update
    BEFORE UPDATE ON deletion_tombstones
    BEGIN SELECT RAISE(ABORT, 'deletion tombstones are append-only'); END;
    """).execute_if(dialect="sqlite"),
)
event.listen(
    deletion_tombstones,
    "after_create",
    DDL("""
    CREATE TRIGGER deletion_tombstones_no_delete
    BEFORE DELETE ON deletion_tombstones
    BEGIN SELECT RAISE(ABORT, 'deletion tombstones are append-only'); END;
    """).execute_if(dialect="sqlite"),
)
event.listen(
    deletion_tombstones,
    "after_create",
    DDL("""
    CREATE FUNCTION scaffold_arena_deletion_tombstone_append_only() RETURNS trigger AS $$
    BEGIN RAISE EXCEPTION 'deletion tombstones are append-only'; RETURN NULL; END;
    $$ LANGUAGE plpgsql;
    CREATE TRIGGER deletion_tombstones_no_mutation
    BEFORE UPDATE OR DELETE ON deletion_tombstones
    FOR EACH ROW EXECUTE FUNCTION scaffold_arena_deletion_tombstone_append_only();
    """).execute_if(dialect="postgresql"),
)
team_audit_events = Table(
    "team_audit_events",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("request_id", String(64), nullable=False),
    Column("project_id", String(64), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=True),
    Column("identity_user_id", String(64), ForeignKey("identity_users.id", ondelete="SET NULL"), nullable=True),
    Column("event_type", String(128), nullable=False),
    Column("method", String(16), nullable=True),
    Column("path", Text, nullable=True),
    Column("payload", JSON, nullable=False, default=dict),
    _created(),
)
Index("ix_team_audit_events_project_created", team_audit_events.c.project_id, team_audit_events.c.created_at)
Index("ix_auth_sessions_identity_expires", auth_sessions.c.identity_user_id, auth_sessions.c.expires_at)

# Genome v1 keeps the complete immutable descriptor in the artifact store.  These
# tables are deliberately query indexes, not a second mutable component authority.
genomes = Table(
    "genomes",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("project_id", String(64), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
    Column("schema", String(64), nullable=False),
    Column("digest", String(64), nullable=False),
    Column("descriptor_artifact_digest", String(64), ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=False),
    Column("authority_status", String(32), nullable=False),
    Column("claim_ceiling", Text, nullable=False),
    _created(),
    UniqueConstraint("project_id", "digest", name="uq_genomes_project_digest"),
    CheckConstraint("length(digest) = 64 AND length(descriptor_artifact_digest) = 64", name="genomes_digests"),
)
genome_sources = Table(
    "genome_sources",
    metadata,
    Column("genome_id", String(128), ForeignKey("genomes.id", ondelete="CASCADE"), primary_key=True),
    Column("source_id", String(128), primary_key=True),
    Column("uri", Text, nullable=False),
    Column("revision", Text, nullable=True),
    Column("content_digest", String(64), nullable=True),
    Column("source_date", String(10), nullable=True),
    Column("license_spdx", String(128), nullable=True),
    Column("provenance", String(32), nullable=False),
)
genome_certifications = Table(
    "genome_certifications",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("genome_id", String(128), ForeignKey("genomes.id", ondelete="RESTRICT"), nullable=False),
    Column("checker_digest", String(64), nullable=False),
    Column("result_artifact_digest", String(64), ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=False),
    Column("verdict", String(16), nullable=False),
    Column("authority_ceiling", String(64), nullable=False),
    _created(),
    CheckConstraint("verdict IN ('PASS', 'HOLD', 'FAIL')", name="genome_certification_verdict"),
)
acp_registry_snapshots = Table(
    "acp_registry_snapshots",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("project_id", String(64), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
    Column("registry_schema_version", String(64), nullable=False),
    Column("source_revision", Text, nullable=True),
    Column("content_digest", String(64), ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=False),
    Column("captured_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("id", "project_id", name="uq_acp_snapshot_id_project"),
)
acp_identities = Table(
    "acp_identities",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("project_id", String(64), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
    Column("snapshot_id", String(128), ForeignKey("acp_registry_snapshots.id", ondelete="RESTRICT"), nullable=False),
    Column("agent_id", String(128), nullable=False), Column("version", String(128), nullable=False),
    Column("distribution_ref", Text, nullable=False), Column("distribution_digest", String(64), nullable=False),
    Column("argv_digest", String(64), nullable=False), Column("license_spdx", String(128), nullable=True),
    Column("approval_status", String(32), nullable=False, server_default="pending"),
    UniqueConstraint("project_id", "snapshot_id", "agent_id", name="uq_acp_identity_project_snapshot_agent"),
    UniqueConstraint("id", "project_id", name="uq_acp_identity_id_project"),
    ForeignKeyConstraint(["snapshot_id", "project_id"], ["acp_registry_snapshots.id", "acp_registry_snapshots.project_id"], name="fk_acp_identity_snapshot_project"),
)
acp_bridge_runs = Table(
    "acp_bridge_runs",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("project_id", String(64), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
    Column("identity_id", String(128), ForeignKey("acp_identities.id", ondelete="RESTRICT"), nullable=False),
    Column("policy_digest", String(64), nullable=False), Column("status", String(32), nullable=False),
    Column("transcript_artifact_digest", String(64), ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=True),
    Column("receipt_artifact_digest", String(64), ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=True),
    Column("cancellation_status", String(32), nullable=False), _created(),
    ForeignKeyConstraint(["identity_id", "project_id"], ["acp_identities.id", "acp_identities.project_id"], name="fk_acp_run_identity_project"),
)
Index("ix_genomes_project_created", genomes.c.project_id, genomes.c.created_at)
Index("ix_acp_bridge_runs_project_created", acp_bridge_runs.c.project_id, acp_bridge_runs.c.created_at)
# X-Ray stores immutable caller-captured source snapshots.  The source bytes
# live in the artifact store; this is only a project-scoped custody index.
xray_snapshots = Table(
    "xray_snapshots",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("project_id", String(64), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
    Column("source_digest", String(64), ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=False),
    Column("source_name", String(255), nullable=False),
    Column("source_uri", Text, nullable=True),
    Column("source_revision", Text, nullable=True),
    Column("captured_at", DateTime(timezone=True), nullable=False),
    Column("claim_ceiling", Text, nullable=False),
    _created(),
    UniqueConstraint("project_id", "source_digest", name="uq_xray_snapshots_project_digest"),
    CheckConstraint("length(source_digest) = 64", name="xray_snapshot_digest"),
)
xray_findings = Table(
    "xray_findings",
    metadata,
    Column("snapshot_id", String(128), ForeignKey("xray_snapshots.id", ondelete="CASCADE"), primary_key=True),
    Column("finding_id", String(128), primary_key=True),
    Column("evidence_state", String(16), nullable=False),
    Column("statement_digest", String(64), nullable=False),
    CheckConstraint("evidence_state IN ('declared', 'observed', 'inferred', 'verified', 'unsupported', 'unknown')", name="xray_finding_state"),
    CheckConstraint("length(statement_digest) = 64", name="xray_finding_digest"),
)
# Observatory reports bind an exact ordered projection of persisted attempt
# events. They deliberately contain no mutable summary counters.
observatory_reports = Table(
    "observatory_reports",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("project_id", String(64), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
    Column("attempt_id", String(64), ForeignKey("attempts.id", ondelete="RESTRICT"), nullable=False),
    Column("ledger_digest", String(64), ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=False),
    Column("fidelity_level", String(32), nullable=False),
    Column("claim_ceiling", Text, nullable=False),
    _created(),
    UniqueConstraint("project_id", "attempt_id", "ledger_digest", name="uq_observatory_report_snapshot"),
    CheckConstraint("length(ledger_digest) = 64", name="observatory_ledger_digest"),
    CheckConstraint("fidelity_level IN ('unknown', 'declared', 'assigned', 'available', 'triggered', 'applied', 'activated', 'observed', 'downstream_pathway_detected')", name="observatory_fidelity_level"),
)
xray_analyses = Table(
    "xray_analyses",
    metadata,
    Column("analysis_digest", String(64), primary_key=True),
    Column("project_id", String(64), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
    Column("source_digest", String(64), ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=False),
    Column("source_kind", String(32), nullable=False),
    Column("report_artifact_digest", String(64), ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=False),
    Column("claim_ceiling", Text, nullable=False),
    _created(),
    CheckConstraint("length(analysis_digest) = 64", name="xray_analysis_digest"),
    CheckConstraint("source_kind IN ('auto', 'repository', 'acp', 'cli', 'sdk', 'otel_bundle', 'recorded_run')", name="xray_analysis_source_kind"),
    UniqueConstraint("project_id", "source_digest", "source_kind", name="uq_xray_analysis_source"),
)
observatory_analyses = Table(
    "observatory_analyses",
    metadata,
    Column("analysis_digest", String(64), primary_key=True),
    Column("project_id", String(64), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
    Column("report_artifact_digest", String(64), ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=False),
    Column("claim_ceiling", Text, nullable=False),
    _created(),
    CheckConstraint("length(analysis_digest) = 64", name="observatory_analysis_digest"),
)
Index("ix_xray_snapshots_project_created", xray_snapshots.c.project_id, xray_snapshots.c.created_at)
Index("ix_observatory_reports_project_attempt", observatory_reports.c.project_id, observatory_reports.c.attempt_id)
Index("ix_xray_analyses_project_created", xray_analyses.c.project_id, xray_analyses.c.created_at)
Index("ix_observatory_analyses_project_created", observatory_analyses.c.project_id, observatory_analyses.c.created_at)
# Counterfactual replay and Harness CI persist immutable, project-scoped custody
# indexes only. Raw source diffs, prompts, credentials, traces, and providers are
# intentionally absent from these tables.
counterfactual_replays = Table(
    "counterfactual_replays", metadata,
    Column("id", String(64), primary_key=True),
    Column("project_id", String(64), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
    Column("request_digest", String(64), nullable=False),
    Column("binding_digest", String(64), nullable=False),
    Column("report_artifact_digest", String(64), ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=False),
    Column("verdict", String(8), nullable=False),
    Column("evidence_maturity", String(32), nullable=False),
    Column("claim_ceiling", Text, nullable=False), _created(),
    UniqueConstraint("project_id", "request_digest", name="uq_counterfactual_replay_project_request"),
    UniqueConstraint("project_id", "report_artifact_digest", name="uq_counterfactual_replay_project_report"),
    CheckConstraint("length(request_digest) = 64", name="counterfactual_request_digest"),
    CheckConstraint("length(binding_digest) = 64", name="counterfactual_binding_digest"),
    CheckConstraint("length(report_artifact_digest) = 64", name="counterfactual_report_digest"),
    CheckConstraint("verdict IN ('PASS', 'HOLD', 'FAIL')", name="counterfactual_verdict"),
    CheckConstraint("evidence_maturity IN ('temporal_correlation', 'diagnostic_divergence', 'paired_replay', 'replicated_intervention', 'confirmatory_eligibility')", name="counterfactual_maturity"),
)
harness_ci_reports = Table(
    "harness_ci_reports", metadata,
    Column("id", String(64), primary_key=True),
    Column("project_id", String(64), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
    Column("request_digest", String(64), nullable=False),
    Column("replay_report_digest", String(64), ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=False),
    Column("report_artifact_digest", String(64), ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=False),
    Column("verdict", String(8), nullable=False),
    Column("claim_ceiling", Text, nullable=False), _created(),
    UniqueConstraint("project_id", "request_digest", name="uq_harness_ci_project_request"),
    UniqueConstraint("project_id", "report_artifact_digest", name="uq_harness_ci_project_report"),
    CheckConstraint("length(request_digest) = 64", name="harness_ci_request_digest"),
    CheckConstraint("length(replay_report_digest) = 64", name="harness_ci_replay_digest"),
    CheckConstraint("length(report_artifact_digest) = 64", name="harness_ci_report_digest"),
    CheckConstraint("verdict IN ('PASS', 'HOLD', 'FAIL')", name="harness_ci_verdict"),
)
Index("ix_counterfactual_replays_project_created", counterfactual_replays.c.project_id, counterfactual_replays.c.created_at)
Index("ix_harness_ci_reports_project_created", harness_ci_reports.c.project_id, harness_ci_reports.c.created_at)
# Arena Forge holds immutable, project-scoped custody indexes.  The substantive
# candidate, evaluation, planner, and safety records live content-addressably in
# artifacts; these indexes deliberately expose no patch text, secrets, prompts,
# sealed holdout contents, or executable instructions.
forge_proposals = Table(
    "forge_proposals", metadata,
    Column("id", String(64), primary_key=True),
    Column("project_id", String(64), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
    Column("proposal_digest", String(64), nullable=False),
    Column("proposal_artifact_digest", String(64), ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=False),
    Column("proposer_identity", String(128), nullable=False),
    Column("base_genome_digest", String(64), nullable=False),
    Column("candidate_genome_digest", String(64), nullable=False),
    Column("mechanism_id", String(128), nullable=False),
    Column("state", String(32), nullable=False),
    Column("claim_scope", String(32), nullable=False),
    _created(),
    UniqueConstraint("project_id", "proposal_digest", name="uq_forge_proposal_project_digest"),
    CheckConstraint("length(proposal_digest) = 64 AND length(proposal_artifact_digest) = 64", name="forge_proposal_digests"),
    CheckConstraint("length(base_genome_digest) = 64 AND length(candidate_genome_digest) = 64", name="forge_proposal_genome_digests"),
    CheckConstraint("state IN ('PENDING_APPROVAL', 'APPROVED', 'ADMITTED', 'REJECTED', 'QUARANTINED', 'INCONCLUSIVE')", name="forge_proposal_state"),
    CheckConstraint("claim_scope IN ('fixture_contract', 'recorded_observation', 'product_control')", name="forge_proposal_claim_scope"),
)
forge_approvals = Table(
    "forge_approvals", metadata,
    Column("id", String(64), primary_key=True),
    Column("project_id", String(64), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
    Column("proposal_digest", String(64), nullable=False),
    Column("approval_artifact_digest", String(64), ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=False),
    Column("approver_identity", String(128), nullable=False),
    Column("decision", String(16), nullable=False),
    _created(),
    UniqueConstraint("project_id", "proposal_digest", name="uq_forge_approval_project_proposal"),
    UniqueConstraint("project_id", "approval_artifact_digest", name="uq_forge_approval_project_artifact"),
    CheckConstraint("length(proposal_digest) = 64 AND length(approval_artifact_digest) = 64", name="forge_approval_digests"),
    CheckConstraint("decision IN ('APPROVED', 'REJECTED')", name="forge_approval_decision"),
)
process_safety_reports = Table(
    "process_safety_reports", metadata,
    Column("id", String(64), primary_key=True),
    Column("project_id", String(64), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
    Column("request_digest", String(64), nullable=False),
    Column("report_artifact_digest", String(64), ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=False),
    Column("verdict", String(8), nullable=False),
    Column("policy_digest", String(64), nullable=False),
    _created(),
    UniqueConstraint("project_id", "request_digest", name="uq_process_safety_project_request"),
    UniqueConstraint("project_id", "report_artifact_digest", name="uq_process_safety_project_report"),
    CheckConstraint("length(request_digest) = 64 AND length(report_artifact_digest) = 64 AND length(policy_digest) = 64", name="process_safety_digests"),
    CheckConstraint("verdict IN ('PASS', 'HOLD', 'FAIL')", name="process_safety_verdict"),
)
forge_evaluations = Table(
    "forge_evaluations", metadata,
    Column("id", String(64), primary_key=True),
    Column("project_id", String(64), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
    Column("proposal_digest", String(64), nullable=False),
    Column("evaluation_digest", String(64), nullable=False),
    Column("evaluation_artifact_digest", String(64), ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=False),
    Column("receipt_artifact_digest", String(64), ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=False),
    Column("evaluator_identity", String(128), nullable=False),
    Column("outcome", String(16), nullable=False),
    Column("process_safety_report_digest", String(64), ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=False),
    _created(),
    UniqueConstraint("project_id", "evaluation_digest", name="uq_forge_evaluation_project_digest"),
    UniqueConstraint("project_id", "receipt_artifact_digest", name="uq_forge_evaluation_project_receipt"),
    CheckConstraint("length(proposal_digest) = 64 AND length(evaluation_digest) = 64", name="forge_evaluation_digests"),
    CheckConstraint("length(evaluation_artifact_digest) = 64 AND length(receipt_artifact_digest) = 64 AND length(process_safety_report_digest) = 64", name="forge_evaluation_artifact_digests"),
    CheckConstraint("outcome IN ('ADMITTED', 'REJECTED', 'QUARANTINED', 'INCONCLUSIVE')", name="forge_evaluation_outcome"),
)
forge_planner_reports = Table(
    "forge_planner_reports", metadata,
    Column("id", String(64), primary_key=True),
    Column("project_id", String(64), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
    Column("request_digest", String(64), nullable=False),
    Column("report_artifact_digest", String(64), ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=False),
    Column("mode", String(16), nullable=False),
    Column("verdict", String(8), nullable=False),
    _created(),
    UniqueConstraint("project_id", "request_digest", name="uq_forge_planner_project_request"),
    UniqueConstraint("project_id", "report_artifact_digest", name="uq_forge_planner_project_report"),
    CheckConstraint("length(request_digest) = 64 AND length(report_artifact_digest) = 64", name="forge_planner_digests"),
    CheckConstraint("mode IN ('exploratory', 'confirmatory')", name="forge_planner_mode"),
    CheckConstraint("verdict IN ('READY', 'HOLD')", name="forge_planner_verdict"),
)
Index("ix_forge_proposals_project_created", forge_proposals.c.project_id, forge_proposals.c.created_at)
Index("ix_forge_evaluations_project_created", forge_evaluations.c.project_id, forge_evaluations.c.created_at)
Index("ix_forge_planner_reports_project_created", forge_planner_reports.c.project_id, forge_planner_reports.c.created_at)
Index("ix_process_safety_reports_project_created", process_safety_reports.c.project_id, process_safety_reports.c.created_at)
event.listen(
    forge_evaluations,
    "after_create",
    DDL("""
    CREATE TRIGGER forge_evaluations_no_update
    BEFORE UPDATE ON forge_evaluations
    BEGIN SELECT RAISE(ABORT, 'Evolution Receipts are immutable'); END;
    """).execute_if(dialect="sqlite"),
)
event.listen(
    forge_evaluations,
    "after_create",
    DDL("""
    CREATE TRIGGER forge_evaluations_no_delete
    BEFORE DELETE ON forge_evaluations
    BEGIN SELECT RAISE(ABORT, 'Evolution Receipts are immutable'); END;
    """).execute_if(dialect="sqlite"),
)
event.listen(
    forge_evaluations,
    "after_create",
    DDL("""
    CREATE FUNCTION scaffold_arena_forge_evolution_receipt_immutable() RETURNS trigger AS $$
    BEGIN RAISE EXCEPTION 'Evolution Receipts are immutable'; RETURN NULL; END;
    $$ LANGUAGE plpgsql;
    CREATE TRIGGER forge_evaluations_no_mutation
    BEFORE UPDATE OR DELETE ON forge_evaluations
    FOR EACH ROW EXECUTE FUNCTION scaffold_arena_forge_evolution_receipt_immutable();
    """).execute_if(dialect="postgresql"),
)
event.listen(
    acp_identities,
    "after_create",
    DDL("""
    CREATE TRIGGER acp_identity_project_matches_snapshot
    BEFORE INSERT ON acp_identities
    BEGIN SELECT CASE WHEN (SELECT project_id FROM acp_registry_snapshots WHERE id = NEW.snapshot_id) != NEW.project_id
    THEN RAISE(ABORT, 'ACP identity project must match registry snapshot project') END; END;
    """).execute_if(dialect="sqlite"),
)
event.listen(
    acp_identities,
    "after_create",
    DDL("""
    CREATE TRIGGER acp_identity_identity_is_immutable
    BEFORE UPDATE OF project_id, snapshot_id ON acp_identities
    BEGIN SELECT RAISE(ABORT, 'ACP identity project and snapshot are immutable'); END;
    """).execute_if(dialect="sqlite"),
)
event.listen(
    acp_bridge_runs,
    "after_create",
    DDL("""
    CREATE TRIGGER acp_run_project_matches_identity
    BEFORE INSERT ON acp_bridge_runs
    BEGIN SELECT CASE WHEN (SELECT project_id FROM acp_identities WHERE id = NEW.identity_id) != NEW.project_id
    THEN RAISE(ABORT, 'ACP run project must match identity project') END; END;
    """).execute_if(dialect="sqlite"),
)
event.listen(
    acp_bridge_runs,
    "after_create",
    DDL("""
    CREATE TRIGGER acp_run_identity_is_immutable
    BEFORE UPDATE OF project_id, identity_id ON acp_bridge_runs
    BEGIN SELECT RAISE(ABORT, 'ACP run project and identity are immutable'); END;
    """).execute_if(dialect="sqlite"),
)
event.listen(
    team_audit_events,
    "after_create",
    DDL("""
    CREATE TRIGGER team_audit_events_no_update
    BEFORE UPDATE ON team_audit_events
    BEGIN SELECT RAISE(ABORT, 'team audit events are append-only'); END;
    """).execute_if(dialect="sqlite"),
)
event.listen(
    team_audit_events,
    "after_create",
    DDL("""
    CREATE TRIGGER team_audit_events_no_delete
    BEFORE DELETE ON team_audit_events
    BEGIN SELECT RAISE(ABORT, 'team audit events are append-only'); END;
    """).execute_if(dialect="sqlite"),
)
event.listen(
    team_audit_events,
    "after_create",
    DDL("""
    CREATE FUNCTION scaffold_arena_team_audit_append_only() RETURNS trigger AS $$
    BEGIN RAISE EXCEPTION 'team audit events are append-only'; RETURN NULL; END;
    $$ LANGUAGE plpgsql;
    CREATE TRIGGER team_audit_events_no_mutation
    BEFORE UPDATE OR DELETE ON team_audit_events
    FOR EACH ROW EXECUTE FUNCTION scaffold_arena_team_audit_append_only();
    """).execute_if(dialect="postgresql"),
)
