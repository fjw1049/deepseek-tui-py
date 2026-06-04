"""Template rendering for workflow prompts."""

from __future__ import annotations

import re
from typing import Any

from deepseek_tui.workflow.constants import (
    FULL_TEXT_MAX,
    PREVIEW_MAX_FANOUT_ITEM,
    PREVIEW_MAX_PER_STEP,
)
from deepseek_tui.workflow.models import StepOutput

_OUTPUT_PREVIEW_RE = re.compile(
    r"\{\{outputs\.([a-zA-Z0-9_\-]+)\}\}"
)
_OUTPUT_FULL_RE = re.compile(
    r"\{\{outputs\.([a-zA-Z0-9_\-]+)\.full\}\}"
)
_OUTPUTS_INDEX_RE = re.compile(r"\{\{outputs\}\}")


def truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def make_preview(text: str, *, limit: int = PREVIEW_MAX_PER_STEP) -> str:
    line = text.replace("\n", " ").strip()
    return truncate_text(line, limit)


def make_step_output(text: str, structured: Any | None = None) -> StepOutput:
    preview = make_preview(text if text else "(empty)")
    return StepOutput(text=text, structured=structured, preview=preview)


def render_template(
    template: str,
    *,
    item: str | None = None,
    previous: StepOutput | None = None,
    outputs: dict[str, StepOutput] | None = None,
) -> str:
    text = template
    if item is not None:
        text = text.replace("{{item}}", item)
    if previous is not None:
        text = text.replace("{{previous}}", previous.preview)
    if outputs is not None:

        def full_sub(match: re.Match[str]) -> str:
            sid = match.group(1)
            out = outputs.get(sid)
            if out is None:
                return f"(missing output: {sid})"
            return truncate_text(out.text, FULL_TEXT_MAX)

        def preview_sub(match: re.Match[str]) -> str:
            sid = match.group(1)
            out = outputs.get(sid)
            if out is None:
                return f"(missing output: {sid})"
            return out.preview

        text = _OUTPUT_FULL_RE.sub(full_sub, text)
        text = _OUTPUT_PREVIEW_RE.sub(preview_sub, text)
        if "{{outputs}}" in text:
            lines = []
            for sid, out in outputs.items():
                lines.append(f"- {sid}: {truncate_text(out.preview, PREVIEW_MAX_FANOUT_ITEM)}")
            text = _OUTPUTS_INDEX_RE.sub("\n".join(lines) if lines else "(no outputs)", text)
    return text
