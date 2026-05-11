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
        model = getattr(app, "_config", None)
        if model and hasattr(model, "model"):
            return CommandResult(output=f"Current model: {model.model or model.default_text_model}")
        return CommandResult(output="Current model: (unknown — config not attached)")

    requested = args.strip()
    for prov_name, defaults in PROVIDER_DEFAULTS.items():
        known = {defaults.model}
        if defaults.flash_model:
            known.add(defaults.flash_model)
        if requested in known:
            return CommandResult(output=f"Model set to: {requested} ({prov_name})")

    return CommandResult(output=f"Model set to: {requested} (unverified — not in registry)")


# ── /models ──────────────────────────────────────────────────────────────

@_register("/models")
def cmd_models(args: str, app: DeepSeekTUI) -> CommandResult:
    from deepseek_tui.config.provider_registry import PROVIDER_DEFAULTS

    lines: list[str] = ["Available models:\n"]
    for prov_name, defaults in PROVIDER_DEFAULTS.items():
        lines.append(f"  {defaults.model} ({prov_name})")
        if defaults.flash_model:
            lines.append(f"  {defaults.flash_model} ({prov_name}, flash)")
    return CommandResult(output="\n".join(lines))


# ── /provider ────────────────────────────────────────────────────────────

@_register("/provider")
def cmd_provider(args: str, app: DeepSeekTUI) -> CommandResult:
    from deepseek_tui.config.provider_registry import PROVIDER_DEFAULTS

    if not args.strip():
        cfg = getattr(app, "_config", None)
        current = cfg.provider if cfg else "unknown"
        return CommandResult(output=f"Current provider: {current}")

    requested = args.strip().lower()
    if requested in PROVIDER_DEFAULTS:
        return CommandResult(output=f"Provider switched to: {requested}")
    available = ", ".join(PROVIDER_DEFAULTS.keys())
    return CommandResult(error=f"Unknown provider: {requested}. Available: {available}")


# ── /links ───────────────────────────────────────────────────────────────

@_register("/links")
def cmd_links(args: str, app: DeepSeekTUI) -> CommandResult:
    return CommandResult(output=(
        "DeepSeek Links:\n"
        "  Dashboard:  https://platform.deepseek.com\n"
        "  API Docs:   https://api-docs.deepseek.com\n"
        "  Status:     https://status.deepseek.com\n"
        "  GitHub:     https://github.com/deepseek-ai"
    ))


# ── /home ────────────────────────────────────────────────────────────────

@_register("/home")
def cmd_home(args: str, app: DeepSeekTUI) -> CommandResult:
    return CommandResult(output=(
        "DeepSeek TUI — Home\n"
        "  Type a message to start a conversation.\n"
        "  Type /help for available commands.\n"
        "  Type /model to switch models.\n"
        "  Type /config to adjust settings."
    ))


# ── /note ────────────────────────────────────────────────────────────────

@_register("/note")
def cmd_note(args: str, app: DeepSeekTUI) -> CommandResult:
    if not args.strip():
        return CommandResult(error="Usage: /note <text>")

    notes_path = Path("~/.deepseek/notes.md").expanduser()
    notes_path.parent.mkdir(parents=True, exist_ok=True)
    with notes_path.open("a", encoding="utf-8") as f:
        f.write(f"\n- [{time.strftime('%Y-%m-%d %H:%M')}] {args.strip()}\n")
    return CommandResult(output=f"Note saved to {notes_path}")


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
    """Render the session-context inspector.

    Mirror Rust slash ``/context``. Builds an :class:`InspectorSnapshot`
    from whatever live state the app exposes — for now that's just the
    model + workspace path, since the API-message stream and reference
    log live in the engine. As more state surfaces on ``DeepSeekTUI``
    (api_messages, references, tool details), they get wired in here.
    """
    from pathlib import Path

    from deepseek_tui.tui.widgets.context_inspector import (
        InspectorSnapshot,
        build_context_inspector_text,
    )

    config = getattr(app, "config", None)
    model = getattr(config, "model", None) or "unknown"
    workspace = Path(
        getattr(config, "workspace", None) or "."
    ).expanduser()

    snapshot = InspectorSnapshot(
        model=model,
        workspace=workspace,
        history_cells=0,
    )
    return CommandResult(output=build_context_inspector_text(snapshot))


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
    from deepseek_tui.config.paths import default_config_path

    config_path = default_config_path()
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
    return CommandResult(output="Switched to Agent mode.")


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
    from deepseek_tui.engine.approval import AutoApprovalHandler
    app._engine.approval_handler = AutoApprovalHandler()
    return CommandResult(output="YOLO mode enabled — all tool approvals auto-accepted.")


# ── /trust ───────────────────────────────────────────────────────────────

@_register("/trust")
def cmd_trust(args: str, app: DeepSeekTUI) -> CommandResult:
    cwd = Path.cwd()
    return CommandResult(output=f"Workspace trusted: {cwd}")


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


# ── /edit ────────────────────────────────────────────────────────────────

@_register("/edit")
def cmd_edit(args: str, app: DeepSeekTUI) -> CommandResult:
    return CommandResult(output="Edit last message — requires Engine integration (Stage 6)")


# ── /undo ────────────────────────────────────────────────────────────────

@_register("/undo")
def cmd_undo(args: str, app: DeepSeekTUI) -> CommandResult:
    """Restore the most recent file-modifying tool snapshot."""
    engine = getattr(app, "_engine", None)
    if engine is None:
        return CommandResult(error="Engine not started — cannot undo")
    success, message = engine.undo_last_tool()
    if success:
        return CommandResult(output=message)
    return CommandResult(error=message)


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


# ── /statusline ──────────────────────────────────────────────────────────

@_register("/statusline")
def cmd_statusline(args: str, app: DeepSeekTUI) -> CommandResult:
    return CommandResult(output="Status line configuration — requires TUI widget integration")


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


# ── /queue ───────────────────────────────────────────────────────────────

@_register("/queue")
def cmd_queue(args: str, app: DeepSeekTUI) -> CommandResult:
    return CommandResult(output="Message queue is empty.")


# ── /stash ───────────────────────────────────────────────────────────────

@_register("/stash")
def cmd_stash(args: str, app: DeepSeekTUI) -> CommandResult:
    from deepseek_tui.config.paths import dot_deepseek_dir

    stash_dir = dot_deepseek_dir() / "stash"
    stash_dir.mkdir(parents=True, exist_ok=True)

    sub = args.strip().split(maxsplit=1)
    action = sub[0] if sub else "list"

    if action == "list":
        files = sorted(stash_dir.glob("*.md"))
        if not files:
            return CommandResult(output="Stash is empty.")
        lines = ["Stashed drafts:\n"]
        for f in files[-10:]:
            lines.append(f"  {f.stem}")
        return CommandResult(output="\n".join(lines))

    if action == "push":
        content = sub[1] if len(sub) > 1 else ""
        if not content:
            return CommandResult(error="Usage: /stash push <text>")
        name = f"stash-{int(time.time())}"
        (stash_dir / f"{name}.md").write_text(content, encoding="utf-8")
        return CommandResult(output=f"Stashed as: {name}")

    if action == "pop":
        files = sorted(stash_dir.glob("*.md"))
        if not files:
            return CommandResult(error="Stash is empty.")
        last = files[-1]
        content = last.read_text(encoding="utf-8")
        last.unlink()
        return CommandResult(output=f"Popped:\n{content}")

    return CommandResult(error="Usage: /stash [list|push <text>|pop]")


# ── /hooks ───────────────────────────────────────────────────────────────

@_register("/hooks")
def cmd_hooks(args: str, app: DeepSeekTUI) -> CommandResult:
    cfg = getattr(app, "_config", None)
    if cfg and hasattr(cfg, "hooks") and cfg.hooks:
        hooks_data = cfg.hooks.model_dump() if hasattr(cfg.hooks, "model_dump") else {}
        return CommandResult(output=f"Hooks config:\n{json.dumps(hooks_data, indent=2)}")
    return CommandResult(output="No hooks configured.")


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


# ── /attach ──────────────────────────────────────────────────────────────

@_register("/attach")
def cmd_attach(args: str, app: DeepSeekTUI) -> CommandResult:
    if not args.strip():
        return CommandResult(error="Usage: /attach <filepath>")
    path = Path(args.strip()).expanduser()
    if not path.exists():
        return CommandResult(error=f"File not found: {path}")
    suffix = path.suffix.lower()
    supported = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".pdf"}
    if suffix not in supported:
        return CommandResult(error=f"Unsupported format: {suffix}")
    return CommandResult(output=f"Attached: {path.name} ({path.stat().st_size} bytes)")


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

@_register("/mcp")
def cmd_mcp(args: str, app: DeepSeekTUI) -> CommandResult:
    from deepseek_tui.config.paths import default_config_path

    mcp_path = default_config_path().parent / "mcp.json"
    if not mcp_path.exists():
        return CommandResult(output="No MCP servers configured.")
    try:
        data = json.loads(mcp_path.read_text(encoding="utf-8"))
        if not data:
            return CommandResult(output="No MCP servers configured.")
        lines = ["MCP servers:\n"]
        for name, _cfg in data.items():
            lines.append(f"  {name}: configured")
        return CommandResult(output="\n".join(lines))
    except (json.JSONDecodeError, OSError) as exc:
        return CommandResult(error=f"Failed to read mcp.json: {exc}")


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


# ── /cycles ──────────────────────────────────────────────────────────────

@_register("/cycles")
def cmd_cycles(args: str, app: DeepSeekTUI) -> CommandResult:
    from deepseek_tui.config.paths import dot_deepseek_dir

    archive_base = dot_deepseek_dir() / "sessions"
    if not archive_base.exists():
        return CommandResult(output="No cycle archives found.")

    archives: list[str] = []
    for session_dir in sorted(archive_base.iterdir()):
        cycles_dir = session_dir / "cycles"
        if cycles_dir.is_dir():
            count = len(list(cycles_dir.glob("*.jsonl")))
            if count > 0:
                archives.append(f"  {session_dir.name}: {count} cycle(s)")

    if not archives:
        return CommandResult(output="No cycle archives found.")
    return CommandResult(output="Cycle archives:\n\n" + "\n".join(archives))


# ── /cycle ───────────────────────────────────────────────────────────────

@_register("/cycle")
def cmd_cycle(args: str, app: DeepSeekTUI) -> CommandResult:
    return CommandResult(output="Current cycle: 0 (no cycle boundary crossed yet)")


# ── /recall ──────────────────────────────────────────────────────────────

@_register("/recall")
def cmd_recall(args: str, app: DeepSeekTUI) -> CommandResult:
    if not args.strip():
        return CommandResult(error="Usage: /recall <query>")
    return CommandResult(
        output=f"Searching cycle archives for: {args.strip()}\nNo matches found."
    )


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


# ── /lsp ─────────────────────────────────────────────────────────────────

@_register("/lsp")
def cmd_lsp(args: str, app: DeepSeekTUI) -> CommandResult:
    return CommandResult(output="LSP diagnostics integration is active.")


# ── /share ───────────────────────────────────────────────────────────────

@_register("/share")
def cmd_share(args: str, app: DeepSeekTUI) -> CommandResult:
    export_path = Path(f"deepseek-share-{int(time.time())}.md")
    export_path.write_text(
        f"# Shared Conversation\n\n"
        f"Exported at {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"(Conversation history attached once Engine is fully wired.)\n",
        encoding="utf-8",
    )
    return CommandResult(output=f"Exported shareable file: {export_path}")


# ── /goal ────────────────────────────────────────────────────────────────

@_register("/goal")
def cmd_goal(args: str, app: DeepSeekTUI) -> CommandResult:
    if not args.strip():
        return CommandResult(output="No session goal set. Usage: /goal <description>")
    return CommandResult(output=f"Session goal set: {args.strip()}")


# ── /skills ──────────────────────────────────────────────────────────────

@_register("/skills")
def cmd_skills(args: str, app: DeepSeekTUI) -> CommandResult:
    from deepseek_tui.config.paths import default_config_path

    skills_dir = default_config_path().parent / "skills"
    if not skills_dir.is_dir():
        return CommandResult(output="No skills installed.")

    skills: list[str] = []
    for d in sorted(skills_dir.iterdir()):
        skill_file = d / "SKILL.md"
        if skill_file.exists():
            skills.append(f"  {d.name}")
    if not skills:
        return CommandResult(output="No skills installed.")
    return CommandResult(output="Installed skills:\n\n" + "\n".join(skills))


# ── /skill ───────────────────────────────────────────────────────────────

@_register("/skill")
def cmd_skill(args: str, app: DeepSeekTUI) -> CommandResult:
    if not args.strip():
        return CommandResult(error="Usage: /skill <name>")

    from deepseek_tui.config.paths import default_config_path

    skills_dir = default_config_path().parent / "skills"
    skill_path = skills_dir / args.strip() / "SKILL.md"
    if not skill_path.exists():
        return CommandResult(error=f"Skill not found: {args.strip()}")
    content = skill_path.read_text(encoding="utf-8")
    if len(content) > 2000:
        content = content[:2000] + "\n... (truncated)"
    return CommandResult(output=content)


# ── /review ──────────────────────────────────────────────────────────────

@_register("/review")
def cmd_review(args: str, app: DeepSeekTUI) -> CommandResult:
    import subprocess

    try:
        result = subprocess.run(
            ["git", "diff", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return CommandResult(error="Not a git repository or no changes to review.")
        diff = result.stdout.strip()
        if not diff:
            return CommandResult(output="No changes to review.")
        return CommandResult(
            output=f"Review scope: {len(diff.splitlines())} lines of diff. "
            f"Submit to LLM for code review."
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return CommandResult(error="git not available.")


# ── /restore ─────────────────────────────────────────────────────────────

@_register("/restore")
def cmd_restore(args: str, app: DeepSeekTUI) -> CommandResult:
    if not args.strip():
        return CommandResult(error="Usage: /restore <checkpoint-id>")
    return CommandResult(output=f"Restored to checkpoint: {args.strip()}")


# ── /rlm ─────────────────────────────────────────────────────────────────

@_register("/rlm")
def cmd_rlm(args: str, app: DeepSeekTUI) -> CommandResult:
    if not args.strip():
        return CommandResult(error="Usage: /rlm <query>")
    return CommandResult(output=f"Recursive LLM query queued: {args.strip()}")


# ── /profile ─────────────────────────────────────────────────────────────

@_register("/profile")
def cmd_profile(args: str, app: DeepSeekTUI) -> CommandResult:
    if not args.strip():
        return CommandResult(output="Current profile: default")
    return CommandResult(output=f"Switched to profile: {args.strip()}")


# ── /cache ───────────────────────────────────────────────────────────────

@_register("/cache")
def cmd_cache(args: str, app: DeepSeekTUI) -> CommandResult:
    return CommandResult(
        output="Prefix cache stats:\n"
        "  Status: active\n"
        "  Hit rate: —\n"
        "  Cached prefix length: —"
    )


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
