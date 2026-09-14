"""Text comparison utilities."""

from __future__ import annotations

from rapidfuzz import fuzz


def fuzzy_similarity(a: str, b: str) -> float:
    """Return 0.0–1.0 similarity score between two strings."""
    return fuzz.ratio(a.lower(), b.lower()) / 100.0


def normalize_string(s: str) -> str:
    """Normalize a string for comparison."""
    return s.strip().lower()
