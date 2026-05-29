"""Hybrid merge: FTS + substring candidates with RRF (no embedding required)."""

from __future__ import annotations

from typing import TypeVar

T = TypeVar("T")


def reciprocal_rank_fusion(
    ranked_lists: list[list[tuple[T, float]]],
    *,
    k: int = 60,
) -> list[tuple[T, float]]:
    scores: dict[str, float] = {}
    rows: dict[str, T] = {}
    for lst in ranked_lists:
        for rank, (row, _) in enumerate(lst):
            row_id = getattr(row, "id", str(rank))
            scores[row_id] = scores.get(row_id, 0.0) + 1.0 / (k + rank + 1)
            rows[row_id] = row
    merged = [(rows[mid], scores[mid]) for mid in scores]
    merged.sort(key=lambda x: x[1], reverse=True)
    return merged
