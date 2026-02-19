"""Memory + Critique scaffold — decompose, solve subtasks, synthesize, critique, refine."""

from __future__ import annotations

import json
import re
from typing import Any, AsyncGenerator, Callable

from core import events as ev
from core.provider import AnthropicProvider
from core.run_engine import RunOptions
from scaffolds.base import BaseScaffold
from tasks.base import BaseTask, OUTPUT_RULES


class MemoryCritiqueScaffold(BaseScaffold):
    id = "memory_critique"
    name = "Memory + Critique"
    subtitle = "Decompose → subtasks → synthesize → critique → refine"

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
        # --- Phase 1: DECOMPOSE ---
        yield ("scaffold_phase", ev.scaffold_phase(run_id, self.id, "decomposing"))

        decompose_result = await provider.complete(
            model_id=model_id,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "You will solve a task by decomposing it into subtasks and then synthesizing.\n\n"
                        f"TASK:\n{task.get_input_text()}\n\n"
                        "Instructions:\n"
                        "- Propose 2–4 subtasks.\n"
                        "- For each subtask provide:\n"
                        "  - goal\n"
                        "  - expected intermediate output (brief)\n"
                        "- Do NOT produce the final answer yet.\n"
                        "Return as a numbered list."
                    ),
                }
            ],
            max_tokens=options.max_output_tokens,
            temperature=options.temperature,
        )

        usage = decompose_result.usage
        yield ("usage", {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens})

        decompose_text = decompose_result.text
        subtasks = re.split(r'\n\d+[\.\)]\s*', decompose_text)
        subtasks = [s.strip() for s in subtasks if s.strip()]
        if not subtasks:
            subtasks = [decompose_text]

        # --- Phase 2: SUBTASKS ---
        working_memory: list[str] = []

        for i, subtask_text in enumerate(subtasks):
            if cancelled_check and cancelled_check():
                break

            yield ("scaffold_phase", ev.scaffold_phase(run_id, self.id, f"subtask_{i + 1}"))

            subtask_result = await provider.complete(
                model_id=model_id,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Solve subtask {i + 1}.\n\n"
                            f"SUBTASK:\n{subtask_text}\n\n"
                            f"Relevant task context:\n{task.get_input_text()}\n\n"
                            "Return your intermediate result. Keep it concise but complete."
                        ),
                    }
                ],
                max_tokens=options.max_output_tokens,
                temperature=options.temperature,
            )

            usage = subtask_result.usage
            yield ("usage", {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens})

            working_memory.append(subtask_result.text)

        if cancelled_check and cancelled_check():
            yield ("final_output", {"output": ""})
            return

        # --- Phase 3: SYNTHESIZE ---
        yield ("scaffold_phase", ev.scaffold_phase(run_id, self.id, "synthesizing"))

        memory_items_joined = "\n\n".join(
            f"{i + 1}. {item}" for i, item in enumerate(working_memory)
        )

        output_parts: list[str] = []
        async for delta in provider.stream_text(
            model_id=model_id,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"{OUTPUT_RULES}\n\n"
                        "SYNTHESIZE a final answer using the working memory.\n\n"
                        f"WORKING MEMORY:\n{memory_items_joined}\n\n"
                        f"TASK:\n{task.get_input_text()}\n\n"
                        f"SCHEMA (JSON Schema):\n{json.dumps(task.get_schema(), indent=2)}"
                    ),
                }
            ],
            max_tokens=options.max_output_tokens,
            temperature=options.temperature,
        ):
            if cancelled_check and cancelled_check():
                break
            output_parts.append(delta)
            yield ("scaffold_delta", ev.scaffold_delta(run_id, self.id, delta))

        usage = provider.get_last_usage()
        yield ("usage", {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens})

        candidate_output = "".join(output_parts)

        if cancelled_check and cancelled_check():
            yield ("final_output", {"output": candidate_output})
            return

        # --- Phase 4: CRITIQUE ---
        yield ("scaffold_phase", ev.scaffold_phase(run_id, self.id, "critiquing"))

        critique_result = await provider.complete(
            model_id=model_id,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Critique the following output.\n\n"
                        f"OUTPUT:\n{candidate_output}\n\n"
                        "Score 1–10 on:\n"
                        "- completeness\n"
                        "- correctness\n"
                        "- format/schema compliance\n\n"
                        "Then list the top 3 weaknesses.\n"
                        'Return as JSON:\n'
                        '{"completeness":n,"correctness":n,"format":n,"weaknesses":[...]}'
                    ),
                }
            ],
            max_tokens=options.max_output_tokens,
            temperature=options.temperature,
        )

        usage = critique_result.usage
        yield ("usage", {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens})

        critique_text = critique_result.text
        try:
            critique_data = json.loads(critique_text)
            weaknesses = critique_data.get("weaknesses", [])
            weaknesses_text = "\n".join(f"- {w}" for w in weaknesses)
        except (json.JSONDecodeError, AttributeError):
            weaknesses_text = critique_text

        if cancelled_check and cancelled_check():
            yield ("final_output", {"output": candidate_output})
            return

        # --- Phase 5: REFINE ---
        yield ("scaffold_phase", ev.scaffold_phase(run_id, self.id, "refining"))

        refined_parts: list[str] = []
        async for delta in provider.stream_text(
            model_id=model_id,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"{OUTPUT_RULES}\n\n"
                        "Improve the output to address these weaknesses:\n\n"
                        f"WEAKNESSES:\n{weaknesses_text}\n\n"
                        f"OUTPUT TO IMPROVE:\n{candidate_output}\n\n"
                        "Return the improved final answer only."
                    ),
                }
            ],
            max_tokens=options.max_output_tokens,
            temperature=options.temperature,
        ):
            if cancelled_check and cancelled_check():
                break
            refined_parts.append(delta)
            yield ("scaffold_delta", ev.scaffold_delta(run_id, self.id, delta))

        usage = provider.get_last_usage()
        yield ("usage", {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens})

        final_output = "".join(refined_parts) if refined_parts else candidate_output
        yield ("final_output", {"output": final_output})
