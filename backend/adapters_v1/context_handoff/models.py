"""Closed, data-only contracts for the local context-handoff study."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import ConfigDict, Field, model_validator

from protocol_v1.canonical import sha256
from protocol_v1.models import ProtocolModel


CONTEXT_HANDOFF_NAMESPACE = "org.scaffold-arena.context-handoff-v1"
CONTEXT_HANDOFF_SCHEDULE_NAMESPACE = "org.scaffold-arena.context-handoff-schedule-v1"
RENDERER_SEMANTIC_VERSION = "1"
EXPECTED_MODEL = "qwen3.5:4b"
EXPECTED_MODEL_DIGEST = "2a654d98e6fba55d452b7043684e9b57a947e393bbffa62485a7aac05ee4eefd"
EXPECTED_OLLAMA_VERSION = "0.34.0"


class PacketSegment(ProtocolModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    segment_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    text: str = Field(min_length=1, max_length=16_384)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")

    @model_validator(mode="after")
    def check_hash(self) -> PacketSegment:
        if self.content_hash != sha256({"segment_id": self.segment_id, "text": self.text, "source_id": self.source_id}):
            raise ValueError("packet segment content_hash does not bind its immutable content")
        return self


class ContextPacket(ProtocolModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    baseline: str = Field(min_length=1, max_length=16_384)
    segments: tuple[PacketSegment, ...]
    curated_segment_ids: tuple[str, ...]

    @model_validator(mode="after")
    def validate_packet(self) -> ContextPacket:
        ids = tuple(item.segment_id for item in self.segments)
        if len(set(ids)) != len(ids) or not self.segments:
            raise ValueError("context packet segments must be non-empty and unique")
        if len(set(self.curated_segment_ids)) != len(self.curated_segment_ids) or not set(self.curated_segment_ids).issubset(ids):
            raise ValueError("curated segment ids must be a unique declared packet subset")
        return self


ContextPolicy = Literal["isolated", "full_inherited", "curated"]


class FrozenRuntimeBinding(ProtocolModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    model: Literal[EXPECTED_MODEL] = EXPECTED_MODEL
    model_digest: Literal[EXPECTED_MODEL_DIGEST] = EXPECTED_MODEL_DIGEST
    ollama_version: Literal[EXPECTED_OLLAMA_VERSION] = EXPECTED_OLLAMA_VERSION


class RendererReceipt(ProtocolModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    renderer_version: Literal[RENDERER_SEMANTIC_VERSION] = RENDERER_SEMANTIC_VERSION
    renderer_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    context_policy: ContextPolicy
    included_segment_ids: tuple[str, ...]
    excluded_segment_ids: tuple[str, ...]
    segment_hashes: Mapping[str, str]
    prompt_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    prompt_bytes: int = Field(ge=1)


class ScheduleCell(ProtocolModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    scenario_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    context_policy: ContextPolicy
    repetition_index: int = Field(ge=0)
    endpoint_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    provider_model: Literal[EXPECTED_MODEL] = EXPECTED_MODEL
    declared_seed: int = Field(ge=0, le=2**31 - 1)
    ordinal: int = Field(ge=0)

    @property
    def coordinate(self) -> tuple[str, str, int, str, str]:
        return (self.scenario_id, self.context_policy, self.repetition_index, self.endpoint_id, self.provider_model)


class FrozenSchedule(ProtocolModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    version: Literal["1"] = "1"
    shuffle_algorithm: Literal["predeclared-policy-interleaved-v1"] = "predeclared-policy-interleaved-v1"
    randomization_seed: int = Field(ge=0)
    cells: tuple[ScheduleCell, ...]
    schedule_digest: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def check_schedule(self) -> FrozenSchedule:
        if not self.cells or len({cell.coordinate for cell in self.cells}) != len(self.cells):
            raise ValueError("schedule cells must be complete and unique")
        if {cell.ordinal for cell in self.cells} != set(range(len(self.cells))):
            raise ValueError("schedule ordinals must be contiguous from zero")
        body = {"version": self.version, "shuffle_algorithm": self.shuffle_algorithm, "randomization_seed": self.randomization_seed, "cells": [cell.model_dump(mode="json") for cell in self.cells]}
        if self.schedule_digest != sha256(body):
            raise ValueError("schedule_digest does not bind the complete schedule")
        return self


def schedule_from_extension(raw: Mapping[str, Any]) -> FrozenSchedule:
    return FrozenSchedule.model_validate(raw)
