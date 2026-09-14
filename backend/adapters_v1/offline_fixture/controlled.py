"""Control-aware compatibility layer for the bundled offline fixture."""

from __future__ import annotations

from ..controls import scenario_without_execution_controls
from ..models import AttemptInput
from .adapter import OfflineDemoFixtureAdapter as _BaseOfflineDemoFixtureAdapter
from .adapter import OfflineDemoFixtureStateOracle as _BaseOfflineDemoFixtureStateOracle


class OfflineDemoFixtureAdapter(_BaseOfflineDemoFixtureAdapter):
    """Verify the original StudyPack scenario beneath the runtime-only overlay."""

    def _validate_binding(self, harness, input: AttemptInput) -> None:
        base_scenario = scenario_without_execution_controls(input.scenario)
        base_input = AttemptInput.bind(base_scenario, input.attempt)
        super()._validate_binding(harness, base_input)


class OfflineDemoFixtureStateOracle(_BaseOfflineDemoFixtureStateOracle):
    """Keep the independent oracle pinned to the underlying StudyPack scenario."""

    def evaluate(self, scenario, oracle, attempt, result):
        return super().evaluate(
            scenario_without_execution_controls(scenario),
            oracle,
            attempt,
            result,
        )
