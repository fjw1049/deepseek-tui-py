"""Evolution prompt constants."""

from __future__ import annotations

EVOLUTION_GUIDANCE = (
    "## Curated Memory (memory_curate)\n\n"
    "Use `memory_curate` for durable preferences, project conventions, and "
    "workflow facts — not transient task progress (use `conversation_search`).\n\n"
    "- `target=memory`: agent notes (patterns, pitfalls, repo quirks)\n"
    "- `target=user`: user profile (preferences, constraints, identity)\n"
    "- Prefer `add`; if at capacity the tool returns `usage` and `current_entries` — "
    "then `replace` or `remove` before adding\n"
    "- One fact per §-separated entry; keep entries concise"
)

SKILLS_EVOLUTION_GUIDANCE = (
    "## Procedural Skills (skill_manage)\n\n"
    "Use `skill_manage` for repeatable procedures (deploy, review checklist, "
    "codegen patterns) — not one-off task state.\n\n"
    "- `create` for new skills; `patch` with `file_path` for SKILL.md or supporting files\n"
    "- YAML frontmatter `name` and `description` required in SKILL.md\n"
    "- Skills = how-to; curated memory = what-you-know; conversation_search = past task context"
)

EVOLUTION_REVIEW_SYSTEM = (
    "You are a background memory curator. Review the conversation excerpt and "
    "update curated memory and/or skills using only the provided tools. Be "
    "conservative: only persist durable, reusable knowledge. Do not repeat "
    "volatile task state."
)

MEMORY_REVIEW_USER = (
    "Review this turn for durable agent notes (MEMORY) worth curating. "
    "Use memory_curate if needed."
)

SKILL_REVIEW_USER = (
    "Review this turn for repeatable procedures worth capturing as skills. "
    "Use skill_manage if needed."
)

COMBINED_REVIEW_USER = (
    "Review this turn for both curated memory updates and procedural skills."
)

FLUSH_USER = (
    "Session is ending or context is being compacted. Flush any remaining "
    "durable notes to curated memory and skills before they are lost. "
    "Be concise and high-signal."
)
