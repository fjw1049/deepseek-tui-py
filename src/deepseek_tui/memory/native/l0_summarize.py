"""Summarized L0 conversation hit formatting."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def summarize_l0_hits(hits: list[dict[str, Any]]) -> str:
    """Compact digest grouped by thread — avoids raw excerpt pile-ups."""
    if not hits:
        return "No matching conversation lines found."

    by_thread: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for hit in hits:
        by_thread[str(hit.get("thread_id", "?"))].append(hit)

    sections: list[str] = []
    for thread_id, thread_hits in sorted(by_thread.items()):
        lines: list[str] = [f"## Thread `{thread_id}` ({len(thread_hits)} hit(s))"]
        for hit in thread_hits:
            role = hit.get("role", "?")
            score = hit.get("score", 0)
            excerpt = str(hit.get("excerpt") or hit.get("content") or "")
            one_line = " ".join(excerpt.split())
            if len(one_line) > 160:
                one_line = one_line[:159] + "…"
            lines.append(
                f"- line {hit.get('line', '?')} [{role}] score={score}: {one_line}"
            )
        sections.append("\n".join(lines))
    return "\n\n".join(sections)
