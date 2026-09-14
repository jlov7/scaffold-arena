"""Safe adapter for explicitly installed OpenAI-compatible local endpoints."""

from .adapter import endpoint_digest, validate_local_endpoint
from .controlled import OpenAICompatibleAdapter

__all__ = ["OpenAICompatibleAdapter", "endpoint_digest", "validate_local_endpoint"]
