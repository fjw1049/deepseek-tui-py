"""Compact schema snippets for MCP argument-error recovery."""

from __future__ import annotations

import json
import re
from typing import Any

_MAX_SCHEMA_CHARS = 2_000

# Heuristic: server/message text that usually means bad arguments.
_ARG_ERROR_RE = re.compile(
    r"(invalid|missing|required|unknown|unexpected|type\s+error|"
    r"validation|argument|parameter|field|schema|properties)",
    re.IGNORECASE,
)


def looks_like_argument_error(message: str) -> bool:
    """True when *message* likely describes a bad tool argument payload."""
    return bool(message) and _ARG_ERROR_RE.search(message) is not None


def format_schema_hint(parameters: dict[str, Any] | None) -> str:
    """Render a truncated schema block for model-facing error text."""
    if not parameters:
        return (
            "Do not guess parameter names — retry with the exact fields "
            "from this tool's input schema in the current catalog."
        )

    compact = _compact_parameters(parameters)
    rendered = json.dumps(compact, ensure_ascii=False, indent=2, sort_keys=True)
    truncated = False
    if len(rendered) > _MAX_SCHEMA_CHARS:
        rendered = rendered[: _MAX_SCHEMA_CHARS - 20] + "\n… [truncated]"
        truncated = True

    lines = [
        "Expected input schema (from cache) — use these exact field names:",
        rendered,
        "Do not guess parameter names. If this snippet is incomplete"
        + (" (truncated)" if truncated else "")
        + ", retry using the exact fields from this tool's catalog schema.",
    ]
    return "\n".join(lines)


def _compact_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    """Keep type / required / property names; drop bulky nested descriptions."""
    out: dict[str, Any] = {}
    if "type" in parameters:
        out["type"] = parameters["type"]
    if "required" in parameters:
        out["required"] = parameters["required"]
    props = parameters.get("properties")
    if isinstance(props, dict):
        slim: dict[str, Any] = {}
        for key, spec in props.items():
            if isinstance(spec, dict):
                entry: dict[str, Any] = {}
                for field in ("type", "enum", "items", "default"):
                    if field in spec:
                        entry[field] = spec[field]
                if "description" in spec and isinstance(spec["description"], str):
                    desc = spec["description"].strip()
                    if desc:
                        entry["description"] = desc[:160] + (
                            "…" if len(desc) > 160 else ""
                        )
                slim[key] = entry or {"type": "any"}
            else:
                slim[key] = spec
        out["properties"] = slim
    if not out:
        # Fall back to a shallow copy of top-level keys only.
        for key in ("type", "required", "properties", "additionalProperties"):
            if key in parameters:
                out[key] = parameters[key]
    return out


def enrich_mcp_argument_error(
    tool_name: str,
    message: str,
    parameters: dict[str, Any] | None,
) -> str:
    """Attach a schema / search hint when *message* looks like a param error."""
    base = f"MCP tool '{tool_name}' failed: {message}"
    if not looks_like_argument_error(message):
        return base
    return f"{base}\n\n{format_schema_hint(parameters)}"
