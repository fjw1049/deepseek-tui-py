"""Cross-ecosystem plugin compatibility shims.

Canonical plugin format = **Claude Code layout + DeepSeek extensions** (the
``rules`` injection and ``permissions``). Plugins authored for other ecosystems
(CodeBuddy / WorkBuddy) are *not* rewritten on disk - format adapters in
``deepseek_tui.plugins.adapters`` map foreign layouts at read time, and the
runtime loader applies the tolerance shims below as a fallback.

All ecosystem-specific knowledge is isolated here, on purpose: adding a new
ecosystem means editing this module, not the hot-path loader.
"""

from __future__ import annotations

__all__ = [
    "FOREIGN_TOOL_NAME_MAP",
    "map_tool_matcher",
    "matcher_to_condition",
]

# Foreign (Claude Code / CodeBuddy) tool names -> DeepSeek runtime tool names.
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
