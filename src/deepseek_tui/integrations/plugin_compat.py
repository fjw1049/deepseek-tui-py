"""Cross-ecosystem plugin normalization.

Canonical plugin format = **Claude Code layout + DeepSeek extensions** (the
``rules`` injection and ``permissions``). Plugins authored for other ecosystems
(CodeBuddy / WorkBuddy) are normalized *into* that canonical form on the
**installed copy** at install time — the vendor's original source files are
never mutated. This keeps the runtime loader canonical-first; its tolerance
shims (see ``plugins._collect_*``) remain only as a fallback so an
un-normalized plugin still loads.

All ecosystem-specific knowledge is isolated here, on purpose: adding a new
ecosystem means editing this module, not the hot-path loader.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

__all__ = [
    "FOREIGN_TOOL_NAME_MAP",
    "map_tool_matcher",
    "matcher_to_condition",
    "normalize_installed_plugin",
]

# Foreign (Claude Code / CodeBuddy) tool names → DeepSeek runtime tool names.
# Keys are lowercased. A foreign name may fan out to several DeepSeek tools.
# This table is the single source of truth for translating hook ``matcher``
# patterns so that tool-scoped hooks authored elsewhere actually fire here.
FOREIGN_TOOL_NAME_MAP: dict[str, tuple[str, ...]] = {
    "read": ("read_file",),
    "write": ("write_file",),
    "edit": ("edit_file",),
    "multiedit": ("edit_file", "apply_patch"),
    "notebookedit": ("edit_file",),
    "bash": ("exec_shell",),
    "glob": ("file_search",),
    "grep": ("grep_files",),
    "ls": ("list_dir",),
    "webfetch": ("fetch_url",),
    "websearch": ("web_search",),
    "task": ("agent_spawn", "delegate_to_agent"),
    "todowrite": ("checklist_write",),
    "skill": ("load_skill",),
}


def map_tool_matcher(matcher: str) -> list[str]:
    """Translate a Claude/CodeBuddy hook ``matcher`` to DeepSeek tool names.

    ``matcher`` is a ``|``-alternation of foreign tool names (e.g.
    ``"Edit|Write"``). An empty matcher, ``"*"`` or ``".*"`` means "every tool"
    and returns ``[]`` (no filter). Tokens already spelled as DeepSeek tool
    names, and unknown tokens, pass through lowercased so nothing is silently
    dropped. Order is preserved and duplicates removed.
    """
    m = matcher.strip()
    if m in ("", "*", ".*"):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for tok in m.split("|"):
        key = tok.strip().lower()
        if not key:
            continue
        for name in FOREIGN_TOOL_NAME_MAP.get(key, (key,)):
            if name not in seen:
                seen.add(name)
                result.append(name)
    return result


def matcher_to_condition(matcher: str | None) -> dict[str, object] | None:
    """Build a lifecycle-hook ``condition`` from a foreign tool ``matcher``.

    Returns a ``tool_name_any`` condition over the mapped DeepSeek tool names,
    or ``None`` when the matcher targets every tool (no filter).
    """
    if not matcher:
        return None
    names = map_tool_matcher(matcher)
    if not names:
        return None
    return {"type": "tool_name_any", "names": names}


# ── Source-level normalization (runs on the installed copy) ─────────────────

# CodeBuddy hook env vars → canonical Claude vars. Project-dir maps to the env
# var the hook runner exports at execution time (see hooks.HookContext).
_HOOK_VAR_REWRITES = (
    ("${CODEBUDDY_PLUGIN_ROOT}", "${CLAUDE_PLUGIN_ROOT}"),
    ("${CODEBUDDY_PROJECT_DIR}", "${CLAUDE_PROJECT_DIR}"),
)


def _rewrite_hook_commands_and_matchers(obj: object) -> object:
    """Recursively rewrite ``command`` var tokens and ``matcher`` tool names.

    Works on the Claude/CodeBuddy ``{Event: [{matcher, hooks: [...]}]}`` tree.
    Matchers are rewritten to a ``|``-alternation of DeepSeek tool names so the
    on-disk file is self-describing in our taxonomy (the loader also maps at
    read time, so behavior is identical either way).
    """
    if isinstance(obj, dict):
        out: dict[str, object] = {}
        for key, value in obj.items():
            if key == "command" and isinstance(value, str):
                for old, new in _HOOK_VAR_REWRITES:
                    value = value.replace(old, new)
                out[key] = value
            elif key == "matcher" and isinstance(value, str):
                mapped = map_tool_matcher(value)
                out[key] = "|".join(mapped) if mapped else value
            else:
                out[key] = _rewrite_hook_commands_and_matchers(value)
        return out
    if isinstance(obj, list):
        return [_rewrite_hook_commands_and_matchers(item) for item in obj]
    return obj


def _normalize_manifest_location(dest: Path, notes: list[str]) -> Path | None:
    """Move a ``.codebuddy-plugin`` manifest to the canonical ``.claude-plugin``.

    Returns the path of the canonical manifest (existing or newly written), or
    ``None`` if there is nothing to do / no manifest.
    """
    claude = dest / ".claude-plugin" / "plugin.json"
    if claude.is_file():
        return claude
    codebuddy = dest / ".codebuddy-plugin" / "plugin.json"
    if not codebuddy.is_file():
        return None
    try:
        data = json.loads(codebuddy.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return codebuddy  # leave the loader's fallback to handle it
    claude.parent.mkdir(parents=True, exist_ok=True)
    claude.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    shutil.rmtree(dest / ".codebuddy-plugin", ignore_errors=True)
    notes.append(".codebuddy-plugin → .claude-plugin")
    return claude


def _normalize_hooks_file(dest: Path, manifest_path: Path, notes: list[str]) -> None:
    """Rewrite the plugin's hooks file (vars + matchers) in canonical form."""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    hooks_ref = manifest.get("hooks")
    if not isinstance(hooks_ref, str):
        return
    hooks_path = (dest / hooks_ref).resolve()
    try:
        hooks_path.relative_to(dest.resolve())
    except ValueError:
        return
    if not hooks_path.is_file():
        return
    try:
        raw = json.loads(hooks_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    rewritten = _rewrite_hook_commands_and_matchers(raw)
    if rewritten != raw:
        hooks_path.write_text(
            json.dumps(rewritten, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        notes.append(f"normalized hooks: {hooks_ref}")


def normalize_installed_plugin(dest: Path) -> list[str]:
    """Normalize an installed plugin copy into canonical form, in place.

    Idempotent and best-effort: any failure leaves the files untouched and the
    runtime loader's tolerance shims take over. Returns human-readable notes of
    what changed (empty when the plugin was already canonical).
    """
    notes: list[str] = []
    if not dest.is_dir():
        return notes
    manifest_path = _normalize_manifest_location(dest, notes)
    if manifest_path is not None:
        _normalize_hooks_file(dest, manifest_path, notes)
    return notes
