"""Closed local context-handoff adapter contracts."""

from .adapter import ContextHandoffOllamaAdapter
from .models import (
    CONTEXT_HANDOFF_NAMESPACE, CONTEXT_HANDOFF_SCHEDULE_NAMESPACE, EXPECTED_MODEL,
    EXPECTED_MODEL_DIGEST, EXPECTED_OLLAMA_VERSION, ContextPacket, ContextPolicy,
    FrozenRuntimeBinding, FrozenSchedule, PacketSegment, RendererReceipt,
)
from .render import RENDERER_DIGEST, render_context

__all__ = ["CONTEXT_HANDOFF_NAMESPACE", "CONTEXT_HANDOFF_SCHEDULE_NAMESPACE", "ContextHandoffOllamaAdapter", "ContextPacket", "ContextPolicy", "EXPECTED_MODEL", "EXPECTED_MODEL_DIGEST", "EXPECTED_OLLAMA_VERSION", "FrozenRuntimeBinding", "FrozenSchedule", "PacketSegment", "RENDERER_DIGEST", "RendererReceipt", "render_context"]
