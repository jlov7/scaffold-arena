"""Base scaffold interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Callable

from core.provider import AnthropicProvider
from core.run_engine import RunOptions
from tasks.base import BaseTask


class BaseScaffold(ABC):
    id: str
    name: str
    subtitle: str

    @abstractmethod
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
        """Execute the scaffold and yield (event_type, event_data) tuples.

        Event types:
          - "scaffold_phase": phase change notification
          - "scaffold_delta": streaming text delta
          - "usage": token usage after an API call
          - "final_output": the completed output text
        """
        yield  # make this an async generator  # type: ignore[misc]
