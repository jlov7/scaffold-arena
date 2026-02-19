"""Base task interface."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod

OUTPUT_RULES = """OUTPUT RULES (STRICT):
- Return ONLY the final answer.
- If the required output is JSON: return a single JSON object.
- Do NOT wrap JSON in markdown fences.
- Do NOT include commentary before or after the JSON."""


class BaseTask(ABC):
    id: str
    name: str
    subtitle: str
    task_type: str
    synthetic_sources: bool = False

    @abstractmethod
    def get_input_text(self) -> str:
        """Return the raw input text for this task."""

    @abstractmethod
    def get_schema(self) -> dict:
        """Return the JSON Schema for the expected output."""

    @abstractmethod
    def get_gold(self) -> dict | list:
        """Return the gold standard answer for deterministic scoring."""

    def get_prompt(self) -> str:
        """Build the full task prompt with output rules and schema."""
        schema_str = json.dumps(self.get_schema(), indent=2)
        parts = [OUTPUT_RULES, "", "TASK:", self.get_input_text(), "", f"SCHEMA (JSON Schema):\n{schema_str}"]
        if self.synthetic_sources:
            parts.insert(0, "IMPORTANT: The sources referenced below are SYNTHETIC DEMO MATERIALS, not real publications.\n")
        return "\n".join(parts)
