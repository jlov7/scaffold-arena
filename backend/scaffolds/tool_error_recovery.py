"""Tool + Error Recovery scaffold — draft, validate, repair if needed."""

from __future__ import annotations

import json
from typing import Any, AsyncGenerator, Callable

import jsonschema

from core import events as ev
from core.provider import AnthropicProvider
from core.run_engine import RunOptions
from scaffolds.base import BaseScaffold
from tasks.base import BaseTask, OUTPUT_RULES
from utils.json_extract import parse_json_lenient


class ToolErrorRecoveryScaffold(BaseScaffold):
    id = "tool_error_recovery"
    name = "Tool + Error Recovery"
    subtitle = "Draft → validate → repair loop (max 1 repair)"

    async def run(
        self,
        run_id: str,
        task: BaseTask,
        model_id: str,
        provider: AnthropicProvider,
        options: RunOptions,
        config_override: dict | None = None,
        cancelled_check: Callable[[], bool] | None = None,
    ) -> AsyncGenerator[tuple[str, Any], None]:
        max_repairs = (config_override or {}).get("max_repairs", 1)

        # Phase 1 - DRAFT
        yield ("scaffold_phase", ev.scaffold_phase(run_id, self.id, "drafting"))

        draft_parts: list[str] = []
        async for delta in provider.stream_text(
            model_id=model_id,
            messages=[{"role": "user", "content": task.get_prompt()}],
            max_tokens=options.max_output_tokens,
            temperature=options.temperature,
        ):
            if cancelled_check and cancelled_check():
                break
            draft_parts.append(delta)
            yield ("scaffold_delta", ev.scaffold_delta(run_id, self.id, delta))

        usage = provider.get_last_usage()
        yield ("usage", {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens})

        draft_output = "".join(draft_parts)

        # Validation step
        validation_errors = ""
        parse_result = parse_json_lenient(draft_output)
        if not parse_result.ok:
            validation_errors = f"JSON parse failed: {parse_result.error}"
        else:
            try:
                jsonschema.validate(instance=parse_result.data, schema=task.get_schema())
            except jsonschema.ValidationError as exc:
                validation_errors = str(exc)

        if cancelled_check and cancelled_check():
            yield ("final_output", {"output": draft_output})
            return

        # Phase 2 - REPAIR
        final_output = draft_output
        if validation_errors and max_repairs >= 1:
            yield ("scaffold_phase", ev.scaffold_phase(run_id, self.id, "repairing"))

            repair_prompt = (
                f"{OUTPUT_RULES}\n\n"
                "Your previous output failed validation.\n\n"
                f"VALIDATION ERRORS (verbatim):\n{validation_errors}\n\n"
                f"TASK:\n{task.get_input_text()}\n\n"
                f"SCHEMA (JSON Schema):\n{json.dumps(task.get_schema(), indent=2)}\n\n"
                "Return a corrected JSON output that fixes all errors."
            )

            repair_parts: list[str] = []
            async for delta in provider.stream_text(
                model_id=model_id,
                messages=[{"role": "user", "content": repair_prompt}],
                max_tokens=options.max_output_tokens,
                temperature=options.temperature,
            ):
                if cancelled_check and cancelled_check():
                    break
                repair_parts.append(delta)
                yield ("scaffold_delta", ev.scaffold_delta(run_id, self.id, delta))

            usage = provider.get_last_usage()
            yield ("usage", {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens})

            final_output = "".join(repair_parts)

        yield ("final_output", {"output": final_output})
