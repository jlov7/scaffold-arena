"""Typed deterministic hooks; adapter narration never overrules an oracle."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from adapters_v1.models import ResultBundle
from protocol_v1.models import AttemptEnvelope, ScenarioSpec, StateOracle


@dataclass(frozen=True)
class StateOracleDecision:
    terminal_outcome: str
    detail: str
    evidence: Mapping[str, Any]


class StateOracleHook(Protocol):
    def evaluate(self, scenario: ScenarioSpec, oracle: StateOracle, attempt: AttemptEnvelope, result: ResultBundle) -> StateOracleDecision: ...


class FaultHook(Protocol):
    def before_attempt(self, scenario: ScenarioSpec, attempt: AttemptEnvelope) -> None: ...
