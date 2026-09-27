"""Text preparation helpers shared by speech backends."""

from __future__ import annotations

import re


def split_synthesis_text(text: str, max_chars: int = 120) -> list[str]:
    """Split long speech at natural boundaries without dropping any words."""
    remaining = re.sub(r"\s+", " ", str(text or "")).strip()
    segments: list[str] = []
    min_boundary = min(40, max_chars // 2)

    while len(remaining) > max_chars:
        window = remaining[:max_chars]
        boundaries = [window.rfind(mark) + 1 for mark in ".!?;:,。！？；："]
        split_at = max(boundaries)
        if split_at < min_boundary:
            split_at = window.rfind(" ")
        if split_at < min_boundary:
            split_at = max_chars
        segment = remaining[:split_at].strip()
        if segment:
            segments.append(segment)
        remaining = remaining[split_at:].strip()

    if remaining:
        segments.append(remaining)
    return segments
