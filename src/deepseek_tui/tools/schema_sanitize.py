"""JSON Schema sanitizer for DeepSeek strict function calling.

Mirrors ``crates/tui/src/tools/schema_sanitize.rs``.

Pydantic-generated schemas contain patterns that DeepSeek's strict mode
rejects:
  - ``anyOf: [X, {type: "null"}]`` for Optional fields
  - bare ``{type: "object"}`` without ``properties``
  - ``required`` entries not present in ``properties``
  - single-element ``oneOf`` / ``allOf`` wrappers

This module normalizes schemas in-place so strict mode can be enabled
without hand-editing tool definitions.
"""

from __future__ import annotations

from typing import Any


def sanitize(schema: dict[str, Any]) -> dict[str, Any]:
    """Normalize *schema* for DeepSeek compatibility. Idempotent."""
    _walk(schema)
    return schema


def sanitize_for_strict(schema: dict[str, Any]) -> dict[str, Any]:
    """Normalize and enforce strict-mode requirements.

    Adds ``additionalProperties: false`` and marks all properties as
    required on every object sub-schema.
    """
    _walk(schema, strict=True)
    return schema


def prepare_tools_for_strict_mode(
    tools: list[dict[str, Any]],
) -> bool:
    """Sanitize all tool schemas for strict mode.

    Returns False if any tool has a root-level ``anyOf``/``oneOf``/``allOf``
    that cannot be collapsed (incompatible with strict). Otherwise sanitizes
    all tools and returns True.
    """
    for tool in tools:
        fn = tool.get("function", {})
        params = fn.get("parameters")
        if not isinstance(params, dict):
            continue
        # Root-level composition → incompatible with strict
        for key in ("anyOf", "oneOf", "allOf"):
            val = params.get(key)
            if isinstance(val, list) and len(val) > 1:
                return False

    for tool in tools:
        fn = tool.get("function", {})
        params = fn.get("parameters")
        if isinstance(params, dict):
            sanitize_for_strict(params)
    return True


# ---------------------------------------------------------------------------
# Internal recursive walker
# ---------------------------------------------------------------------------


def _walk(schema: dict[str, Any], *, strict: bool = False) -> None:
    """Recursively normalize a JSON schema dict."""
    # 1. Collapse nullable anyOf: [X, {type: "null"}] → X
    _collapse_nullable_union(schema)

    # 2. Collapse single-element oneOf / allOf
    _collapse_single_composition(schema)

    # 3. Inject properties on bare objects
    if schema.get("type") == "object" and "properties" not in schema:
        schema["properties"] = {}

    # 4. Prune dangling required entries
    _prune_dangling_required(schema)

    # 5. Strict mode additions
    if strict and schema.get("type") == "object":
        schema["additionalProperties"] = False
        props = schema.get("properties", {})
        if props:
            schema["required"] = list(props.keys())

    # Recurse into sub-schemas
    props = schema.get("properties")
    if isinstance(props, dict):
        for sub in props.values():
            if isinstance(sub, dict):
                _walk(sub, strict=strict)

    items = schema.get("items")
    if isinstance(items, dict):
        _walk(items, strict=strict)

    for key in ("anyOf", "oneOf", "allOf"):
        variants = schema.get(key)
        if isinstance(variants, list):
            for v in variants:
                if isinstance(v, dict):
                    _walk(v, strict=strict)


def _collapse_nullable_union(schema: dict[str, Any]) -> None:
    """Collapse ``anyOf: [X, {type: "null"}]`` → X merged into schema."""
    any_of = schema.get("anyOf")
    if not isinstance(any_of, list):
        return
    if len(any_of) != 2:
        return

    null_idx = -1
    for i, variant in enumerate(any_of):
        if isinstance(variant, dict) and variant.get("type") == "null":
            null_idx = i
            break

    if null_idx == -1:
        return

    # The other variant is the real type
    real = any_of[1 - null_idx]
    if not isinstance(real, dict):
        return

    # Remove anyOf and merge the real type into schema
    del schema["anyOf"]
    for k, v in real.items():
        schema[k] = v


def _collapse_single_composition(schema: dict[str, Any]) -> None:
    """Collapse single-element oneOf/allOf into the schema."""
    for key in ("oneOf", "allOf"):
        variants = schema.get(key)
        if isinstance(variants, list) and len(variants) == 1:
            single = variants[0]
            if isinstance(single, dict):
                del schema[key]
                for k, v in single.items():
                    schema[k] = v


def _prune_dangling_required(schema: dict[str, Any]) -> None:
    """Remove required entries not present in properties."""
    required = schema.get("required")
    properties = schema.get("properties")
    if not isinstance(required, list) or not isinstance(properties, dict):
        return
    valid = [r for r in required if r in properties]
    if valid:
        schema["required"] = valid
    else:
        del schema["required"]
