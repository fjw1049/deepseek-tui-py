"""Slash command handler implementations.

Each handler has signature: ``(args: str, app: DeepSeekTUI) -> CommandResult``.
Mirrors individual ``commands/*.rs`` files in Rust.
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from deepseek_tui.tui.commands import (
    REGISTRY,
    CommandResult,
)
from deepseek_tui.tui.widgets.status_bar import StatusBar
from deepseek_tui.tui.widgets.transcript import Transcript

if TYPE_CHECKING:
    from deepseek_tui.tui.app import DeepSeekTUI

Handler = Callable[[str, "DeepSeekTUI"], CommandResult]

_HANDLERS: dict[str, Handler] = {}


def _register(name: str) -> Callable[[Handler], Handler]:
    def decorator(fn: Handler) -> Handler:
        _HANDLERS[name] = fn
        return fn
    return decorator


def get_handler(name: str) -> Handler | None:
    return _HANDLERS.get(name)


# ── /help ────────────────────────────────────────────────────────────────

@_register("/help")
def cmd_help(args: str, app: DeepSeekTUI) -> CommandResult:
    lines = ["Available commands:\n"]
    for entry in REGISTRY:
        aliases = ", ".join(entry.aliases) if entry.aliases else ""
        alias_str = f" ({aliases})" if aliases else ""
        p1_mark = " [P1]" if not entry.p0 else ""
        lines.append(f"  {entry.name:<14}{entry.description}{alias_str}{p1_mark}")
    return CommandResult(output="\n".join(lines))


# ── /clear ───────────────────────────────────────────────────────────────

@_register("/clear")
def cmd_clear(args: str, app: DeepSeekTUI) -> CommandResult:
    return CommandResult(output="Conversation cleared.")


# ── /exit ────────────────────────────────────────────────────────────────

@_register("/exit")
def cmd_exit(args: str, app: DeepSeekTUI) -> CommandResult:
    return CommandResult(output="Exiting...", exit_app=True)


# ── /model ───────────────────────────────────────────────────────────────

@_register("/model")
def cmd_model(args: str, app: DeepSeekTUI) -> CommandResult:
    from deepseek_tui.config.provider_registry import PROVIDER_DEFAULTS

    if not args.strip():
        cfg = getattr(app, "config", None)
        if cfg is not None:
            return CommandResult(output=f"Current model: {cfg.model or cfg.default_text_model}")
        return CommandResult(output="Current model: (unknown — config not attached)")

    requested = args.strip()
    for prov_name, defaults in PROVIDER_DEFAULTS.items():
        known = {defaults.model}
        if defaults.flash_model:
            known.add(defaults.flash_model)
        if requested in known:
            return CommandResult(output=f"Model set to: {requested} ({prov_name})")

    return CommandResult(output=f"Model set to: {requested} (unverified — not in registry)")


# ── /mode ────────────────────────────────────────────────────────────────

_VALID_MODES: tuple[str, ...] = ("agent", "plan", "yolo", "ask")


@_register("/mode")
def cmd_mode(args: str, app: DeepSeekTUI) -> CommandResult:
    """Switch or cycle the active mode.

    Usage:
        /mode               — cycle through agent → plan → yolo → ask → agent
        /mode plan          — switch directly to ``plan``
        /mode agent|yolo|ask
    """
    arg = args.strip().lower()
    if not arg:
        # No argument → behave like the Shift+Tab chord.
        cycle = getattr(app, "action_cycle_mode", None)
        if callable(cycle):
            cycle()
            current = getattr(app, "_interaction_mode", "agent")
            return CommandResult(output=f"Mode → {current}")
        return CommandResult(error="cycle_mode action unavailable")

    if arg not in _VALID_MODES:
        return CommandResult(
            error=(
                f"Unknown mode: {arg!r}. Valid: " + ", ".join(_VALID_MODES)
            )
        )
    # Direct switch — drive the same code path action_cycle_mode uses
    # so the StatusBar / ComposerHint refresh consistently.
    app._interaction_mode = arg  # type: ignore[attr-defined]
    try:
        from deepseek_tui.tui.widgets.composer import ComposerHint
        from deepseek_tui.tui.widgets.status_bar import StatusBar

        app.query_one(StatusBar).set_mode(arg)
        app.query_one(ComposerHint).set_mode(arg)
    except Exception:  # noqa: BLE001 — best-effort UI refresh
        pass
    return CommandResult(output=f"Mode → {arg}")


# ── /provider ────────────────────────────────────────────────────────────

@_register("/provider")
def cmd_provider(args: str, app: DeepSeekTUI) -> CommandResult:
    from deepseek_tui.config.provider_registry import PROVIDER_DEFAULTS

    if not args.strip():
        cfg = getattr(app, "config", None)
        current = cfg.provider if cfg else "unknown"
        return CommandResult(output=f"Current provider: {current}")

    requested = args.strip().lower()
    if requested in PROVIDER_DEFAULTS:
        return CommandResult(output=f"Provider switched to: {requested}")
    available = ", ".join(PROVIDER_DEFAULTS.keys())
    return CommandResult(error=f"Unknown provider: {requested}. Available: {available}")


# ── /save ────────────────────────────────────────────────────────────────

@_register("/save")
def cmd_save(args: str, app: DeepSeekTUI) -> CommandResult:
    """Save current session to JSON file."""
    if app._engine is None:
        return CommandResult(error="Engine not started — cannot save session")

    # Determine save path
    if args.strip():
        save_path = Path(args.strip()).expanduser()
    else:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        save_path = Path.cwd() / f"session_{timestamp}.json"

    # Build session snapshot
    messages = [msg.model_dump() for msg in app._engine.session_messages]
    model = app._engine.default_model
    workspace = str(app._engine.tool_context.working_directory)

    # Calculate total tokens from status bar (cumulative display)
    status = app.query_one(StatusBar)
    total_tokens = status._tokens

    session_data = {
        "metadata": {
            "id": f"session-{int(time.time())}",
            "model": model,
            "workspace": workspace,
            "total_tokens": total_tokens,
            "message_count": len(messages),
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
        "messages": messages,
    }

    try:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        json_content = json.dumps(session_data, indent=2, ensure_ascii=False)
        save_path.write_text(json_content, encoding="utf-8")
        session_id = session_data["metadata"]["id"][:8]
        return CommandResult(output=f"Session saved to {save_path} (ID: {session_id})")
    except OSError as exc:
        return CommandResult(error=f"Failed to save session: {exc}")


# ── /sessions ────────────────────────────────────────────────────────────

@_register("/sessions")
def cmd_sessions(args: str, app: DeepSeekTUI) -> CommandResult:
    return CommandResult(output="Session picker — requires StateStore integration (Stage 6)")


# ── /load ────────────────────────────────────────────────────────────────

@_register("/load")
def cmd_load(args: str, app: DeepSeekTUI) -> CommandResult:
    """Load session from JSON file."""
    if app._engine is None:
        return CommandResult(error="Engine not started — cannot load session")

    if not args.strip():
        return CommandResult(error="Usage: /load <path>")

    load_path = Path(args.strip()).expanduser()
    if not load_path.exists():
        return CommandResult(error=f"File not found: {load_path}")

    try:
        content = load_path.read_text(encoding="utf-8")
        session_data = json.loads(content)
    except OSError as exc:
        return CommandResult(error=f"Failed to read session file: {exc}")
    except json.JSONDecodeError as exc:
        return CommandResult(error=f"Failed to parse session file: {exc}")

    # Validate structure
    if "messages" not in session_data or "metadata" not in session_data:
        return CommandResult(error="Invalid session file format")

    # Restore messages to engine
    from deepseek_tui.protocol.messages import Message
    try:
        restored_messages = [Message.model_validate(msg) for msg in session_data["messages"]]
        app._engine.session_messages.clear()
        app._engine.session_messages.extend(restored_messages)
    except Exception as exc:
        return CommandResult(error=f"Failed to restore messages: {exc}")

    # Update UI
    transcript = app.query_one(Transcript)
    transcript.clear_messages()

    # Rebuild transcript from messages
    for msg in restored_messages:
        if msg.role == "user":
            # Extract text content
            text_parts = [block.text for block in msg.content if hasattr(block, "text")]
            if text_parts:
                transcript.add_user_message(" ".join(text_parts))
        elif msg.role == "assistant":
            text_parts = [
                block.text
                for block in msg.content
                if hasattr(block, "text") and block.type == "text"
            ]
            if text_parts:
                transcript.add_assistant_message(" ".join(text_parts))

    metadata = session_data["metadata"]
    session_id = metadata.get("id", "unknown")[:8]
    message_count = metadata.get("message_count", len(restored_messages))

    return CommandResult(
        output=f"Session loaded from {load_path} (ID: {session_id}, {message_count} messages)"
    )


# ── /context ─────────────────────────────────────────────────────────────

@_register("/context")
def cmd_context(args: str, app: DeepSeekTUI) -> CommandResult:
    """Render a Cursor-style context budget breakdown.

    Reads ``Engine.context_breakdown()`` for live per-bucket token
    counts (system prompt + tools schema + conversation history),
    formats a fixed-width table with a percent bar. Falls back to the
    minimal model + workspace dump from the legacy InspectorSnapshot
    when no engine has been wired (e.g. before first turn).
    """
    from pathlib import Path

    engine = getattr(app, "_engine", None)
    config = getattr(app, "config", None)
    model = getattr(config, "model", None) or "unknown"
    workspace = Path(
        getattr(config, "workspace", None) or "."
    ).expanduser()

    if engine is None:
        from deepseek_tui.tui.widgets.context_inspector import (
            InspectorSnapshot,
            build_context_inspector_text,
        )

        snapshot = InspectorSnapshot(
            model=model,
            workspace=workspace,
            history_cells=0,
        )
        return CommandResult(output=build_context_inspector_text(snapshot))

    breakdown = engine.context_breakdown(model)
    return CommandResult(output=_format_context_breakdown(breakdown, model))


def _format_context_breakdown(b: dict[str, int], model: str) -> str:
    """Render the breakdown dict as a fixed-width text block.

    Layout::

        Context: 33.4K / 200K (17%)
        ├─ System prompt   603  (1.8%)
        ├─ Tools          7.8K  (23.4%)
        ├─ Conversation   10.7K (32.0%)
        └─ Free space    180.9K (90.5%)
    """
    total = int(b.get("total", 0))
    window = int(b.get("window", 0))

    def fmt_tokens(n: int) -> str:
        if n >= 10_000:
            return f"{n / 1000:.1f}K"
        if n >= 1_000:
            return f"{n / 1000:.1f}K"
        return str(n)

    def pct(n: int) -> str:
        if window <= 0:
            return "  -  "
        return f"{100.0 * n / window:5.1f}%"

    lines = []
    if window > 0:
        used_pct = 100.0 * total / window
        lines.append(
            f"Context: {fmt_tokens(total)} / {fmt_tokens(window)} ({used_pct:.0f}%)"
        )
    else:
        lines.append(f"Context: {fmt_tokens(total)} (window unknown)")

    rows: list[tuple[str, str, int]] = [
        ("System prompt", "├─", int(b.get("system_prompt", 0))),
        ("Tools",         "├─", int(b.get("tools", 0))),
        ("Conversation",  "├─", int(b.get("conversation", 0))),
        ("Free space",    "└─", int(b.get("free", 0))),
    ]
    label_w = max(len(label) for _, label, _ in rows)
    for label, branch, n in rows:
        lines.append(
            f"  {branch} {label:<{label_w}}  {fmt_tokens(n):>6}  ({pct(n)})"
        )
    lines.append("")
    lines.append(f"Model: {model}")
    return "\n".join(lines)


# ── /export ──────────────────────────────────────────────────────────────

@_register("/export")
def cmd_export(args: str, app: DeepSeekTUI) -> CommandResult:
    filename = args.strip() or f"deepseek-export-{int(time.time())}.md"
    path = Path(filename)
    if path.exists():
        return CommandResult(error=f"File already exists: {path}")
    path.write_text(
        f"# DeepSeek TUI Export\n\n"
        f"Exported at {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"(Conversation history will be included once Engine is wired.)\n",
        encoding="utf-8",
    )
    return CommandResult(output=f"Exported to {path}")


# ── /config ──────────────────────────────────────────────────────────────

@_register("/config")
def cmd_config(args: str, app: DeepSeekTUI) -> CommandResult:
    sub = args.strip().split(maxsplit=1)
    action = sub[0] if sub else "show"

    if action == "set":
        if len(sub) < 2 or "=" not in sub[1]:
            return CommandResult(error="Usage: /config set key=value")
        key, _, value = sub[1].partition("=")
        return _config_write(key.strip(), value.strip())

    if action == "unset":
        if len(sub) < 2:
            return CommandResult(error="Usage: /config unset key")
        return _config_write(sub[1].strip(), None)

    return CommandResult(output="Opening config editor...")


def _config_write(key: str, value: str | None) -> CommandResult:
    """Set or unset a key in ~/.deepseek/config.toml."""
    from deepseek_tui.config.paths import user_config_path

    config_path = user_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    if config_path.exists():
        lines = config_path.read_text(encoding="utf-8").splitlines()

    found = False
    new_lines: list[str] = []
    for line in lines:
        stripped = line.split("#", 1)[0].strip()
        if stripped.startswith(f"{key} ") or stripped.startswith(f"{key}="):
            found = True
            if value is not None:
                new_lines.append(f"{key} = {_toml_value(value)}")
        else:
            new_lines.append(line)

    if not found and value is not None:
        new_lines.append(f"{key} = {_toml_value(value)}")

    config_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    if value is None:
        return CommandResult(output=f"Unset {key}" if found else f"Key {key} not found")
    return CommandResult(output=f"Set {key} = {_toml_value(value)}")


def _toml_value(raw: str) -> str:
    """Wrap as TOML string unless it looks like a bool/int/float."""
    if raw.lower() in ("true", "false"):
        return raw.lower()
    try:
        int(raw)
        return raw
    except ValueError:
        pass
    try:
        float(raw)
        return raw
    except ValueError:
        pass
    return f'"{raw}"'


# ── /agent ───────────────────────────────────────────────────────────────

@_register("/agent")
def cmd_agent(args: str, app: DeepSeekTUI) -> CommandResult:
    """Switch to Agent mode (shortcut for ``/mode agent``)."""
    return cmd_mode("agent", app)


# ── /plan ────────────────────────────────────────────────────────────────

@_register("/plan")
def cmd_plan(args: str, app: DeepSeekTUI) -> CommandResult:
    """Switch to Plan mode and pop the plan-confirmation prompt.

    Mirror Rust slash ``/plan`` + ``PlanPromptView``. The prompt opens
    via :class:`PlanPromptScreen` (push_screen with a callback). Outside
    of a running Textual app (e.g. unit tests), the call short-circuits
    to a textual hint so the dispatch layer is still testable.
    """
    from deepseek_tui.tui.plan_prompt import PlanOutcome, PlanPromptScreen
    from deepseek_tui.tui.widgets.status_bar import StatusBar

    if not getattr(app, "is_running", False):
        return CommandResult(output="Switched to Plan mode.")

    def _on_plan_outcome(outcome: PlanOutcome | None) -> None:
        if outcome is None or outcome == PlanOutcome.DISMISSED:
            return
        status = app.query_one(StatusBar)
        status.set_mode(outcome.value)

    app.push_screen(PlanPromptScreen(), _on_plan_outcome)
    return CommandResult(output="Switched to Plan mode.")


# ── /yolo ────────────────────────────────────────────────────────────────

@_register("/yolo")
def cmd_yolo(args: str, app: DeepSeekTUI) -> CommandResult:
    if app._engine is None:
        return CommandResult(error="Engine not started")
    from deepseek_tui.engine.handle import AutoApprovalHandler
    app._engine.approval_handler = AutoApprovalHandler()
    return CommandResult(output="YOLO mode enabled — all tool approvals auto-accepted.")


# ── /logout ──────────────────────────────────────────────────────────────

@_register("/logout")
def cmd_logout(args: str, app: DeepSeekTUI) -> CommandResult:
    from deepseek_tui.secrets.facade import Secrets
    secrets = Secrets.auto_detect()
    for prov in ["deepseek", "nvidia-nim", "openrouter", "novita", "openai"]:
        secrets.delete(prov)
    return CommandResult(output="Logged out. API keys cleared.")


# ── /tokens ──────────────────────────────────────────────────────────────

@_register("/tokens")
def cmd_tokens(args: str, app: DeepSeekTUI) -> CommandResult:
    """Show token usage statistics for the current session."""
    if app._engine is None:
        return CommandResult(error="Engine not started — no token data available")

    # Get current session state
    message_count = len(app._engine.session_messages)
    model = app._engine.default_model

    # Get cumulative tokens from status bar (tracks total across all turns)
    status = app.query_one(StatusBar)
    total_tokens = status._tokens

    # Build report
    lines = [
        "Token Usage Report",
        "=" * 50,
        f"Model:              {model}",
        f"API messages:       {message_count}",
        f"Cumulative tokens:  {total_tokens:,}",
        "",
        "Note: Token counts are cumulative across all turns in this session.",
        "Use /cost to see estimated cost breakdown.",
    ]

    return CommandResult(output="\n".join(lines))


# ── /system ──────────────────────────────────────────────────────────────

@_register("/system")
def cmd_system(args: str, app: DeepSeekTUI) -> CommandResult:
    from deepseek_tui.prompts import AppMode, compose_prompt
    prompt = compose_prompt(AppMode.AGENT)
    if len(prompt) > 2000:
        prompt = prompt[:2000] + "\n... (truncated)"
    return CommandResult(output=f"System prompt:\n{prompt}")


# ── /retry ───────────────────────────────────────────────────────────────

@_register("/retry")
def cmd_retry(args: str, app: DeepSeekTUI) -> CommandResult:
    return CommandResult(output="Retry last request — requires Engine integration (Stage 6)")


# ── /init ────────────────────────────────────────────────────────────────

@_register("/init")
def cmd_init(args: str, app: DeepSeekTUI) -> CommandResult:
    target = Path.cwd() / "AGENTS.md"
    if target.exists():
        return CommandResult(error=f"AGENTS.md already exists at {target}")
    target.write_text(
        "# AGENTS.md\n\n"
        "Project instructions for AI assistants.\n\n"
        "## Project Type\n\n"
        "<!-- Add your project type and build commands here -->\n",
        encoding="utf-8",
    )
    return CommandResult(output=f"Created {target}")


# ── /settings ────────────────────────────────────────────────────────────

@_register("/settings")
def cmd_settings(args: str, app: DeepSeekTUI) -> CommandResult:
    from deepseek_tui.config.loader import ConfigLoader
    try:
        config = ConfigLoader().load()
        data = config.model_dump(exclude_none=True)
        return CommandResult(output=json.dumps(data, indent=2, default=str))
    except Exception as exc:
        return CommandResult(error=f"Failed to load settings: {exc}")


# ── /cost ────────────────────────────────────────────────────────────────

@_register("/cost")
def cmd_cost(args: str, app: DeepSeekTUI) -> CommandResult:
    """Show estimated cost breakdown for the current session."""
    if app._engine is None:
        return CommandResult(error="Engine not started — no cost data available")

    # Get cumulative tokens from status bar
    status = app.query_one(StatusBar)
    total_tokens = status._tokens
    model = app._engine.default_model

    # DeepSeek pricing (as of 2024):
    # deepseek-chat: $0.14 per 1M input tokens, $0.28 per 1M output tokens
    # For simplicity, use average rate of $0.21 per 1M tokens
    # (This is a rough estimate; actual cost depends on input/output ratio)

    cost_per_million = 0.21  # USD per 1M tokens (average)
    estimated_cost = (total_tokens / 1_000_000) * cost_per_million

    lines = [
        "Session Cost Breakdown",
        "=" * 50,
        f"Model:              {model}",
        f"Total tokens:       {total_tokens:,}",
        f"Estimated cost:     ${estimated_cost:.4f} USD",
        "",
        "Note: This is an approximate estimate based on average pricing.",
        "Actual costs may vary based on input/output token ratio and",
        "cache hit rates. Check your DeepSeek dashboard for exact billing.",
    ]

    return CommandResult(output="\n".join(lines))


# ── /hooks ───────────────────────────────────────────────────────────────

@_register("/hooks")
def cmd_hooks(args: str, app: DeepSeekTUI) -> CommandResult:
    sub = (args.strip() or "list").lower()
    if sub in ("events", "event", "list-events"):
        lines = [
            "Available hook events (use one of these as `event = \"...\"` in your `[[hooks.hooks]]` entry):",
            "",
            "  session_start — fires once when the TUI launches",
            "  session_end — fires once on graceful shutdown",
            "  message_submit — fires when the user submits a turn (before model dispatch)",
            "  tool_call_before — fires before each tool call",
            "  tool_call_after — fires after each tool call",
            "  mode_change — fires on Plan/Agent/Yolo transitions",
            "  on_error — fires on transport / capacity / tool errors",
            "  shell_env — fires before exec_shell for env injection",
        ]
        return CommandResult(output="\n".join(lines))

    if sub not in ("", "list", "ls", "show"):
        return CommandResult(
            error=f"unknown subcommand `{sub}`. Try `/hooks list` or `/hooks events`."
        )

    executor = None
    if app._engine is not None:
        executor = getattr(app._engine, "hook_executor", None)
    if executor is None or not executor.config.hooks:
        return CommandResult(
            output=(
                "No hooks configured. Add a `[[hooks.hooks]]` entry to "
                "`~/.deepseek/config.toml` to define one."
            )
        )
    cfg = executor.config_snapshot()
    lines = [
        f"{len(cfg.hooks)} configured hook(s) (global enabled: "
        f"{'yes' if cfg.enabled else 'no — all hooks suppressed'}):",
        "",
    ]
    by_event: dict[str, list] = {}
    for hook in cfg.hooks:
        by_event.setdefault(hook.event, []).append(hook)
    for event in sorted(by_event):
        lines.append(f"### {event}")
        for hook in by_event[event]:
            label = hook.name.strip() if hook.name and hook.name.strip() else "(unnamed)"
            bg = " [bg]" if hook.background else ""
            condition = ""
            if hook.condition:
                condition = f" if {hook.condition}"
            cmd_preview = hook.command if len(hook.command) <= 60 else hook.command[:57] + "..."
            lines.append(
                f"  - {label}{bg} (timeout {hook.timeout_secs}s){condition}\n"
                f"      $ {cmd_preview}"
            )
        lines.append("")
    if not cfg.enabled:
        lines.append(
            "Hooks are globally disabled — set `[hooks].enabled = true` in config.toml to fire them."
        )
    return CommandResult(output="\n".join(lines).rstrip())


# ── /subagents ───────────────────────────────────────────────────────────

@_register("/subagents")
def cmd_subagents(args: str, app: DeepSeekTUI) -> CommandResult:
    if app._engine is None:
        return CommandResult(error="Engine not started")
    mgr = app._engine.tool_context.subagent_manager
    if mgr is None:
        return CommandResult(output="Sub-agent feature not enabled.")
    running = mgr.running_count()
    agents = mgr.list_filtered(include_archived=False)
    if not agents:
        return CommandResult(output="No active sub-agents.")
    lines = [f"Sub-agents ({running} running, {len(agents)} total):\n"]
    for a in agents:
        status = a.status.kind.value if a.status else "unknown"
        label = a.nickname or a.agent_type or a.agent_id[:8]
        lines.append(f"  {label:<20} [{status}]")
    return CommandResult(output="\n".join(lines))


# ── /task ────────────────────────────────────────────────────────────────

@_register("/task")
def cmd_task(args: str, app: DeepSeekTUI) -> CommandResult:
    if app._engine is None:
        return CommandResult(error="Engine not started")
    mgr = app._engine.tool_context.task_manager
    if mgr is None:
        return CommandResult(output="Task feature not enabled.")
    # Read task counts directly (safe for display without async lock)
    from deepseek_tui.tools.task_manager import TaskStatus
    tasks = mgr._tasks
    queued = sum(1 for t in tasks.values() if t.status is TaskStatus.QUEUED)
    running = sum(1 for t in tasks.values() if t.status is TaskStatus.RUNNING)
    completed = sum(
        1 for t in tasks.values()
        if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)
    )
    total = len(tasks)
    if total == 0:
        return CommandResult(output="No background tasks.")
    lines = [
        f"Background tasks: {total} total",
        f"  Queued:    {queued}",
        f"  Running:   {running}",
        f"  Done:      {completed}",
    ]
    return CommandResult(output="\n".join(lines))


# ── /jobs ────────────────────────────────────────────────────────────────

@_register("/jobs")
def cmd_jobs(args: str, app: DeepSeekTUI) -> CommandResult:
    if app._engine is None:
        return CommandResult(error="Engine not started")
    # Shell processes are stored in ToolContext.metadata
    processes = app._engine.tool_context.metadata.get("shell_processes", {})
    if not processes:
        return CommandResult(output="No active shell jobs.")
    lines = [f"Active shell jobs: {len(processes)}\n"]
    for pid_key, proc in processes.items():
        pid = getattr(proc, "pid", "?")
        status = "running" if proc.returncode is None else f"exited({proc.returncode})"
        lines.append(f"  {pid_key[:8]}  pid={pid}  [{status}]")
    return CommandResult(output="\n".join(lines))


# ── /mcp ─────────────────────────────────────────────────────────────────

def _mcp_restart_required(app: DeepSeekTUI) -> bool:
    return bool(getattr(app, "_mcp_restart_required", False))


def _set_mcp_restart_required(app: DeepSeekTUI, value: bool) -> None:
    app._mcp_restart_required = value


async def _mcp_discover_worker(app: DeepSeekTUI, path, *, reload_engine: bool) -> None:  # type: ignore[no-untyped-def]
    from deepseek_tui.mcp.store import discover_manager_snapshot, format_manager_snapshot

    transcript = app.query_one(Transcript)
    try:
        if reload_engine and app._engine is not None:
            mgr = app._engine.mcp_manager
            if mgr is not None:
                await mgr.reconnect_all()
            app._engine.invalidate_mcp_tools_cache()
            try:
                await app._engine._get_tools_with_mcp()
            except Exception:  # noqa: BLE001
                pass
        snapshot = await discover_manager_snapshot(
            path, restart_required=_mcp_restart_required(app)
        )
        extra = (
            "\n\nMCP discovery refreshed. Model-visible MCP tools updated for this session."
        )
        transcript.add_notice(format_manager_snapshot(snapshot) + extra, severity="info")
    except Exception as exc:  # noqa: BLE001
        transcript.add_notice(f"MCP snapshot failed: {exc}", severity="error")


@_register("/mcp")
def cmd_mcp(args: str, app: DeepSeekTUI) -> CommandResult:
    from deepseek_tui.mcp.store import (
        McpWriteStatus,
        add_server_config,
        format_manager_snapshot,
        init_config,
        manager_snapshot_from_config,
        remove_server_config,
        resolve_mcp_config_path,
        set_server_enabled,
    )

    path = resolve_mcp_config_path(app.config)
    raw = (args or "").strip()
    if not raw or raw.lower() in {"status", "list", "show"}:
        snapshot = manager_snapshot_from_config(
            path, restart_required=_mcp_restart_required(app)
        )
        return CommandResult(output=format_manager_snapshot(snapshot))

    parts = raw.split()
    action = parts[0].lower()
    rest = parts[1:]

    try:
        if action == "init":
            force = any(part in {"--force", "-f"} for part in rest)
            status = init_config(path, force=force)
            if status == McpWriteStatus.CREATED:
                msg = f"Created MCP config at {path}"
            elif status == McpWriteStatus.OVERWRITTEN:
                msg = f"Overwrote MCP config at {path}"
            else:
                msg = f"MCP config already exists at {path} (use /mcp init --force to overwrite)"
            snapshot = manager_snapshot_from_config(path, restart_required=False)
            return CommandResult(output=f"{msg}\n\n{format_manager_snapshot(snapshot)}")

        if action == "add":
            if len(rest) < 3:
                return CommandResult(
                    error=(
                        "Usage: /mcp add stdio <name> <command> [args...] "
                        "OR /mcp add http <name> <url>"
                    )
                )
            transport = rest[0].lower()
            if transport == "stdio":
                name, command, *cmd_args = rest[1], rest[2], rest[3:]
                add_server_config(path, name, command=command, args=cmd_args)
                _set_mcp_restart_required(app, True)
                msg = f"Added MCP stdio server '{name}'"
            elif transport in {"http", "sse"}:
                name, url = rest[1], rest[2]
                add_server_config(path, name, url=url)
                _set_mcp_restart_required(app, True)
                msg = f"Added MCP HTTP/SSE server '{name}'"
            else:
                return CommandResult(
                    error=(
                        "Usage: /mcp add stdio <name> <command> [args...] "
                        "OR /mcp add http <name> <url>"
                    )
                )
            snapshot = manager_snapshot_from_config(
                path, restart_required=_mcp_restart_required(app)
            )
            return CommandResult(output=f"{msg}\n\n{format_manager_snapshot(snapshot)}")

        if action == "enable":
            if not rest:
                return CommandResult(error="Usage: /mcp enable <name>")
            set_server_enabled(path, rest[0], True)
            _set_mcp_restart_required(app, True)
            msg = f"Enabled MCP server '{rest[0]}'"
        elif action == "disable":
            if not rest:
                return CommandResult(error="Usage: /mcp disable <name>")
            set_server_enabled(path, rest[0], False)
            _set_mcp_restart_required(app, True)
            msg = f"Disabled MCP server '{rest[0]}'"
        elif action in {"remove", "rm"}:
            if not rest:
                return CommandResult(error="Usage: /mcp remove <name>")
            remove_server_config(path, rest[0])
            _set_mcp_restart_required(app, True)
            msg = f"Removed MCP server '{rest[0]}'"
        elif action in {"validate", "reload", "reconnect"}:
            app.run_worker(
                _mcp_discover_worker(app, path, reload_engine=action in {"reload", "reconnect"}),
                name="mcp-discover",
            )
            return CommandResult(output="Refreshing MCP discovery...")
        else:
            return CommandResult(
                error=(
                    "Usage: /mcp [init|add stdio <name> <command> [args...]|"
                    "add http <name> <url>|enable <name>|disable <name>|"
                    "remove <name>|validate|reload]"
                )
            )
    except (KeyError, ValueError, OSError, json.JSONDecodeError) as exc:
        return CommandResult(error=f"MCP action failed: {exc}")

    snapshot = manager_snapshot_from_config(
        path, restart_required=_mcp_restart_required(app)
    )
    return CommandResult(output=f"{msg}\n\n{format_manager_snapshot(snapshot)}")


# ── /compact ─────────────────────────────────────────────────────────────

@_register("/compact")
def cmd_compact(args: str, app: DeepSeekTUI) -> CommandResult:
    if app._engine is None:
        return CommandResult(error="Engine not started")
    import asyncio

    async def _do_compact() -> str:
        msgs = app._engine.session_messages
        if not msgs:
            return "Nothing to compact — session is empty."
        compacted = await app._engine._emergency_compact(msgs)
        app._engine.session_messages[:] = compacted
        return (
            f"Context compacted: {len(msgs)} → {len(compacted)} messages."
        )

    try:
        asyncio.get_running_loop()
        asyncio.ensure_future(_do_compact())
        return CommandResult(output="Context compaction triggered (async).")
    except RuntimeError:
        return CommandResult(output="Context compaction triggered.")


# ── /diff ────────────────────────────────────────────────────────────────

@_register("/diff")
def cmd_diff(args: str, app: DeepSeekTUI) -> CommandResult:
    import subprocess

    try:
        result = subprocess.run(
            ["git", "diff", "--stat"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return CommandResult(error="Not a git repository or git not available.")
        output = result.stdout.strip()
        if not output:
            return CommandResult(output="No uncommitted changes.")
        return CommandResult(output=f"Changes:\n{output}")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return CommandResult(error="git not available.")


# ── /skills ──────────────────────────────────────────────────────────────

@_register("/skills")
def cmd_skills(args: str, app: DeepSeekTUI) -> CommandResult:
    """List local skills, or fetch the remote registry.

    Usage:
        /skills                       — list installed skills
        /skills <prefix>              — filter installed by name prefix
        /skills --remote | remote     — list curated remote registry
        /skills sync | --sync         — fetch + cache remote registry locally

    Mirrors Rust ``commands/skills.rs::list_skills`` (skills.rs:37-130).
    """
    from deepseek_tui.skills import default_skills_dir
    from deepseek_tui.skills.install import fetch_registry

    skills_dir = default_skills_dir()
    arg = args.strip()

    if arg in ("--remote", "remote"):
        registry = fetch_registry()
        if registry is None:
            return CommandResult(error="Failed to fetch remote skill registry.")
        if not registry.skills:
            return CommandResult(output="Remote registry is empty.")
        lines = ["Remote skills:\n"]
        for name, entry in sorted(registry.skills.items()):
            desc = f" — {entry.description}" if entry.description else ""
            lines.append(f"  {name}{desc}  ({entry.source})")
        return CommandResult(output="\n".join(lines))

    if arg in ("sync", "--sync"):
        registry = fetch_registry()
        if registry is None:
            return CommandResult(error="Failed to fetch remote skill registry.")
        return CommandResult(
            output=(
                f"Fetched registry index ({len(registry.skills)} skills). "
                "Use `/skill install <name>` to install one."
            )
        )

    if arg.startswith("-"):
        return CommandResult(
            error="Usage: /skills [--remote|sync|<name-prefix>]"
        )

    prefix = arg.lower() if arg else None

    if not skills_dir.is_dir():
        return CommandResult(output="No skills installed.")

    skills: list[str] = []
    for d in sorted(skills_dir.iterdir()):
        if not d.is_dir():
            continue
        if not (d / "SKILL.md").exists():
            continue
        if prefix and not d.name.lower().startswith(prefix):
            continue
        skills.append(f"  {d.name}")
    if not skills:
        if prefix:
            return CommandResult(output=f"No skills match prefix `{prefix}`.")
        return CommandResult(output="No skills installed.")
    return CommandResult(output="Installed skills:\n\n" + "\n".join(skills))


# ── /skill ───────────────────────────────────────────────────────────────

@_register("/skill")
def cmd_skill(args: str, app: DeepSeekTUI) -> CommandResult:
    """Skill subcommands: read SKILL.md, install / update / uninstall / trust.

    Usage:
        /skill <name>                — print SKILL.md
        /skill install <spec>        — github:owner/repo or local path
        /skill update <name>         — re-fetch from .installed-from
        /skill uninstall <name>      — delete (community installs only)
        /skill trust <name>          — mark trusted (allowed-tools whitelist)

    Mirrors Rust ``commands/skills.rs::run_skill`` (skills.rs:142-310).
    """
    from deepseek_tui.skills import default_skills_dir
    from deepseek_tui.skills.install import (
        InstallSource,
        install,
        trust,
        uninstall,
        update,
    )

    raw = args.strip()
    if not raw:
        return CommandResult(
            error=(
                "Usage: /skill <name> | install <spec> | update <name> | "
                "uninstall <name> | trust <name>"
            )
        )

    parts = raw.split(None, 1)
    head = parts[0]
    rest = parts[1].strip() if len(parts) > 1 else ""
    skills_dir = default_skills_dir()

    if head == "install":
        if not rest:
            return CommandResult(
                error="Usage: /skill install <github:owner/repo|local-path>"
            )
        source = InstallSource.parse(rest)
        if source.kind == "invalid":
            return CommandResult(error=f"Invalid source: {rest}")
        outcome, message = install(source, skills_dir=skills_dir)
        if outcome.value == "failed":
            return CommandResult(error=message)
        return CommandResult(output=message)

    if head == "update":
        if not rest:
            return CommandResult(error="Usage: /skill update <name>")
        outcome, message = update(rest, skills_dir=skills_dir)
        if outcome.value == "failed":
            return CommandResult(error=message)
        return CommandResult(output=message)

    if head == "uninstall":
        if not rest:
            return CommandResult(error="Usage: /skill uninstall <name>")
        return CommandResult(output=uninstall(rest, skills_dir=skills_dir))

    if head == "trust":
        if not rest:
            return CommandResult(error="Usage: /skill trust <name>")
        return CommandResult(output=trust(rest, skills_dir=skills_dir))

    # Default: treat the whole arg as a skill name to read.
    skill_path = skills_dir / raw / "SKILL.md"
    if not skill_path.exists():
        return CommandResult(error=f"Skill not found: {raw}")
    content = skill_path.read_text(encoding="utf-8")
    if len(content) > 2000:
        content = content[:2000] + "\n... (truncated)"
    return CommandResult(output=content)


# ── /log ──────────────────────────────────────────────────────────────────


@_register("/log")
def cmd_log(args: str, app: DeepSeekTUI) -> CommandResult:
    """Show the active log file path or tail the last N lines.

    Usage:
        /log              → print current log file path
        /log tail         → print last 50 lines
        /log tail 200     → print last 200 lines

    Mirrors the lightweight log-introspection slash command described in
    the 2026-05-10 logging design doc — full Rust binary doesn't have
    this exact command but exposes ``tail -f`` instructions in docs.
    """
    from deepseek_tui.logging_setup import current_log_path, tail_log

    args = args.strip()
    path = current_log_path()
    if not args:
        if path is None:
            return CommandResult(output="logging is disabled (Config.logging.enabled=false)")
        return CommandResult(output=f"log file: {path}\n(use `/log tail` for recent entries)")

    parts = args.split()
    if parts[0] != "tail":
        return CommandResult(
            error=(
                f"unknown subcommand: {parts[0]} — use '/log' or '/log tail [N]'"
            )
        )
    n = 50
    if len(parts) > 1:
        try:
            n = max(1, min(int(parts[1]), 5000))
        except ValueError:
            return CommandResult(error=f"line count must be an integer, got: {parts[1]!r}")
    lines = tail_log(n)
    if not lines:
        if path is None:
            return CommandResult(output="logging is disabled")
        return CommandResult(output=f"(no log entries yet at {path})")
    body = "\n".join(lines)
    return CommandResult(output=f"-- last {len(lines)} lines from {path} --\n{body}")


# ── /undo ───────────────────────────────────────────────────────────────

@_register("/undo")
def cmd_undo(args: str, app: DeepSeekTUI) -> CommandResult:
    """Undo the last file-modifying tool (mirrors Rust /undo)."""
    if app._engine is None:
        return CommandResult(error="Engine not started")
    success, msg = app._engine.undo_last_tool()
    if success:
        return CommandResult(output=msg)
    return CommandResult(error=msg)
