"""Post-edit path extraction helpers.

Mirrors ``crates/tui/src/core/engine/lsp_hooks.rs:16-71`` — the helpers
that inspect a tool-call input and return the files the tool just
edited. The engine feeds each path into :meth:`LspManager.diagnostics_for`
so the next LLM turn sees fresh diagnostics.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

_EDIT_TOOLS = {"edit_file", "write_file"}


def edited_paths_for_tool(tool_name: str, tool_input: Any) -> list[Path]:
    """Return workspace-relative paths the tool just edited.

    Mirrors Rust ``edited_paths_for_tool`` (lsp_hooks.rs:16-49). Returns
    ``[]`` for non-edit tools so callers can treat it as a pure gate.
    """
    if not isinstance(tool_input, dict):
        return []

    if tool_name in _EDIT_TOOLS:
        path = tool_input.get("path")
        if isinstance(path, str) and path:
            return [Path(path)]
        return []

    if tool_name == "apply_patch":
        out: list[Path] = []
        path = tool_input.get("path")
        if isinstance(path, str) and path:
            out.append(Path(path))
        files = tool_input.get("files")
        if isinstance(files, list):
            for entry in files:
                if isinstance(entry, dict):
                    p = entry.get("path")
                    if isinstance(p, str) and p:
                        out.append(Path(p))
        # Rust also handles `changes` (our native shape), same logic.
        changes = tool_input.get("changes")
        if isinstance(changes, list):
            for entry in changes:
                if isinstance(entry, dict):
                    p = entry.get("path")
                    if isinstance(p, str) and p:
                        out.append(Path(p))
        # Fallback: parse `+++ b/...` from the patch text.
        if not out:
            patch = tool_input.get("patch")
            if isinstance(patch, str) and patch:
                out.extend(parse_patch_paths(patch))
        return out

    return []


def parse_patch_paths(patch: str) -> list[Path]:
    """Extract ``+++ b/<path>`` targets from a unified diff.

    Mirrors Rust ``parse_patch_paths`` (lsp_hooks.rs:56-71). Best-effort
    only; the real apply_patch validates the patch shape.
    """
    out: list[Path] = []
    for line in patch.splitlines():
        if not line.startswith("+++ "):
            continue
        rest = line[len("+++ ") :].strip()
        # Strip the `b/` prefix conventional for git diffs.
        if rest.startswith("b/"):
            rest = rest[2:]
        if rest == "/dev/null" or not rest:
            continue
        out.append(Path(rest))
    return out
