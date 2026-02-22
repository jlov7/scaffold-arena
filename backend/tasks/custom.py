from __future__ import annotations

from tasks.base import BaseTask, OUTPUT_RULES


class CustomPromptTask(BaseTask):
    def __init__(
        self,
        *,
        task_id: str,
        name: str,
        prompt: str,
        schema: dict | None = None,
    ) -> None:
        self.id = task_id
        self.name = name
        self.subtitle = "Custom prompt task"
        self.task_type = "custom"
        self.synthetic_sources = False
        self._prompt = prompt
        self._schema = schema or {"type": "object"}

    def get_input_text(self) -> str:
        return self._prompt

    def get_schema(self) -> dict:
        return self._schema

    def get_gold(self) -> dict:
        return {}

    def get_prompt(self) -> str:
        return "\n".join(
            [
                OUTPUT_RULES,
                "",
                "TASK:",
                self._prompt,
                "",
                f"SCHEMA (JSON Schema):\n{self._schema}",
            ]
        )
