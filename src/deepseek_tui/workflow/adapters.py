"""Workflow adapters and prompts.
"""

from __future__ import annotations



# Parse Pi-style workflow scripts (meta export only → IR skeleton).
#
# Full JS body execution is not supported in Python; callers must supply
# ``phases`` in the IR ``spec`` or convert the script to IR externally.
#
import json
import re
from typing import Any

from deepseek_tui.workflow.models import WorkflowMeta, WorkflowPhase, WorkflowPolicy, WorkflowSpec


class PiJsParseError(ValueError):
    pass


_META_EXPORT_RE = re.compile(
    r"export\s+const\s+meta\s*=\s*",
    re.MULTILINE,
)


def parse_workflow_script(script: str) -> tuple[dict[str, Any], str]:
    """Extract ``meta`` object and remaining script body (Pi ``parseWorkflowScript`` subset)."""
    if not script.strip():
        raise PiJsParseError("workflow script is empty")
    match = _META_EXPORT_RE.search(script)
    if not match:
        raise PiJsParseError(
            "`export const meta = { name, description }` must be present in the script"
        )
    if script[: match.start()].strip():
        raise PiJsParseError("meta export must be the first statement in the script")
    return _parse_meta_python(script)


def script_meta_to_spec_skeleton(
    meta: dict[str, Any],
    *,
    phases: list[WorkflowPhase] | None = None,
    policy: WorkflowPolicy | None = None,
) -> WorkflowSpec:
    """Build a WorkflowSpec from parsed Pi meta plus caller-supplied phases."""
    name = meta.get("name")
    description = meta.get("description")
    if not isinstance(name, str) or not name.strip():
        raise PiJsParseError("meta.name must be a non-empty string")
    if not isinstance(description, str) or not description.strip():
        raise PiJsParseError("meta.description must be a non-empty string")
    if not phases:
        raise PiJsParseError(
            "script provides meta only; supply phases in spec or convert script body to IR"
        )
    return WorkflowSpec(
        version=1,
        meta=WorkflowMeta(name=name.strip(), description=description.strip()),
        policy=policy or WorkflowPolicy(),
        phases=phases,
    )


def _parse_meta_python(script: str) -> tuple[dict[str, Any], str]:
    match = _META_EXPORT_RE.search(script)
    if not match:
        raise PiJsParseError(
            "`export const meta = { name, description }` must be the first export in the script"
        )
    if script[: match.start()].strip():
        raise PiJsParseError("meta export must be the first statement in the script")
    start = match.end()
    obj_text, end = _extract_braced_object(script, start)
    meta = _js_object_literal_to_python(obj_text)
    if not isinstance(meta, dict):
        raise PiJsParseError("meta must be an object")
    _validate_meta(meta)
    body = script[: match.start()] + script[end:]
    return meta, body


def _extract_braced_object(script: str, start: int) -> tuple[str, int]:
    if start >= len(script) or script[start] != "{":
        raise PiJsParseError("meta must be an object literal")
    depth = 0
    i = start
    in_str = False
    str_ch = ""
    escape = False
    while i < len(script):
        ch = script[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == str_ch:
                in_str = False
            i += 1
            continue
        if ch in ("'", '"', "`"):
            in_str = True
            str_ch = ch
            i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return script[start : i + 1], i + 1
        i += 1
    raise PiJsParseError("unbalanced meta object")


def _js_object_literal_to_python(text: str) -> Any:
    """Best-effort JS object literal → Python via JSON."""
    converted = text
    converted = re.sub(r"(\w+)\s*:", r'"\1":', converted)
    converted = converted.replace("'", '"')
    converted = re.sub(r"\btrue\b", "true", converted)
    converted = re.sub(r"\bfalse\b", "false", converted)
    converted = re.sub(r"\bnull\b", "null", converted)
    converted = re.sub(r",\s*}", "}", converted)
    converted = re.sub(r",\s*]", "]", converted)
    try:
        return json.loads(converted)
    except json.JSONDecodeError as exc:
        raise PiJsParseError(f"could not parse meta literal: {exc}") from exc


def _validate_meta(meta: dict[str, Any]) -> None:
    if not isinstance(meta.get("name"), str) or not str(meta["name"]).strip():
        raise PiJsParseError("meta.name must be a non-empty string")
    if not isinstance(meta.get("description"), str) or not str(meta["description"]).strip():
        raise PiJsParseError("meta.description must be a non-empty string")
    phases = meta.get("phases")
    if phases is not None:
        if not isinstance(phases, list):
            raise PiJsParseError("meta.phases must be an array")
        for phase in phases:
            if not isinstance(phase, dict) or not isinstance(phase.get("title"), str):
                raise PiJsParseError("each meta phase must have a title string")


# Workflow prompt snippets for the main model.
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
