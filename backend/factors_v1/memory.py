"""Bounded, source-linked memory with deterministic non-semantic compaction."""

from __future__ import annotations

import re

from protocol_v1.canonical import sha256

from .models import EpisodeMemory, MemoryItem


def new_episode_memory(*, episode_id: str, max_items: int, max_bytes: int) -> EpisodeMemory:
    return EpisodeMemory(episode_id=episode_id, max_items=max_items, max_bytes=max_bytes, total_bytes=0)


def _bytes(item: MemoryItem) -> int:
    return len(item.content.encode("utf-8"))


_COMPACTION_MARKER = re.compile(
    r"^\[extractive-compaction; omitted_bytes=(\d+); source_lineage=([a-z][a-z0-9_-]{1,127}(?:,[a-z][a-z0-9_-]{1,127})*)\]$"
)


def _source_text(item: MemoryItem) -> tuple[str, int]:
    if not item.lineage:
        return item.content, 0
    marker, separator, extract = item.content.partition("\n")
    match = _COMPACTION_MARKER.fullmatch(marker)
    if not separator or match is None:
        raise ValueError("malformed internal extractive compaction marker")
    if tuple(match.group(2).split(",")) != item.lineage:
        raise ValueError("internal compaction marker does not bind source lineage")
    return extract, int(match.group(1))


def _utf8_prefix(value: str, max_bytes: int) -> str:
    return value.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")


def _compact(left: MemoryItem, right: MemoryItem, *, max_bytes: int) -> MemoryItem:
    lineage = tuple(dict.fromkeys((*left.lineage, left.item_id, *right.lineage, right.item_id)))
    pointers = tuple(dict.fromkeys((*left.source_pointers, *right.source_pointers)))
    left_source, left_omitted = _source_text(left)
    right_source, right_omitted = _source_text(right)
    original_bytes = (
        len(left_source.encode("utf-8"))
        + len(right_source.encode("utf-8"))
        + left_omitted
        + right_omitted
    )
    omitted_bytes = left_omitted + right_omitted
    separator = "\n---\n"
    for _ in range(8):
        header = f"[extractive-compaction; omitted_bytes={omitted_bytes}; source_lineage={','.join(lineage)}]\n"
        available = max_bytes - len(header.encode("utf-8")) - len(separator.encode("utf-8"))
        if available < 2:
            raise ValueError("episode memory bound is too small for extractive compaction")
        left_limit = available // 2
        right_limit = available - left_limit
        left_extract = _utf8_prefix(left_source, left_limit)
        right_extract = _utf8_prefix(right_source, right_limit)
        if not left_extract or not right_extract:
            raise ValueError("episode memory bound cannot retain readable extractive content")
        new_omitted = original_bytes - len(left_extract.encode("utf-8")) - len(right_extract.encode("utf-8"))
        if new_omitted == omitted_bytes:
            break
        omitted_bytes = new_omitted
    content = f"[extractive-compaction; omitted_bytes={omitted_bytes}; source_lineage={','.join(lineage)}]\n{left_extract}{separator}{right_extract}"
    if len(content.encode("utf-8")) > max_bytes:
        raise ValueError("extractive compaction cannot meet the episode byte bound")
    digest = sha256({"lineage": lineage, "content": content, "sources": pointers})
    return MemoryItem(item_id=f"compact-{digest[:16]}", episode_id=left.episode_id, content=content, source_pointers=pointers, lineage=lineage)


def append_memory(memory: EpisodeMemory, item: MemoryItem) -> EpisodeMemory:
    """Add within one episode, compacting oldest pairs only when it reduces bounds."""
    if item.episode_id != memory.episode_id:
        raise ValueError("cross-episode memory persistence is prohibited")
    if item.item_id in {existing.item_id for existing in memory.items}:
        raise ValueError("memory item id already exists")
    if _bytes(item) > memory.max_bytes:
        raise ValueError("memory item exceeds the episode byte bound")
    items = list(memory.items) + [item]
    while len(items) > memory.max_items or sum(_bytes(entry) for entry in items) > memory.max_bytes:
        if len(items) < 2:
            raise ValueError("episode memory cannot compact within declared bounds")
        remainder_bytes = sum(_bytes(entry) for entry in items[2:])
        capacity = min(_bytes(items[0]) + _bytes(items[1]) - 1, memory.max_bytes - remainder_bytes)
        if capacity < 1:
            raise ValueError("episode memory cannot compact within declared bounds")
        compacted = _compact(items[0], items[1], max_bytes=capacity)
        if _bytes(compacted) >= _bytes(items[0]) + _bytes(items[1]):
            raise ValueError("deterministic compaction would not reduce memory")
        items = [compacted, *items[2:]]
    return EpisodeMemory(episode_id=memory.episode_id, max_items=memory.max_items, max_bytes=memory.max_bytes, items=tuple(items), total_bytes=sum(_bytes(entry) for entry in items))
