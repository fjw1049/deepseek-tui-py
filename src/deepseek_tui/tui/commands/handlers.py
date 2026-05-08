"""P0 slash command handler implementations.

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
    return CommandResult(output="Session save — requires StateStore integration (Stage 6)")


# ── /sessions ────────────────────────────────────────────────────────────

@_register("/sessions")
def cmd_sessions(args: str, app: DeepSeekTUI) -> CommandResult:
    return CommandResult(output="Session picker — requires StateStore integration (Stage 6)")


# ── /load ────────────────────────────────────────────────────────────────

@_register("/load")
def cmd_load(args: str, app: DeepSeekTUI) -> CommandResult:
    return CommandResult(output="Session load — requires StateStore integration (Stage 6)")


# ── /context ─────────────────────────────────────────────────────────────

@_register("/context")
def cmd_context(args: str, app: DeepSeekTUI) -> CommandResult:
    return CommandResult(output="Context inspector — requires Engine integration (Stage 6)")


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
    return CommandResult(output="Opening config editor...")


# ── /agent ───────────────────────────────────────────────────────────────

@_register("/agent")
def cmd_agent(args: str, app: DeepSeekTUI) -> CommandResult:
    return CommandResult(output="Switched to Agent mode.")


# ── /plan ────────────────────────────────────────────────────────────────

@_register("/plan")
def cmd_plan(args: str, app: DeepSeekTUI) -> CommandResult:
    return CommandResult(output="Switched to Plan mode.")


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
    return CommandResult(output="Token usage — requires Engine integration (Stage 6)")


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
    return CommandResult(output="Undo last message pair — requires Engine integration (Stage 6)")


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
    return CommandResult(output="Cost breakdown — requires Engine integration (Stage 6)")
