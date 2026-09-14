"""Generation-scoped context for externally invoked adapter work."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import ConfigDict, Field, model_validator

from protocol_v1.canonical import sha256
from protocol_v1.models import ProtocolModel


class InvocationContext(ProtocolModel):
    """Immutable invocation fence passed separately from the scientific input.

    The context is operational evidence, not task content.  It deliberately
    excludes credentials and never changes the canonical AttemptInput.
    """

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    invocation_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    attempt_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    generation: int = Field(ge=1)
    fence_token: str = Field(pattern=r"^[a-f0-9]{64}$")
    provider_idempotency_key: str = Field(min_length=1, max_length=255)
    aggregate_deadline_at: datetime | None = None
    context_digest: str = Field(pattern=r"^[a-f0-9]{64}$")

    @staticmethod
    def digest_for(
        *,
        invocation_id: str,
        attempt_id: str,
        generation: int,
        fence_token: str,
        provider_idempotency_key: str,
        aggregate_deadline_at: datetime | None,
    ) -> str:
        return sha256(
            {
                "invocation_id": invocation_id,
                "attempt_id": attempt_id,
                "generation": generation,
                "fence_token": fence_token,
                "provider_idempotency_key": provider_idempotency_key,
                "aggregate_deadline_at": (
                    aggregate_deadline_at.astimezone(UTC).isoformat()
                    if aggregate_deadline_at is not None
                    else None
                ),
            }
        )

    @classmethod
    def bind(
        cls,
        *,
        invocation_id: str,
        attempt_id: str,
        generation: int,
        fence_token: str,
        provider_idempotency_key: str,
        aggregate_deadline_at: datetime | None,
    ) -> InvocationContext:
        if aggregate_deadline_at is not None and (
            aggregate_deadline_at.tzinfo is None
            or aggregate_deadline_at.utcoffset() is None
        ):
            raise ValueError("aggregate_deadline_at must be timezone-aware")
        normalized_deadline = (
            aggregate_deadline_at.astimezone(UTC)
            if aggregate_deadline_at is not None
            else None
        )
        return cls(
            invocation_id=invocation_id,
            attempt_id=attempt_id,
            generation=generation,
            fence_token=fence_token,
            provider_idempotency_key=provider_idempotency_key,
            aggregate_deadline_at=normalized_deadline,
            context_digest=cls.digest_for(
                invocation_id=invocation_id,
                attempt_id=attempt_id,
                generation=generation,
                fence_token=fence_token,
                provider_idempotency_key=provider_idempotency_key,
                aggregate_deadline_at=normalized_deadline,
            ),
        )

    @model_validator(mode="after")
    def validate_binding(self) -> InvocationContext:
        if self.aggregate_deadline_at is not None and (
            self.aggregate_deadline_at.tzinfo is None
            or self.aggregate_deadline_at.utcoffset() is None
        ):
            raise ValueError("aggregate_deadline_at must be timezone-aware")
        expected = self.digest_for(
            invocation_id=self.invocation_id,
            attempt_id=self.attempt_id,
            generation=self.generation,
            fence_token=self.fence_token,
            provider_idempotency_key=self.provider_idempotency_key,
            aggregate_deadline_at=self.aggregate_deadline_at,
        )
        if self.context_digest != expected:
            raise ValueError("context_digest does not bind the invocation context")
        return self

    def model_copy(
        self,
        *,
        update: dict[str, Any] | None = None,
        deep: bool = False,
    ) -> InvocationContext:
        if not update:
            return super().model_copy(update=update, deep=deep)
        values = self.model_dump(mode="python")
        values.update(update)
        values.pop("context_digest", None)
        return type(self).bind(**values)

    def remaining_seconds(self, *, now: datetime | None = None) -> float | None:
        if self.aggregate_deadline_at is None:
            return None
        current = now or datetime.now(UTC)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        return (self.aggregate_deadline_at - current.astimezone(UTC)).total_seconds()
