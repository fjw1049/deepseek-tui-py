"""Compact session-context inspector text renderer.

Mirrors ``crates/tui/src/tui/context_inspector.rs`` (466 LOC).

Builds the textual snapshot rendered by the ``/context`` slash command.
The Rust implementation reaches deep into ``App`` state; the Python port
takes a small :class:`InspectorSnapshot` dataclass so unit tests don't
need to spin up a Textual app and the engine layer can build the
snapshot from whatever live state it has at the time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from deepseek_tui.config.provider_registry import context_window_for_model
from deepseek_tui.engine.context import estimate_input_tokens_conservative
from deepseek_tui.protocol.messages import Message

WORKING_SET_MARKER: str = "## Repo Working Set"
CONTEXT_WARNING_THRESHOLD_PERCENT: float = 85.0
CONTEXT_CRITICAL_THRESHOLD_PERCENT: float = 95.0
MAX_REFERENCE_ROWS: int = 12
MAX_TOOL_ROWS: int = 8


@dataclass(slots=True)
class ContextReferenceView:
    """Mirror Rust ``SessionContextReference`` projected onto the inspector."""

    badge: str
    label: str
    target: str
    source: str = "at_mention"  # "at_mention" or "attachment"
    included: bool = True
    expanded: bool = False
    detail: str | None = None


@dataclass(slots=True)
class ToolDetailView:
    """Mirror Rust ``ToolDetailRecord`` projected onto the inspector."""

    tool_name: str
    tool_id: str
    output: str | None = None


@dataclass(slots=True)
class InspectorSnapshot:
    """Snapshot of the bits of app state the inspector renders.

    Mirror Rust ``App`` fields used by ``build_context_inspector_text``.
    """

    model: str
    workspace: Path
    session_id: str | None = None
    history_cells: int = 0
    api_messages: list[Message] = field(default_factory=list)
    system_prompt: str | None = None
    system_prompt_blocks: list[str] | None = None
    workspace_context: str | None = None
    references: list[ContextReferenceView] = field(default_factory=list)
    active_tool_details: list[ToolDetailView] = field(default_factory=list)
    cell_tool_details: list[tuple[int, ToolDetailView]] = field(default_factory=list)


def build_context_inspector_text(snapshot: InspectorSnapshot) -> str:
    """Build the inspector text.

    Mirror Rust ``build_context_inspector_text`` (context_inspector.rs:24).
    """
    used, max_window, percent = _context_usage(snapshot)
    status = _context_status(percent)

    lines: list[str] = [
        "Session Context",
        "---------------",
        f"Model: {snapshot.model}",
        f"Workspace: {snapshot.workspace}",
    ]
    if snapshot.session_id:
        lines.append(f"Session: {snapshot.session_id}")
    lines.append(
        f"Context: {status} - ~{used}/{max_window} tokens ({percent:.1f}%)"
    )
    lines.append(
        f"Transcript: {snapshot.history_cells} cells, "
        f"{len(snapshot.api_messages)} API messages"
    )
    workspace_status = snapshot.workspace_context or "not sampled yet"
    lines.append(f"Workspace status: {workspace_status}")

    lines.append("")
    lines.extend(_system_prompt_structure(snapshot))
    lines.append("")
    lines.extend(_render_references(snapshot.references))
    lines.append("")
    lines.extend(_render_tools(snapshot))

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _context_usage(snapshot: InspectorSnapshot) -> tuple[int, int, float]:
    max_window = context_window_for_model(snapshot.model)
    estimated = estimate_input_tokens_conservative(
        snapshot.api_messages, snapshot.system_prompt
    )
    chars = sum(
        len(getattr(block, "text", "") or "")
        for msg in snapshot.api_messages
        for block in msg.content
    )
    used = max(estimated, chars // 4)
    percent = min(100.0, max(0.0, (used / max_window) * 100.0)) if max_window else 0.0
    return used, max_window, percent


def _context_status(percent: float) -> str:
    """Mirror Rust ``context_status`` (context_inspector.rs:80)."""
    if percent >= CONTEXT_CRITICAL_THRESHOLD_PERCENT:
        return "critical"
    if percent >= CONTEXT_WARNING_THRESHOLD_PERCENT:
        return "high"
    return "ok"


def _text_tokens(text: str) -> int:
    return -(-len(text) // 3)  # ceil(len / 3)


def _system_prompt_structure(snapshot: InspectorSnapshot) -> list[str]:
    """Mirror Rust ``push_system_prompt_structure`` (context_inspector.rs:92)."""
    out: list[str] = ["System Prompt Structure", "-----------------------"]

    blocks = snapshot.system_prompt_blocks
    text = snapshot.system_prompt

    if blocks:
        total_tokens = sum(_text_tokens(b) for b in blocks)
        working_idx = next(
            (i for i, b in enumerate(blocks) if WORKING_SET_MARKER in b),
            None,
        )
        stable_count = working_idx if working_idx is not None else len(blocks)
        stable_tokens = sum(_text_tokens(b) for b in blocks[:stable_count])
        out.append(
            f"  Stable prefix: {stable_count} block(s), ~{stable_tokens} tokens "
            "[cache-friendly]"
        )
        if working_idx is not None:
            block = blocks[working_idx]
            working_tokens = _text_tokens(block)
            out.append(
                f"  Volatile working set: 1 block, ~{working_tokens} tokens "
                "[changes every turn]"
            )
            first = block.splitlines()[0] if block.splitlines() else "(empty)"
            out.append(f"    First line: {first}")
        else:
            out.append("  Volatile working set: none")
        out.append(f"  Total: {len(blocks)} block(s), ~{total_tokens} tokens")
    elif text:
        total_tokens = _text_tokens(text)
        if WORKING_SET_MARKER in text:
            out.append(
                f"  Single text blob (~{total_tokens} tokens) "
                "[contains working-set marker — structure unclear]"
            )
        else:
            out.append(
                f"  Single text blob (~{total_tokens} tokens) "
                "[stable prefix only]"
            )
    else:
        out.append("  No system prompt set.")

    out.append(
        "  Tip: Stable prefix blocks are DeepSeek V4 prefix-cache eligible. "
        "Volatile working-set changes break the cache only for the tail."
    )
    return out


def _render_references(references: list[ContextReferenceView]) -> list[str]:
    """Mirror Rust ``push_references`` (context_inspector.rs:175)."""
    out: list[str] = ["References", "----------"]
    seen: set[str] = set()
    rendered = 0
    total = len(references)
    for ref in references:
        key = f"{ref.source}:{ref.label}:{ref.target}"
        if key in seen:
            continue
        seen.add(key)
        if rendered >= MAX_REFERENCE_ROWS:
            remaining = total - rendered
            if remaining > 0:
                out.append(f"- ... {remaining} more reference(s)")
            break
        prefix = "@" if ref.source == "at_mention" else "/attach "
        if ref.included:
            state = "included" if ref.expanded else "attached"
        else:
            state = "not included"
        detail = ref.detail.strip() if ref.detail else ""
        suffix = f" - {detail}" if detail else ""
        out.append(
            f"- [{ref.badge}] {prefix}{ref.label} -> {ref.target} ({state}{suffix})"
        )
        rendered += 1
    if rendered == 0:
        out.append("- No file, directory, or media references recorded yet.")
    return out


def _render_tools(snapshot: InspectorSnapshot) -> list[str]:
    """Mirror Rust ``push_tools`` (context_inspector.rs:233)."""
    out: list[str] = ["Recent Tools", "------------"]
    rendered = 0
    for detail in snapshot.active_tool_details:
        out.append(_tool_row("active", detail))
        rendered += 1
        if rendered >= MAX_TOOL_ROWS:
            return out
    rows = sorted(snapshot.cell_tool_details, key=lambda x: x[0], reverse=True)
    for cell_idx, detail in rows[: MAX_TOOL_ROWS - rendered]:
        out.append(_tool_row(f"cell {cell_idx}", detail))
        rendered += 1
    if rendered == 0:
        out.append("- No tool activity recorded yet.")
    else:
        out.append("- Open the matching card and press Alt+V for full details.")
    return out


def _tool_row(location: str, detail: ToolDetailView) -> str:
    output_state = "output captured" if detail.output else "no output yet"
    short = detail.tool_id if len(detail.tool_id) <= 8 else detail.tool_id[:8] + "..."
    return f"- [{location}] {detail.tool_name} {short} ({output_state})"
