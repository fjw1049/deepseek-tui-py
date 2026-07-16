"""Allowlisted deterministic helpers for ``support`` workflow nodes."""

from __future__ import annotations

import json
from typing import Any, Callable

from deepseek_tui.workflow.models import StepOutput, make_step_output


HelperFn = Callable[[dict[str, StepOutput], dict[str, Any]], StepOutput]


def _dedupe_findings(inputs: dict[str, StepOutput], options: dict[str, Any]) -> StepOutput:
    """Merge text previews and drop duplicate lines (case-insensitive)."""
    seen: set[str] = set()
    lines: list[str] = []
    for _sid, out in inputs.items():
        for line in (out.preview or out.text or "").splitlines():
            key = line.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            lines.append(line.strip())
    max_items = int(options.get("max_items") or 200)
    lines = lines[:max_items]
    text = "\n".join(lines)
    return make_step_output(text, {"findings": lines, "count": len(lines)})


def _flatten_previews(inputs: dict[str, StepOutput], options: dict[str, Any]) -> StepOutput:
    sep = str(options.get("separator") or "\n---\n")
    parts = [f"[{sid}]\n{out.preview}" for sid, out in inputs.items() if out.preview]
    text = sep.join(parts)
    return make_step_output(text, {"sources": list(inputs.keys())})


def _merge_json(inputs: dict[str, StepOutput], options: dict[str, Any]) -> StepOutput:
    """Merge structured dict outputs under their step ids."""
    merged: dict[str, Any] = {}
    for sid, out in inputs.items():
        if out.structured is not None:
            merged[sid] = out.structured
        else:
            merged[sid] = {"text": out.preview}
    text = json.dumps(merged, ensure_ascii=False)
    return make_step_output(text, merged)


HELPERS: dict[str, HelperFn] = {
    "dedupe_findings": _dedupe_findings,
    "flatten_previews": _flatten_previews,
    "merge_json": _merge_json,
    # Dotted aliases matching plan style
    "workflow.helpers.dedupe_findings": _dedupe_findings,
    "workflow.helpers.flatten_previews": _flatten_previews,
    "workflow.helpers.merge_json": _merge_json,
}


def run_support_helper(
    uses: str,
    inputs: dict[str, StepOutput],
    options: dict[str, Any] | None = None,
) -> StepOutput:
    key = uses.strip()
    fn = HELPERS.get(key)
    if fn is None:
        short = key.rsplit(".", 1)[-1]
        fn = HELPERS.get(short)
    if fn is None:
        raise ValueError(
            f"unknown support helper {uses!r}; allowlist: "
            + ", ".join(sorted({k for k in HELPERS if "." not in k}))
        )
    return fn(inputs, options or {})


def list_helpers() -> list[str]:
    return sorted({k for k in HELPERS if "." not in k})
