"""Message context formatting and working set.

Consolidates context.py, project_context.py, working_set.py.
"""

from __future__ import annotations



# ======================================================================
# From context.py
# ======================================================================

"""Context budgeting and prompt-shaping helpers for the engine.

Mirrors `crates/tui/src/core/engine/context.rs:1-382`.
Shared by the streaming turn loop, capacity flow, and engine session
maintenance code.
"""


import json
import math
from typing import Any

from deepseek_tui.config.providers import context_window_for_model
from deepseek_tui.protocol.messages import Message
from deepseek_tui.tools.registry import ToolResult

# --- Constants (Rust context.rs:17-44) -----------------------------------

TURN_MAX_OUTPUT_TOKENS = 262_144
MIN_RECENT_MESSAGES_TO_KEEP = 4
MAX_CONTEXT_RECOVERY_ATTEMPTS = 2
CONTEXT_HEADROOM_TOKENS = 1024

TOOL_RESULT_CONTEXT_HARD_LIMIT_CHARS = 12_000
TOOL_RESULT_CONTEXT_SOFT_LIMIT_CHARS = 2_000
TOOL_RESULT_CONTEXT_SNIPPET_CHARS = 900

LARGE_CONTEXT_TOOL_RESULT_HARD_LIMIT_CHARS = 40_000
LARGE_CONTEXT_TOOL_RESULT_SOFT_LIMIT_CHARS = 15_000
LARGE_CONTEXT_TOOL_RESULT_SNIPPET_CHARS = 10_000

LARGE_CONTEXT_WINDOW_TOKENS = 500_000

TOOL_RESULT_METADATA_SUMMARY_CHARS = 320

COMPACTION_SUMMARY_MARKER = "Conversation Summary (Auto-Generated)"
WORKING_SET_SUMMARY_MARKER = "## Repo Working Set"

# --- Text summarization (Rust context.rs:52-84) --------------------------


def summarize_text(text: str, limit: int) -> str:
    """Truncate text to limit characters, appending '...' if cut."""
    if len(text) <= limit:
        return text
    take = max(0, limit - 3)
    return text[:take] + "..."


def summarize_text_head_tail(text: str, limit: int) -> str:
    """Keep head + tail of text with a truncation marker in the middle."""
    total = len(text)
    if total <= limit:
        return text
    if limit <= 20:
        return summarize_text(text, limit)

    marker = "\n\n[... output truncated for context ...]\n\n"
    marker_len = len(marker)
    if limit <= marker_len + 20:
        return summarize_text(text, limit)

    remaining = limit - marker_len
    head_len = (remaining * 2) // 3
    tail_len = remaining - head_len
    return text[:head_len] + marker + text[total - tail_len :]


# --- Tool result compaction (Rust context.rs:86-263) ----------------------

_NOISY_TOOLS = frozenset(
    {
        "exec_shell",
        "exec_shell_wait",
        "exec_shell_interact",
        "multi_tool_use.parallel",
        "web_search",
    }
)


def _tool_result_is_noisy(tool_name: str) -> bool:
    return tool_name in _NOISY_TOOLS


def _tool_result_metadata_summary(metadata: dict[str, Any] | None) -> str | None:
    if not metadata or not isinstance(metadata, dict):
        return None
    for key in ("summary", "stdout_summary", "stderr_summary", "message"):
        val = metadata.get(key)
        if isinstance(val, str) and val.strip():
            return summarize_text(val.strip(), TOOL_RESULT_METADATA_SUMMARY_CHARS)
    return None


def _summarize_subagent_status(status: Any) -> str:
    if isinstance(status, str):
        return status
    if isinstance(status, dict):
        for kind, value in status.items():
            if isinstance(value, str) and value.strip():
                return f"{kind}({summarize_text(value.strip(), 120)})"
            return str(kind)
    return str(status)


def _summarize_subagent_snapshot(snapshot: Any, index: int) -> str:
    if not isinstance(snapshot, dict):
        return f"- item {index}: {summarize_text(str(snapshot), 240)}"

    lines: list[str] = []

    result = snapshot.get("result")
    if isinstance(result, str) and result.strip():
        lines.append(f"- result: {summarize_text(result.strip(), 1600)}")
    else:
        lines.append("- result: (not available yet)")

    meta: list[str] = []
    agent_id = snapshot.get("agent_id")
    if isinstance(agent_id, str) and agent_id.strip():
        meta.append(f"id={agent_id}")
    agent_type = snapshot.get("agent_type")
    if isinstance(agent_type, str) and agent_type.strip():
        meta.append(f"type={agent_type}")
    status = _summarize_subagent_status(snapshot.get("status", "unknown"))
    if status and status != "unknown":
        meta.append(f"status={status}")

    assignment = snapshot.get("assignment")
    if isinstance(assignment, dict):
        objective = assignment.get("objective")
        if isinstance(objective, str) and objective.strip():
            meta.append(f"objective={summarize_text(objective.strip(), 120)}")

    steps = snapshot.get("steps_taken")
    duration_ms = snapshot.get("duration_ms")
    if steps is not None or duration_ms is not None:
        s = str(steps) if steps is not None else "?"
        d = str(duration_ms) if duration_ms is not None else "?"
        meta.append(f"steps={s}, duration_ms={d}")

    if meta:
        lines.append(f"  ({'; '.join(meta)})")

    return "\n".join(lines)


def _compact_subagent_tool_result_for_context(
    tool_name: str, raw: str
) -> str | None:
    """Compact agent_result / agent_wait payloads for parent context."""
    if tool_name not in ("agent_result", "agent_wait", "wait"):
        return None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None

    if isinstance(parsed, list):
        snapshots = parsed
    elif isinstance(parsed, dict):
        snapshots = [parsed]
    else:
        return None

    out = [
        "[sub-agent result summarized for parent context]",
        "Lead with the result body; metadata is for routing only.",
        "Child results are self-reports — verify side effects with tools before claiming success.",
    ]
    for idx, snap in enumerate(snapshots):
        if idx >= 8:
            remaining = len(snapshots) - idx
            out.append(
                f"- ... {remaining} more sub-agent result(s) omitted from context summary"
            )
            break
        out.append(_summarize_subagent_snapshot(snap, idx + 1))
    return "\n".join(out)


def _tool_result_context_limits(model: str) -> tuple[int, int, int]:
    """Return (hard_limit, noisy_soft_limit, snippet) for the model."""
    window = context_window_for_model(model)
    if window >= LARGE_CONTEXT_WINDOW_TOKENS:
        return (
            LARGE_CONTEXT_TOOL_RESULT_HARD_LIMIT_CHARS,
            LARGE_CONTEXT_TOOL_RESULT_SOFT_LIMIT_CHARS,
            LARGE_CONTEXT_TOOL_RESULT_SNIPPET_CHARS,
        )
    return (
        TOOL_RESULT_CONTEXT_HARD_LIMIT_CHARS,
        TOOL_RESULT_CONTEXT_SOFT_LIMIT_CHARS,
        TOOL_RESULT_CONTEXT_SNIPPET_CHARS,
    )


def compact_tool_result_for_context(
    model: str, tool_name: str, output: ToolResult
) -> str:
    """Compact a tool result before inserting into the model transcript.

    Mirrors Rust ``compact_tool_result_for_context`` (context.rs:228-263).
    """
    raw = output.content.strip()
    if not raw:
        return ""

    subagent = _compact_subagent_tool_result_for_context(tool_name, raw)
    if subagent is not None:
        return subagent

    hard_limit, noisy_soft, snippet_chars = _tool_result_context_limits(model)
    raw_len = len(raw)
    should_compact = raw_len > hard_limit or (
        _tool_result_is_noisy(tool_name) and raw_len > noisy_soft
    )
    if not should_compact:
        return raw

    snippet = summarize_text_head_tail(raw, snippet_chars)
    omitted = raw_len - len(snippet)
    summary = _tool_result_metadata_summary(output.metadata)

    if summary:
        return (
            f"[{tool_name} output compacted to protect context]\n"
            f"Summary: {summary}\n"
            f"Snippet: {snippet}\n"
            f"(Original: {raw_len} chars, omitted: {omitted} chars.)"
        )
    return (
        f"[{tool_name} output compacted to protect context]\n"
        f"Snippet: {snippet}\n"
        f"(Original: {raw_len} chars, omitted: {omitted} chars.)"
    )


# --- System prompt management (Rust context.rs:265-339) -------------------


def extract_compaction_summary_prompt(prompt: str | None) -> str | None:
    """Extract compaction summary block from a system prompt string.

    Recognizes both the legacy marker and the ``<archived_context>`` tag
    actually emitted by ``compaction._build_summary_system_prompt`` — the
    two had drifted apart, making this function never match real output.
    """
    if not prompt:
        return None
    if COMPACTION_SUMMARY_MARKER not in prompt and "<archived_context>" not in prompt:
        return None
    return prompt


def remove_working_set_summary(prompt: str | None) -> str | None:
    """Remove the working-set summary block from a system prompt."""
    if not prompt:
        return None
    lines = prompt.split("\n")
    filtered = [line for line in lines if WORKING_SET_SUMMARY_MARKER not in line]
    result = "\n".join(filtered).strip()
    return result or None


def append_working_set_summary(
    prompt: str | None, working_set_summary: str | None
) -> str | None:
    """Append a working-set summary to the system prompt."""
    summary = (working_set_summary or "").strip()
    if not summary:
        return prompt
    base = remove_working_set_summary(prompt) or ""
    if base:
        return f"{base}\n\n{summary}"
    return summary


# --- Token estimation (Rust context.rs:341-378) --------------------------


def _estimate_text_tokens_conservative(text: str) -> int:
    return math.ceil(len(text) / 3)


def estimate_input_tokens_conservative(
    messages: list[Message], system_prompt: str | None = None
) -> int:
    """Conservative estimate of input tokens including system prompt.

    Mirrors Rust ``estimate_input_tokens_conservative`` (context.rs:356-366).
    """
    msg_chars = 0
    for msg in messages:
        for block in msg.content:
            for attr in ("text", "content", "input"):
                val = getattr(block, attr, None)
                if isinstance(val, str):
                    msg_chars += len(val)
                elif isinstance(val, dict):
                    msg_chars += len(json.dumps(val))
    message_tokens = (msg_chars * 3) // 2  # conservative 1.5x

    system_tokens = (
        _estimate_text_tokens_conservative(system_prompt) if system_prompt else 0
    )

    framing_overhead = len(messages) * 12 + 48

    return message_tokens + system_tokens + framing_overhead


def context_input_budget(model: str, requested_output_tokens: int) -> int | None:
    """Calculate usable input token budget after reserving output + headroom.

    Mirrors Rust ``context_input_budget`` (context.rs:368-374), with one
    fix: the output reservation is clamped to a quarter of the window.
    Without the clamp, models whose window is smaller than the requested
    output reservation (e.g. 128K window vs 262K reservation) computed a
    negative budget and silently skipped overflow prechecks entirely.
    """
    window = context_window_for_model(model)
    reserve = min(requested_output_tokens, window // 4)
    budget = window - reserve - CONTEXT_HEADROOM_TOKENS
    return budget if budget > 0 else None


def turn_response_headroom_tokens() -> int:
    return TURN_MAX_OUTPUT_TOKENS + CONTEXT_HEADROOM_TOKENS


def is_context_length_error_message(message: str) -> bool:
    """Heuristic check for context-length errors from the provider."""
    lower = message.lower()
    return any(
        needle in lower
        for needle in (
            "context length",
            "context_length",
            "maximum context",
            "token limit",
            "too many tokens",
            "reduce the length",
            "context window",
        )
    )


# --- Legacy aliases (keep backward compatibility with turn_loop) ----------

def estimated_input_tokens(messages: list[Message]) -> int:
    """Rough estimate of input tokens from message list (legacy)."""
    total_chars = 0
    for m in messages:
        total_chars += len(json.dumps(m.model_dump()))
    return max(1, total_chars // 4)


def _api_tool_name(tool: dict[str, Any]) -> str:
    function = tool.get("function")
    if not isinstance(function, dict):
        return ""
    name = function.get("name")
    return name if isinstance(name, str) else ""


def _tool_schema_buckets(api_tools: list[dict[str, Any]] | None) -> tuple[int, int]:
    if not api_tools:
        return 0, 0

    from deepseek_tui.engine.dispatch import is_mcp_tool

    tool_definitions = 0
    mcp = 0
    for tool in api_tools:
        tokens = _estimate_text_tokens_conservative(json.dumps(tool, ensure_ascii=False))
        if is_mcp_tool(_api_tool_name(tool)):
            mcp += tokens
        else:
            tool_definitions += tokens
    return tool_definitions, mcp


def estimate_context_breakdown(
    *,
    model: str,
    messages: list[Message] | None = None,
    system_prompt_override: str | None = None,
    skills_context: str | None = None,
    working_set_summary: str | None = None,
    api_tools: list[dict[str, Any]] | None = None,
    workspace: Any | None = None,
    mode: str = "agent",
) -> dict[str, int]:
    """Estimate token occupancy by category for the next request.

    Shared by :meth:`Engine.context_breakdown`, TUI ``/context``, and the
    Workbench runtime API.

    ``tools`` and ``free`` are retained for old Workbench/TUI clients. Newer
    clients should prefer the more explainable top-level buckets:
    ``tool_definitions``, ``mcp``, ``skills``, ``rules``, and ``conversation``.
    """
    from pathlib import Path

    from deepseek_tui.engine.prompts import build_system_prompt
    from deepseek_tui.engine.prompts import AppMode

    target_model = model or ""
    try:
        app_mode = AppMode((mode or "agent").strip().lower())
    except ValueError:
        app_mode = AppMode.AGENT
    if system_prompt_override and system_prompt_override.strip():
        system_tokens = _estimate_text_tokens_conservative(
            system_prompt_override.strip()
        )
        rules_tokens = 0
        skills_tokens = 0
    else:
        ws = Path(workspace).expanduser().resolve() if workspace else None
        system_text = build_system_prompt(
            None,
            working_set_summary=working_set_summary,
            workspace=ws,
            mode=app_mode,
            project_context_enabled=False,
        )
        system_tokens = _estimate_text_tokens_conservative(system_text)

        rules_text = ""
        if ws is not None:

            rules_text = load_project_context_with_parents(ws).as_system_block()
        rules_tokens = (
            _estimate_text_tokens_conservative(rules_text.strip())
            if rules_text.strip()
            else 0
        )
        skills_tokens = (
            _estimate_text_tokens_conservative(skills_context.strip())
            if skills_context and skills_context.strip()
            else 0
        )

    tool_definitions_tokens, mcp_tokens = _tool_schema_buckets(api_tools)
    tools_tokens = tool_definitions_tokens + mcp_tokens

    conv_tokens = estimated_input_tokens(messages) if messages else 0
    total = (
        system_tokens
        + rules_tokens
        + skills_tokens
        + tools_tokens
        + conv_tokens
    )
    window = context_window_for_model(target_model) or 0
    free = max(0, window - total) if window else 0

    return {
        "system_prompt": system_tokens,
        "tool_definitions": tool_definitions_tokens,
        "tools": tools_tokens,
        "mcp": mcp_tokens,
        "skills": skills_tokens,
        "rules": rules_tokens,
        "conversation": conv_tokens,
        "total": total,
        "window": window,
        "free": free,
    }


# ======================================================================
# From project_context.py
# ======================================================================

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


# ======================================================================
# From working_set.py
# ======================================================================

"""Working set management for tracking user-relevant files and context.

Mirrors `crates/tui/src/session/working_set.rs`
"""


from pathlib import Path
from typing import Any

from deepseek_tui.protocol.messages import Message


class WorkingSet:
    """Tracks files and context relevant to current user work.

    Mirrors Rust WorkingSet for pinning decisions during compaction.
    """

    _MAX_RECENT_PATHS = 100

    def __init__(self, workspace: Path | None = None) -> None:
        """Initialize working set.

        Args:
            workspace: Root workspace directory
        """
        self.workspace = workspace
        self.recent_paths: set[str] = set()
        self.recent_tool_uses: list[str] = []
        self.message_count: int = 0

    def observe_user_message(self, text: str, workspace: Path | None = None) -> None:
        """Observe user message and extract relevant paths."""
        self.message_count += 1
        self._extract_paths_from_text(text, workspace)

    def observe_references(self, references: list[Any]) -> None:
        """Track paths from expanded @mention context references."""
        for ref in references:
            target = getattr(ref, "target", None)
            if isinstance(target, str) and target:
                normalized = self._normalize_path(target, self.workspace)
                if normalized:
                    self.recent_paths.add(normalized)
        if len(self.recent_paths) > self._MAX_RECENT_PATHS:
            excess = len(self.recent_paths) - self._MAX_RECENT_PATHS
            for path in list(self.recent_paths)[:excess]:
                self.recent_paths.discard(path)

    def observe_tool_call(
        self,
        tool_name: str,
        tool_input: dict[str, Any] | None,
        tool_output: str | None = None,
        workspace: Path | None = None,
    ) -> None:
        """Observe tool execution and track usage."""
        self.recent_tool_uses.append(tool_name)
        if len(self.recent_tool_uses) > 20:
            self.recent_tool_uses.pop(0)

        if tool_input:
            self._extract_paths_from_dict(tool_input, workspace)

        if tool_output:
            self._extract_paths_from_text(tool_output, workspace)

    def pinned_message_indices(
        self,
        messages: list[Message],
        workspace: Path | None = None,
    ) -> set[int]:
        """Determine which message indices should be pinned during compaction.

        Always pins:
        - Last 4 messages (KEEP_RECENT_MESSAGES)

        Also pins messages that reference working set files.
        """
        if not messages:
            return set()

        pinned: set[int] = set()

        # Always keep last 4 messages
        keep_recent = 4
        for i in range(max(0, len(messages) - keep_recent), len(messages)):
            pinned.add(i)

        # Pin messages that reference working set paths
        for idx, msg in enumerate(messages):
            if self._message_references_working_set(msg, workspace):
                pinned.add(idx)

        return pinned

    def top_paths(self, limit: int = 24) -> list[str]:
        """Get top working set paths for compaction context.

        Args:
            limit: Maximum number of paths to return

        Returns:
            List of paths, limited to most recent
        """
        paths = list(self.recent_paths)
        return paths[-limit:]

    def summary(self, limit: int = 24) -> str:
        """Produce a human-readable summary block for cycle carry-forward."""
        paths = self.top_paths(limit)
        if not paths:
            return ""
        lines = ["### Working Set (recent files)"]
        for p in paths:
            lines.append(f"- `{p}`")
        return "\n".join(lines)

    def _extract_paths_from_text(self, text: str, workspace: Path | None = None) -> None:
        """Extract file paths from text."""
        if not text:
            return

        # Simple path extraction: look for common patterns
        import re

        # Match common path patterns
        pattern = (
            r"(?:^|\s)([./][^\s\"\']*\.(?:py|rs|toml|json|yaml|md|txt|sh))"
        )
        for match in re.finditer(pattern, text):
            path = match.group(1)
            if path and len(path) > 2:
                normalized = self._normalize_path(path, workspace)
                if normalized:
                    self.recent_paths.add(normalized)
        if len(self.recent_paths) > self._MAX_RECENT_PATHS:
            excess = len(self.recent_paths) - self._MAX_RECENT_PATHS
            for path in list(self.recent_paths)[:excess]:
                self.recent_paths.discard(path)

    def _extract_paths_from_dict(
        self, obj: dict[str, Any], workspace: Path | None = None
    ) -> None:
        """Extract file paths from tool input dictionary."""
        if not obj:
            return

        # Check common path keys
        for key in ["path", "file", "target", "cwd"]:
            if key in obj and isinstance(obj[key], str):
                path = obj[key]
                normalized = self._normalize_path(path, workspace)
                if normalized:
                    self.recent_paths.add(normalized)

        # Check list-based path keys
        for key in ["paths", "files", "targets"]:
            if key in obj and isinstance(obj[key], list):
                for item in obj[key]:
                    if isinstance(item, str):
                        normalized = self._normalize_path(item, workspace)
                        if normalized:
                            self.recent_paths.add(normalized)

    def _normalize_path(self, path: str, workspace: Path | None = None) -> str | None:
        """Normalize a path candidate.

        Returns None if not a valid path, otherwise a normalized string.
        """
        if not path or len(path) < 2:
            return None

        # Skip very long paths
        if len(path) > 500:
            return None

        # Convert to Path for validation
        try:
            p = Path(path)
            # Return as string for working set tracking
            return str(p)
        except (ValueError, OSError):
            return None

    def _message_references_working_set(
        self, msg: Message, workspace: Path | None = None
    ) -> bool:
        """Check if message references any working set paths."""
        if not self.recent_paths:
            return False

        for block in msg.content:
            text = getattr(block, "text", None)
            if isinstance(text, str) and any(
                path in text for path in self.recent_paths
            ):
                return True
            content = getattr(block, "content", None)
            if isinstance(content, str) and any(
                path in content for path in self.recent_paths
            ):
                return True

        return False
