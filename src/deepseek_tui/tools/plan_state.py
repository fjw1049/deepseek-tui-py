"""Pure plan parsing and in-memory snapshot shared by tools and UI."""

from __future__ import annotations

import re
from typing import Any

_PLAN_STORE_KEY = "plan"


def _first_markdown_heading(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or None
    return None


def parse_plan_markdown(text: str) -> list[dict[str, Any]]:
    """Best-effort checklist parser for ``update_plan`` markdown bodies."""
    steps: list[dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        match = re.match(r"^- \[( |x|X|~)\] (.+)$", stripped)
        if not match:
            continue
        mark, title = match.group(1), match.group(2).strip()
        if mark.lower() == "x":
            status = "completed"
        elif mark == "~":
            status = "in_progress"
        else:
            status = "pending"
        steps.append({"index": len(steps) + 1, "title": title, "status": status})
    return steps


def parse_structured_plan_steps(raw_steps: list[Any]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for idx, item in enumerate(raw_steps, start=1):
        if not isinstance(item, dict):
            continue
        title = item.get("step") or item.get("title") or ""
        if not str(title).strip():
            continue
        status = item.get("status", "pending")
        steps.append(
            {
                "index": idx,
                "title": str(title),
                "status": str(status),
            }
        )
    return steps


def sync_plan_store(
    metadata: dict[str, Any],
    *,
    explanation: str | None,
    plan_text: str | None = None,
    structured_steps: list[dict[str, Any]] | None = None,
) -> None:
    steps = structured_steps or (parse_plan_markdown(plan_text or "") if plan_text else [])
    goal = explanation or (_first_markdown_heading(plan_text or "") if plan_text else None)
    metadata[_PLAN_STORE_KEY] = {
        "goal": goal,
        "explanation": explanation,
        "steps": steps,
    }
