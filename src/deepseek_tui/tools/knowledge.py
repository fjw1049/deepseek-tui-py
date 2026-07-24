"""Plan, note, and skill_load tools."""

from __future__ import annotations



import os
from pathlib import Path
from typing import Any

from deepseek_tui.tools.registry import ToolCapability, ToolError, ToolResult, ToolSpec
from deepseek_tui.tools.registry import ToolContext

# ===========================================================================
# note — quick note tool
# ===========================================================================


class NoteTool(ToolSpec):
    """Append a quick note to the session notes file."""

    def name(self) -> str:
        return "note"

    def description(self) -> str:
        return "Append a short note to the session notes file for later reference."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The note content.",
                }
            },
            "required": ["content"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        content = _require_string(input_data, "content")
        notes_path = _notes_path(context)
        notes_path.parent.mkdir(parents=True, exist_ok=True)

        entry = f"\n---\n{content.strip()}\n"
        with notes_path.open("a", encoding="utf-8") as f:
            f.write(entry)

        return ToolResult(
            success=True,
            content=f"Note appended to {notes_path}",
            metadata={"path": str(notes_path)},
        )


# ===========================================================================
# review — code review tool
# ===========================================================================

# ===========================================================================
# plan_update — update the agent's plan
# ===========================================================================


class PlanUpdateTool(ToolSpec):
    """Update the current execution plan."""

    def name(self) -> str:
        return "update_plan"

    def description(self) -> str:
        return (
            "Update the user-facing execution plan. Use ONLY for plan mode, "
            "when the user explicitly asks for a plan, or when the engine "
            "requires a plan first. This is NOT routine progress tracking — "
            "use checklist_write for that, and never maintain both for the "
            "same work."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "description": "The full updated plan (markdown string or structured step array).",
                    "oneOf": [
                        {"type": "string"},
                        {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "step": {"type": "string"},
                                    "title": {"type": "string"},
                                    "status": {"type": "string"},
                                },
                            },
                        },
                    ],
                },
                "explanation": {
                    "type": "string",
                    "description": "Short goal or summary for the plan.",
                },
            },
            "required": ["plan"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        from deepseek_tui.tui.sidebar import (
            parse_plan_markdown,
            parse_structured_plan_steps,
            sync_plan_store,
        )

        explanation_raw = input_data.get("explanation")
        explanation = (
            explanation_raw.strip()
            if isinstance(explanation_raw, str) and explanation_raw.strip()
            else None
        )
        plan_field = input_data.get("plan")
        structured_steps: list[dict[str, object]] | None = None
        plan_text: str
        if isinstance(plan_field, list):
            structured_steps = parse_structured_plan_steps(plan_field)
            lines = [
                f"- [{'x' if s['status'] == 'completed' else '~' if s['status'] == 'in_progress' else ' '}] {s['title']}"
                for s in structured_steps
            ]
            plan_text = "\n".join(lines)
        elif isinstance(plan_field, str):
            plan_text = plan_field
            structured_steps = parse_plan_markdown(plan_text)
        else:
            raise ToolError("Missing or invalid 'plan' (string markdown or step array)")

        plan_path = context.working_directory / ".deepseek" / "plan.md"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(plan_text, encoding="utf-8")
        sync_plan_store(
            context.metadata,
            explanation=explanation,
            plan_text=plan_text,
            structured_steps=structured_steps,
        )

        return ToolResult(
            success=True,
            content=f"Plan updated ({len(plan_text)} chars)",
            metadata={"path": str(plan_path), "steps": len(structured_steps or [])},
        )


# ===========================================================================
# skill_load — load a skill file into context
# ===========================================================================


class SkillLoadTool(ToolSpec):
    """Load a skill body + companion files into the next turn's context.

    The tool name is
    ``load_skill`` (verb-noun) to match the prompt-side trigger text the
    system message advertises — see ``render_available_skills_context``
    in ``skills/__init__.py``.

    Resolution is **registry-first**: we never invent a path from
    ``<skills_dir>/<name>/SKILL.md`` (community installs put the file
    under a directory whose name differs from the frontmatter ``name``,
    so a guessed path 404s). Instead we ask ``discover_in_workspace``
    for the path it parsed and read from there.
    """

    def name(self) -> str:
        return "load_skill"

    def description(self) -> str:
        return (
            "Load a skill (SKILL.md body + companion file list) into the "
            "next turn's context. Use this when the user names a skill or "
            "the task clearly matches a skill listed in the system prompt's "
            "`## Skills` section. Faster than read_file + list_dir."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": (
                        "Skill id — the `name` field from the SKILL.md "
                        "frontmatter, also shown in the `## Skills` listing."
                    ),
                },
                "path": {
                    "type": "string",
                    "description": (
                        "Escape hatch: direct path to a SKILL.md file. "
                        "Prefer `name` so the registry can locate companion "
                        "files in the same directory."
                    ),
                },
            },
            "required": [],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        # Accept both ``name`` and ``skill_name`` (legacy
        # Python alias) — the Python tool used to ship as ``skill_load``
        # with the latter param, so prompts cached against the old shape
        # still work after the rename.
        name = _optional_string(input_data, "name") or _optional_string(
            input_data, "skill_name"
        )
        path_str = _optional_string(input_data, "path")

        if path_str:
            skill_path = Path(path_str).expanduser()  # noqa: ASYNC240
            if not skill_path.exists():
                raise ToolError(f"Skill file not found: {skill_path}")
            content = skill_path.read_text(encoding="utf-8")
            return ToolResult(
                success=True,
                content=content,
                metadata={"path": str(skill_path)},
            )

        if not name:
            raise ToolError("`name` (or `path`) must be provided")

        from deepseek_tui.integrations.skills import (
            discover_in_workspace,
            skills_directories,
        )

        # Prefer the engine's merged skill registry (workspace + plugin
        # skills) when the tool runs inside an engine; fall back to a fresh
        # workspace discovery for engine-less contexts (tests, standalone).
        # Without this, plugin skills - which are merged into the engine
        # registry in Engine.create but not by discover_in_workspace - would
        # be unreachable by name despite being listed in the system prompt.
        registry = context.metadata.get("skill_registry") or discover_in_workspace(
            workspace=context.working_directory
        )
        skill = registry.get(name)
        if skill is None:
            available = registry.list_names()
            if available:
                hint = (
                    f"skill `{name}` not found. "
                    f"Available: {', '.join(available)}"
                )
            else:
                dirs = skills_directories(workspace=context.working_directory)
                if dirs:
                    hint = (
                        f"no skills installed. Searched: "
                        f"{', '.join(str(p) for p in dirs)}"
                    )
                else:
                    hint = (
                        "no skills directories found; install skills under "
                        "`<workspace>/.deepseek/skills/<name>/SKILL.md`, "
                        "`~/.claude/skills/<name>/SKILL.md`, or "
                        "`~/.deepseek/skills/<name>/SKILL.md`"
                    )
            raise ToolError(hint)

        body = _format_skill_body(skill)
        companions = _collect_companion_files(skill)
        return ToolResult(
            success=True,
            content=body,
            metadata={
                "skill_name": skill.name,
                "skill_path": str(skill.path),
                "companion_files": [str(p) for p in companions],
            },
        )


def _format_skill_body(skill: Any) -> str:
    """Render the tool-result body model will see.

    The description rides up top so a single tool result is self-contained
    (no need to cross-reference the system-prompt catalogue);
    companion-file paths land under a clearly-named heading so the
    model can open them with ``read_file`` when relevant.
    """
    out: list[str] = [f"# Skill: {skill.name}", ""]
    if skill.description.strip():
        out.append(f"> {skill.description.strip()}")
        out.append("")
    out.append(f"Source: `{skill.path}`")
    out.append("")
    out.append("## SKILL.md")
    out.append("")
    out.append(skill.body.strip())
    out.append("")

    companions = _collect_companion_files(skill)
    if companions:
        out.append("")
        out.append("## Companion files")
        out.append("")
        out.append(
            "Sibling files in the skill directory. Use `read_file` to "
            "open them when the task requires."
        )
        out.append("")
        for path in companions:
            out.append(f"- `{path}`")
    return "\n".join(out)


def _collect_companion_files(skill: Any) -> list[Path]:
    """List sibling files of SKILL.md.

    Skips the ``SKILL.md`` itself and any nested directories so the
    listing stays focused on at-hand resources. Sorted for determinism.
    """
    parent = skill.path.parent if isinstance(skill.path, Path) else Path(skill.path).parent
    if not parent.is_dir():
        return []
    return sorted(
        p for p in parent.iterdir()
        if p.is_file() and p.name != "SKILL.md"
    )


# ===========================================================================
# Helpers
# ===========================================================================


def _require_string(input_data: dict[str, object], key: str) -> str:
    value = input_data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"'{key}' must be a non-empty string")
    return value


def _optional_string(input_data: dict[str, object], key: str) -> str | None:
    value = input_data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ToolError(f"'{key}' must be a string")
    return value


def _notes_path(context: ToolContext) -> Path:
    """``~/.deepseek/notes.txt`` — user scratch notes.

    ``DEEPSEEK_NOTES_PATH`` env var overrides (used by tests to isolate
    writes from the real ``~/.deepseek/notes.txt``).
    """
    from deepseek_tui.config.paths import user_notes_path

    env = os.environ.get("DEEPSEEK_NOTES_PATH", "").strip()
    if env:
        return Path(env).expanduser()
    return user_notes_path()


