"""The stable asynchronous adapter boundary."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from protocol_v1.models import HarnessSpec, TraceEvent

from .invocation import InvocationContext
from .models import (
    AdapterCapabilities,
    AdapterHealth,
    ArtifactRef,
    AttemptInput,
    PreparedAttempt,
    ResultBundle,
)


class HarnessAdapter(ABC):
    """Only trusted, explicitly registered instances may cross this boundary."""

    @abstractmethod
    async def describe_capabilities(self) -> AdapterCapabilities: ...

    @abstractmethod
    async def healthcheck(self) -> AdapterHealth: ...

    @abstractmethod
    async def prepare_attempt(self, harness: HarnessSpec, input: AttemptInput) -> PreparedAttempt: ...

    async def prepare_invocation(
        self,
        harness: HarnessSpec,
        input: AttemptInput,
        context: InvocationContext,
    ) -> PreparedAttempt:
        """Prepare with an operational fence when an adapter supports it.

        The default preserves compatibility but does not claim that the
        external transport consumed the idempotency key or fence token.  The
        worker records that distinction in the InvocationRecord.
        """

        del context
        return await self.prepare_attempt(harness, input)

    @abstractmethod
    async def execute_attempt(self, prepared: PreparedAttempt) -> ResultBundle: ...

    @abstractmethod
    async def stream_events(self, prepared: PreparedAttempt) -> AsyncIterator[TraceEvent]: ...

    @abstractmethod
    async def collect_artifacts(self, prepared: PreparedAttempt) -> tuple[ArtifactRef, ...]: ...

    @abstractmethod
    async def cancel_attempt(self, prepared: PreparedAttempt) -> None: ...

    @abstractmethod
    async def cleanup_attempt(self, prepared: PreparedAttempt) -> None: ...
