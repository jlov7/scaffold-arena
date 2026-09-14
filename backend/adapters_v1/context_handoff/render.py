"""Pure canonical prompt rendering for the context-handoff factor."""

from __future__ import annotations

from protocol_v1.canonical import canonical_json, sha256, sha256_bytes

from .models import ContextPacket, ContextPolicy, RENDERER_SEMANTIC_VERSION, RendererReceipt


RENDERER_DIGEST = sha256({"renderer": "context-handoff", "semantic_version": RENDERER_SEMANTIC_VERSION, "format": "baseline-segments-task-v1"})


def render_context(*, task: str, packet: ContextPacket, policy: ContextPolicy) -> tuple[str, RendererReceipt]:
    if policy == "isolated":
        included = ()
    elif policy == "full_inherited":
        included = tuple(segment.segment_id for segment in packet.segments)
    else:
        included = packet.curated_segment_ids
    by_id = {segment.segment_id: segment for segment in packet.segments}
    excluded = tuple(segment.segment_id for segment in packet.segments if segment.segment_id not in included)
    lines = ["CURRENT BASELINE FACTS:", packet.baseline]
    for segment_id in included:
        segment = by_id[segment_id]
        lines.extend((f"FROZEN PACKET SEGMENT {segment.segment_id} ({segment.source_id}):", segment.text))
    lines.extend(("TASK:", task, "Return only the declared JSON output contract."))
    prompt = "\n\n".join(lines)
    receipt = RendererReceipt(
        renderer_digest=RENDERER_DIGEST,
        context_policy=policy,
        included_segment_ids=included,
        excluded_segment_ids=excluded,
        segment_hashes={segment_id: by_id[segment_id].content_hash for segment_id in included},
        prompt_hash=sha256_bytes(prompt.encode("utf-8")),
        prompt_bytes=len(prompt.encode("utf-8")),
    )
    return prompt, receipt
