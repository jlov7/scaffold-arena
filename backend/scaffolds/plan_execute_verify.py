"""Plan → Execute → Verify scaffold."""

from __future__ import annotations

import json
from typing import Any, AsyncGenerator, Callable

from core import events as ev
from core.provider import AnthropicProvider
from core.run_engine import RunOptions
from scaffolds.base import BaseScaffold
from tasks.base import BaseTask, OUTPUT_RULES


class PlanExecuteVerifyScaffold(BaseScaffold):
    id = "plan_execute_verify"
    name = "Plan → Execute → Verify"
    subtitle = "3-phase: plan, execute with streaming, then verify"

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
        schema_json = json.dumps(task.get_schema(), indent=2)

        # Phase 1 — PLAN (non-streaming)
        yield ("scaffold_phase", ev.scaffold_phase(run_id, self.id, "planning"))

        plan_result = await provider.complete(
            model_id=model_id,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"You are creating an execution plan for a strict output task.\n\n"
                        f"{task.get_input_text()}\n\n"
                        f"Constraints:\n"
                        f"- Your plan must be 6–10 numbered steps.\n"
                        f"- Include how you will avoid common failure modes (missing fields, wrong types, extra prose).\n"
                        f"- Do NOT solve the task yet. Plan only."
                    ),
                }
            ],
            max_tokens=options.max_output_tokens,
            temperature=options.temperature,
        )

        yield ("usage", {"input_tokens": plan_result.usage.input_tokens, "output_tokens": plan_result.usage.output_tokens})

        if cancelled_check and cancelled_check():
            return

        plan_text = plan_result.text

        # Phase 2 — EXECUTE (streaming)
        yield ("scaffold_phase", ev.scaffold_phase(run_id, self.id, "executing"))

        execute_prompt = (
            f"{OUTPUT_RULES}\n\n"
            f"Execute the following plan to complete the task:\n\n"
            f"PLAN:\n{plan_text}\n\n"
            f"TASK:\n{task.get_input_text()}\n\n"
            f"SCHEMA (JSON Schema):\n{schema_json}"
        )

        output_parts: list[str] = []
        async for delta in provider.stream_text(
            model_id=model_id,
            messages=[{"role": "user", "content": execute_prompt}],
            max_tokens=options.max_output_tokens,
            temperature=options.temperature,
        ):
            if cancelled_check and cancelled_check():
                break
            output_parts.append(delta)
            yield ("scaffold_delta", ev.scaffold_delta(run_id, self.id, delta))

        usage = provider.get_last_usage()
        yield ("usage", {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens})

        if cancelled_check and cancelled_check():
            final_output = "".join(output_parts)
            yield ("final_output", {"output": final_output})
            return

        candidate_output = "".join(output_parts)

        # Phase 3 — VERIFY (non-streaming)
        yield ("scaffold_phase", ev.scaffold_phase(run_id, self.id, "verifying"))

        verify_result = await provider.complete(
            model_id=model_id,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"You are verifying an answer against strict requirements.\n\n"
                        f"REQUIREMENTS:\n"
                        f"- Output must be a single JSON object with exactly the required fields and types.\n"
                        f"- Must satisfy the schema.\n"
                        f"- Must contain all required items (e.g. parties, must-flag clauses, required sources).\n\n"
                        f"SCHEMA (JSON Schema):\n{schema_json}\n\n"
                        f"CANDIDATE OUTPUT:\n{candidate_output}\n\n"
                        f"Instructions:\n"
                        f"- If the output violates requirements, list the exact issues in bullet points.\n"
                        f"- Then produce a corrected output that fully complies.\n"
                        f"- Return ONLY the corrected output (JSON only)."
                    ),
                }
            ],
            max_tokens=options.max_output_tokens,
            temperature=options.temperature,
        )

        yield ("usage", {"input_tokens": verify_result.usage.input_tokens, "output_tokens": verify_result.usage.output_tokens})

        final_output = verify_result.text if verify_result.text else candidate_output
        yield ("final_output", {"output": final_output})
