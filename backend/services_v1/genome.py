"""Project-scoped immutable Harness Genome registration and inspection."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import insert, select

from artifacts_v1 import ArtifactIntegrityError, ArtifactStore
from persistence_v1 import ArenaRepository
from persistence_v1.schema import artifacts, genome_certifications, genome_sources, genomes, projects

from genome_v1 import GenomeDescriptor, canonical_genome_bytes, certify_descriptor, genome_digest, load_standards_catalog, project_graph, semantic_diff

_LOCAL_CEILING = "local descriptor registration only; no runtime, quality, safety, deployment, or independent reproduction claim"


class GenomeError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _id() -> str:
    return f"x{uuid.uuid4().hex}"


def _bare_digest(value: str) -> str:
    if value.startswith("sha256:"):
        value = value[7:]
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise GenomeError("genome_digest_invalid", "Genome digests must be lowercase SHA-256 values.")
    return value


class GenomeService:
    def __init__(self, repository: ArenaRepository, artifact_store: ArtifactStore, *, personal_project_id: str | None = None) -> None:
        self.repository = repository
        self.artifact_store = artifact_store
        self.personal_project_id = personal_project_id

    def _project(self, project_id: str | None) -> str:
        resolved = project_id or self.personal_project_id
        if not resolved:
            raise GenomeError("project_context_required", "An explicit project context is required.")
        with self.repository.engine.connect() as conn:
            if conn.execute(select(projects.c.id).where(projects.c.id == resolved)).scalar_one_or_none() is None:
                raise GenomeError("unknown_project", "The supplied project does not exist.", status_code=404)
        return resolved

    @staticmethod
    def _parse(payload: Mapping[str, Any]) -> GenomeDescriptor:
        try:
            descriptor = GenomeDescriptor.model_validate_json(
                json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            )
            expected = genome_digest(descriptor)
        except (TypeError, ValueError) as exc:
            raise GenomeError("genome_invalid", "A strict, content-addressed Genome v1 descriptor is required.") from exc
        if descriptor.genome_digest != expected:
            raise GenomeError("genome_digest_mismatch", "The supplied Genome digest does not bind its canonical descriptor.")
        if descriptor.authority.status != "declared":
            raise GenomeError("genome_authority_unverified", "Registration accepts declared authority only; elevation requires a service-bound receipt.")
        return descriptor

    def validate(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        descriptor = self._parse(payload)
        return {"valid": True, "genome_digest": descriptor.genome_digest, "claim_ceiling": _LOCAL_CEILING, "provider_execution_started": False}

    def register(self, payload: Mapping[str, Any], *, project_id: str | None) -> dict[str, Any]:
        project = self._project(project_id)
        descriptor = self._parse(payload)
        canonical = canonical_genome_bytes(descriptor)
        artifact_digest = self.artifact_store.put_bytes(canonical, media_type="application/vnd.scaffold-arena.genome+json", metadata={"kind": "harness-genome"})
        digest = _bare_digest(descriptor.genome_digest)
        with self.repository.transaction(immediate=True) as conn:
            existing = conn.execute(select(genomes).where(genomes.c.project_id == project, genomes.c.digest == digest)).mappings().one_or_none()
            if existing is not None:
                if existing["descriptor_artifact_digest"] != artifact_digest:
                    raise GenomeError("genome_immutable_conflict", "This project already contains the Genome digest with different custody bytes.", status_code=409)
                return {"genome_id": existing["id"], "genome_digest": descriptor.genome_digest, "idempotent_replay": True, "claim_ceiling": existing["claim_ceiling"]}
            if conn.execute(select(artifacts.c.digest).where(artifacts.c.digest == artifact_digest)).scalar_one_or_none() is None:
                conn.execute(insert(artifacts).values(digest=artifact_digest, size_bytes=len(canonical), media_type="application/vnd.scaffold-arena.genome+json", storage_uri=self.artifact_store.uri_for(artifact_digest), metadata_json={"kind": "harness-genome"}))
            genome_id = descriptor.genome_id
            conn.execute(insert(genomes).values(id=genome_id, project_id=project, schema=descriptor.schema_version, digest=digest, descriptor_artifact_digest=artifact_digest, authority_status="declared", claim_ceiling=_LOCAL_CEILING))
            for source in descriptor.source_bindings:
                conn.execute(insert(genome_sources).values(genome_id=genome_id, source_id=source.source_id, uri=source.uri, revision=source.revision, content_digest=None if source.content_digest is None else _bare_digest(source.content_digest), source_date=None if source.source_date is None else source.source_date.isoformat(), license_spdx=source.license_spdx, provenance=source.provenance))
        return {"genome_id": genome_id, "genome_digest": descriptor.genome_digest, "descriptor_artifact_digest": artifact_digest, "claim_ceiling": _LOCAL_CEILING, "idempotent_replay": False}

    def list(self, *, project_id: str | None) -> dict[str, Any]:
        project = self._project(project_id)
        with self.repository.engine.connect() as conn:
            records = conn.execute(select(genomes).where(genomes.c.project_id == project).order_by(genomes.c.created_at.desc())).mappings().all()
        return {"genomes": [{"genome_id": row["id"], "schema": row["schema"], "genome_digest": f"sha256:{row['digest']}", "authority_status": row["authority_status"], "claim_ceiling": row["claim_ceiling"]} for row in records]}

    def get(self, genome_id: str, *, project_id: str | None) -> GenomeDescriptor:
        project = self._project(project_id)
        with self.repository.engine.connect() as conn:
            record = conn.execute(select(genomes).where(genomes.c.id == genome_id, genomes.c.project_id == project)).mappings().one_or_none()
        if record is None:
            raise GenomeError("genome_not_found", "The requested Genome is not available in this project.", status_code=404)
        try:
            raw = self.artifact_store.get_bytes(record["descriptor_artifact_digest"])
            descriptor = GenomeDescriptor.model_validate_json(raw)
            if (
                descriptor.genome_id != record["id"]
                or descriptor.schema_version != record["schema"]
                or _bare_digest(genome_digest(descriptor)) != record["digest"]
                or descriptor.authority.status != record["authority_status"]
            ):
                raise ValueError("descriptor index mismatch")
            return descriptor
        except (ArtifactIntegrityError, OSError, ValueError) as exc:
            raise GenomeError("genome_custody_unavailable", "The immutable Genome descriptor could not be verified.", status_code=409) from exc

    def graph(self, genome_id: str, *, project_id: str | None) -> dict[str, Any]:
        return project_graph(self.get(genome_id, project_id=project_id)).model_dump(mode="json")

    def diff(self, before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
        return semantic_diff(self._parse(before), self._parse(after)).model_dump(mode="json")

    def certify(self, genome_id: str, *, project_id: str | None) -> dict[str, Any]:
        project = self._project(project_id)
        descriptor = self.get(genome_id, project_id=project)
        receipt = certify_descriptor(descriptor)
        raw = json.dumps(receipt.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        artifact_digest = self.artifact_store.put_bytes(raw, media_type="application/vnd.scaffold-arena.genome-certification+json", metadata={"kind": "genome-certification"})
        with self.repository.transaction(immediate=True) as conn:
            existing = conn.execute(
                select(genome_certifications).where(
                    genome_certifications.c.id == receipt.receipt_id,
                    genome_certifications.c.genome_id == genome_id,
                    genome_certifications.c.checker_digest == _bare_digest(receipt.checker_digest),
                )
            ).mappings().one_or_none()
            if existing is not None:
                if existing["result_artifact_digest"] != artifact_digest:
                    raise GenomeError("genome_certification_conflict", "The deterministic certification receipt conflicts with stored custody bytes.", status_code=409)
                return receipt.model_dump(mode="json")
            if conn.execute(select(artifacts.c.digest).where(artifacts.c.digest == artifact_digest)).scalar_one_or_none() is None:
                conn.execute(insert(artifacts).values(digest=artifact_digest, size_bytes=len(raw), media_type="application/vnd.scaffold-arena.genome-certification+json", storage_uri=self.artifact_store.uri_for(artifact_digest), metadata_json={"kind": "genome-certification"}))
            conn.execute(insert(genome_certifications).values(id=receipt.receipt_id, genome_id=genome_id, checker_digest=_bare_digest(receipt.checker_digest), result_artifact_digest=artifact_digest, verdict=receipt.verdict, authority_ceiling=receipt.authority_ceiling))
        return receipt.model_dump(mode="json")

    def certification(self, genome_id: str, *, project_id: str | None) -> dict[str, Any]:
        self.get(genome_id, project_id=project_id)
        with self.repository.engine.connect() as conn:
            row = conn.execute(select(genome_certifications).where(genome_certifications.c.genome_id == genome_id).order_by(genome_certifications.c.created_at.desc())).mappings().first()
        if row is None:
            raise GenomeError("genome_certification_not_found", "No local Genome certification receipt exists for this project.", status_code=404)
        try:
            return json.loads(self.artifact_store.get_bytes(row["result_artifact_digest"]))
        except (ArtifactIntegrityError, OSError, ValueError, TypeError) as exc:
            raise GenomeError("genome_custody_unavailable", "The certification receipt could not be verified.", status_code=409) from exc

    @staticmethod
    def catalog(protocol: str | None = None) -> dict[str, Any]:
        rows = [row for row in load_standards_catalog() if protocol is None or row.standard_id == protocol]
        return {"standards": [row.model_dump(mode="json") for row in rows], "claim_ceiling": "catalog metadata only; support requires a named local receipt"}
