"""Workflow prompt snippets for the main model."""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files


@lru_cache(maxsize=1)
def workflow_guidelines_snippet() -> str:
    """Load optional workflow guidelines appended when the tool is active."""
    try:
        text = (
            files("deepseek_tui.workflow")
            .joinpath("prompt_guidelines.md")
            .read_text(encoding="utf-8")
        )
    except (OSError, TypeError):
        return ""
    return text.strip()
