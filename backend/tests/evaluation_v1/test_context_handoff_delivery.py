from __future__ import annotations

from adapters_v1.context_handoff import ContextPacket
from adapters_v1.context_handoff.render import RENDERER_DIGEST, render_context
from evaluation_v1.graders import ContextHandoffDeliveryGrader
from evaluation_v1.models import EvaluationContext
from protocol_v1.canonical import sha256


PACKET = {"baseline": "Current answer is hold.", "segments": ({"segment_id": "help", "source_id": "packet-help", "text": "Use receipt.", "content_hash": sha256({"segment_id":"help", "source_id":"packet-help", "text":"Use receipt."})},), "curated_segment_ids": ("help",)}
OPTIONS = {"temperature": 0.0, "top_p": 1.0, "num_predict": 256, "seed": 5, "num_ctx": 4096}


def _context(observed_digest: str) -> EvaluationContext:
    prompt, receipt = render_context(task="Return JSON.", packet=ContextPacket.model_validate(PACKET), policy="curated")
    return EvaluationContext(factor_assignments={"context_policy":"curated"}, state_refs={"context_renderer_receipt": receipt.model_dump(mode="json"), "frozen_request_binding": {"model":"qwen3.5:4b", "options":OPTIONS}, "observed_request_digest": observed_digest})


def test_independent_delivery_reconstruction_requires_actual_request_digest() -> None:
    prompt, _ = render_context(task="Return JSON.", packet=ContextPacket.model_validate(PACKET), policy="curated")
    expected = sha256({"model":"qwen3.5:4b", "messages":[{"role":"user","content":prompt}], "stream":False, "think":False, "options":OPTIONS})
    grader = ContextHandoffDeliveryGrader(task="Return JSON.", packet=PACKET, renderer_digest=RENDERER_DIGEST)
    assert grader.evaluate("{}", _context(expected)).passed
    forged = grader.evaluate("{}", _context(sha256({"different":"actual request"})))
    assert not forged.passed and forged.severe_failures == ("context-policy-delivery-mismatch",)
