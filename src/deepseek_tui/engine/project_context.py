"""Project context loader — discovers AGENTS.md / CLAUDE.md / instructions.

Mirrors Rust ``crates/tui/src/project_context.rs``. Resolves the first
project-instruction file found, walks up parent directories for monorepo
setups, falls back to a user-level ``~/.deepseek/AGENTS.md``, and finally
auto-generates a placeholder ``<workspace>/.deepseek/instructions.md`` so
the engine has *something* to anchor on.

The loaded content is wrapped as::

    <project_instructions source="<path>">
    <content>
    </project_instructions>

and injected into the system prompt by ``engine/prompts.py``. Without this
the model never sees ``AGENTS.md`` / ``CLAUDE.md`` — they sit on disk and
do nothing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from deepseek_tui.config.paths import (
    project_deepseek_dir,
    project_instructions_path,
    user_agents_path,
)

logger = logging.getLogger(__name__)


# Candidate context files, in priority order. Mirrors Rust
# ``PROJECT_CONTEXT_FILES`` (project_context.rs:22-27).
PROJECT_CONTEXT_FILES: tuple[str, ...] = (
    "AGENTS.md",
    ".claude/instructions.md",
    "CLAUDE.md",
    ".deepseek/instructions.md",
)

# Hard cap to keep a malicious / oversized include from blowing the prompt
# budget on its own (Rust ``MAX_CONTEXT_SIZE`` = 100 KB).
MAX_CONTEXT_SIZE: int = 100 * 1024


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ProjectContext:
    """Result of loading project context.

    Mirrors Rust ``ProjectContext`` (project_context.rs:80-93). The
    ``warnings`` list surfaces non-fatal load failures (file too large,
    empty, unreadable) so callers can show them without aborting startup.
    """

    project_root: Path
    instructions: str | None = None
    source_path: Path | None = None
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def empty(cls, project_root: Path) -> ProjectContext:
        return cls(project_root=project_root)

    def has_instructions(self) -> bool:
        return self.instructions is not None

    def as_system_block(self) -> str | None:
        """Format the instructions as a system-prompt block.

        Mirrors Rust ``as_system_block`` (project_context.rs:113-124).
        """
        if self.instructions is None:
            return None
        source = (
            str(self.source_path) if self.source_path is not None else "project"
        )
        return (
            f'<project_instructions source="{source}">\n'
            f"{self.instructions}\n"
            f"</project_instructions>"
        )


# ---------------------------------------------------------------------------
# File loading
# ---------------------------------------------------------------------------


def _load_context_file(path: Path) -> str:
    """Read ``path`` with size and emptiness checks.

    Raises ``ValueError`` for too-large / empty / unreadable files; the
    caller turns the message into a warning.
    """
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ValueError(f"Failed to stat context file {path}: {exc}") from exc

    if size > MAX_CONTEXT_SIZE:
        raise ValueError(
            f"Context file {path} is too large ({size} bytes, max {MAX_CONTEXT_SIZE})"
        )

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Failed to read context file {path}: {exc}") from exc

    if not content.strip():
        raise ValueError(f"Context file {path} is empty")

    return content


# ---------------------------------------------------------------------------
# Workspace-scoped lookup
# ---------------------------------------------------------------------------


def load_project_context(workspace: Path) -> ProjectContext:
    """Load the first project-context file found under ``workspace``.

    Mirrors Rust ``load_project_context`` (project_context.rs:327-352).
    Returns an empty context if no candidate file is present or readable.
    Warnings collect non-fatal failures.
    """
    ctx = ProjectContext.empty(workspace)
    for filename in PROJECT_CONTEXT_FILES:
        file_path = workspace / filename
        if not (file_path.exists() and file_path.is_file()):
            continue
        try:
            ctx.instructions = _load_context_file(file_path)
            ctx.source_path = file_path
            return ctx
        except ValueError as exc:
            ctx.warnings.append(str(exc))
    return ctx


# ---------------------------------------------------------------------------
# Parent-directory recursion + user-level fallback + auto-generate
# ---------------------------------------------------------------------------


def load_project_context_with_parents(
    workspace: Path,
    *,
    home_dir: Path | None = None,
) -> ProjectContext:
    """Full project-context resolution.

    Mirrors Rust ``load_project_context_with_parents_and_home``
    (project_context.rs:361-413).

    Search order:
      1. ``workspace`` itself
      2. parent directories, recursively (monorepo support)
      3. ``~/.deepseek/AGENTS.md`` (user-level fallback)
      4. auto-generate ``<ws>/.deepseek/instructions.md``

    The optional ``home_dir`` parameter is for tests; production callers
    omit it and the function uses the real ``~/.deepseek/AGENTS.md``.
    """
    ctx = load_project_context(workspace)

    # 2. Walk parents for monorepo setups.
    if not ctx.has_instructions():
        current = workspace.parent
        seen: set[Path] = {workspace.resolve()}
        while current is not None:
            resolved = current.resolve()
            if resolved in seen:  # reached filesystem root, parent is itself
                break
            seen.add(resolved)
            parent_ctx = load_project_context(current)
            ctx.warnings.extend(parent_ctx.warnings)
            if parent_ctx.has_instructions():
                ctx.instructions = parent_ctx.instructions
                ctx.source_path = parent_ctx.source_path
                break
            next_parent = current.parent
            if next_parent == current:
                break
            current = next_parent

    # 3. User-level fallback (~/.deepseek/AGENTS.md).
    if not ctx.has_instructions():
        global_ctx = _load_global_agents_context(workspace, home_dir)
        if global_ctx is not None:
            ctx.warnings.extend(global_ctx.warnings)
            if global_ctx.has_instructions():
                ctx.instructions = global_ctx.instructions
                ctx.source_path = global_ctx.source_path

    # 4. Auto-generate as last resort. Writes to disk so subsequent loads
    #    are cached at the filesystem layer (Rust comment: avoids per-turn
    #    scan that breaks KV prefix cache stability).
    if not ctx.has_instructions():
        generated = _auto_generate_context(workspace)
        if generated is not None:
            reload_ctx = load_project_context(workspace)
            ctx.warnings.extend(reload_ctx.warnings)
            if reload_ctx.has_instructions():
                ctx.instructions = reload_ctx.instructions
                ctx.source_path = reload_ctx.source_path
            else:
                # Disk write succeeded but reload didn't find it (rare race
                # — e.g. workspace path mismatch). Inline the generated
                # content so the prompt still has *something*.
                ctx.instructions = generated
                ctx.source_path = None

    return ctx


def _load_global_agents_context(
    workspace: Path,
    home_dir: Path | None,
) -> ProjectContext | None:
    """Read ``~/.deepseek/AGENTS.md`` (or ``<home_dir>/.deepseek/AGENTS.md``
    when overridden for tests).
    """
    if home_dir is not None:
        path = home_dir / ".deepseek" / "AGENTS.md"
    else:
        path = user_agents_path()

    if not (path.exists() and path.is_file()):
        return None

    ctx = ProjectContext.empty(workspace)
    try:
        ctx.instructions = _load_context_file(path)
        ctx.source_path = path
    except ValueError as exc:
        ctx.warnings.append(str(exc))
    return ctx


# ---------------------------------------------------------------------------
# Auto-generation
# ---------------------------------------------------------------------------


_AUTO_GENERATED_TEMPLATE = """\
# Project Instructions (Auto-generated)

> This file was automatically generated by DeepSeek TUI as a fallback
> because no `AGENTS.md`, `CLAUDE.md`, or `.deepseek/instructions.md` was
> found in the workspace or any parent directory.
>
> **You should replace this with project-specific guidance.** Edit this
> file, or — better — write a real `AGENTS.md` at the project root.
> See https://agentmd.org for the convention.
>
> Until you do, the agent has no idea what conventions, build commands,
> or architectural rules apply to this codebase.
"""


def _auto_generate_context(workspace: Path) -> str | None:
    """Write a placeholder ``<workspace>/.deepseek/instructions.md``.

    Mirrors Rust ``auto_generate_context`` (project_context.rs:439-475)
    but skips the project-tree summary — that lives in the optional
    ``ProjectContextPack`` (Stage-4 work), not the load chain.

    Returns the generated content on success, ``None`` on failure (no
    HOME, permission error, etc.). Never raises.
    """
    instructions_path = project_instructions_path(workspace)
    if instructions_path.exists():
        return None

    try:
        project_deepseek_dir(workspace).mkdir(parents=True, exist_ok=True)
        instructions_path.write_text(_AUTO_GENERATED_TEMPLATE, encoding="utf-8")
    except OSError as exc:
        logger.warning("auto-generate failed at %s: %s", instructions_path, exc)
        return None

    logger.info("auto-generated %s", instructions_path)
    return _AUTO_GENERATED_TEMPLATE
