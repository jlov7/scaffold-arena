"""Bare scaffold — single-shot prompt, no orchestration."""

from __future__ import annotations

from typing import Any, AsyncGenerator, Callable

from core import events as ev
from core.provider import AnthropicProvider
from core.run_engine import RunOptions
from scaffolds.base import BaseScaffold
from tasks.base import BaseTask


class BareScaffold(BaseScaffold):
    id = "bare"
    name = "Bare Prompt"
    subtitle = "Single-shot, no scaffolding"

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
        prompt = task.get_prompt()

        yield ("scaffold_phase", ev.scaffold_phase(run_id, self.id, "generating"))

        output_parts: list[str] = []
        async for delta in provider.stream_text(
            model_id=model_id,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=options.max_output_tokens,
            temperature=options.temperature,
        ):
            if cancelled_check and cancelled_check():
                break
            output_parts.append(delta)
            yield ("scaffold_delta", ev.scaffold_delta(run_id, self.id, delta))

        usage = provider.get_last_usage()
        yield ("usage", {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens})

        final_output = "".join(output_parts)
        yield ("final_output", {"output": final_output})
