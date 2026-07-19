"""Slash command registry and dispatcher.

Central registry of slash
commands with description, aliases, and handler dispatch.
"""
from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
import json
import time
from collections.abc import Callable
from pathlib import Path

if TYPE_CHECKING:
    from deepseek_tui.tui.app import DeepSeekTUI

__all__ = [
    "CommandCategory",
    "CommandEntry",
    "CommandResult",
    "REGISTRY",
    "dispatch",
    "get_completions",
]

_LOG = logging.getLogger(__name__)


class CommandCategory(str, enum.Enum):
    DISPLAY = "display"
    CONFIG = "config"
    SESSION = "session"
    ENGINE = "engine"
    TOOL = "tool"


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Return value from a slash command handler."""

    output: str = ""
    error: str = ""
    exit_app: bool = False
    # When set, the app submits this text as a user message (used by plugin
    # ``/<plugin>:<command>`` commands — the engine expands the template).
    submit_message: str | None = None


@dataclass(frozen=True, slots=True)
class CommandEntry:
    """A single registered slash command."""

    name: str
    description: str
    category: CommandCategory
    aliases: tuple[str, ...] = ()


# Helper to shorten definitions.
_D = CommandCategory.DISPLAY
_C = CommandCategory.CONFIG
_S = CommandCategory.SESSION
_E = CommandCategory.ENGINE
_T = CommandCategory.TOOL

# ── Registry ─────────────────────────────────────────────────────────────

REGISTRY: list[CommandEntry] = [
    CommandEntry("/help", "Show help information", _D, ("/?",)),
    CommandEntry("/clear", "Clear conversation history", _S),
    CommandEntry("/exit", "Exit the application", _S, ("/quit", "/q")),
    CommandEntry("/model", "Switch or view current model", _E),
    CommandEntry("/provider", "Switch LLM backend", _E),
    CommandEntry(
        "/hooks", "List lifecycle hooks",
        _D, ("/hook",),
    ),
    CommandEntry(
        "/subagents", "List sub-agent status",
        _T, ("/agents",),
    ),
    CommandEntry(
        "/task", "Manage background tasks",
        _T, ("/tasks",),
    ),
    CommandEntry(
        "/jobs", "Inspect shell jobs",
        _T, ("/job",),
    ),
    CommandEntry("/mcp", "Manage MCP servers", _T),
    CommandEntry("/save", "Save session to file", _S),
    CommandEntry("/load", "Load session from file", _S),
    CommandEntry(
        "/compact", "Trigger context compaction",
        _S,
    ),
    CommandEntry("/context", "Context inspector", _D, ("/ctx",)),
    CommandEntry("/export", "Export to markdown", _S),
    CommandEntry("/config", "Open configuration editor", _C),
    CommandEntry(
        "/mode",
        "Switch or cycle mode (agent / plan / yolo / ask / workflow)",
        _C,
    ),
    CommandEntry("/yolo", "Enable YOLO mode", _C),
    CommandEntry("/agent", "Switch to agent mode", _C),
    CommandEntry("/plan", "Switch to plan mode", _C),
    CommandEntry("/workflow", "Switch to workflow mode", _C),
    CommandEntry("/logout", "Clear API key", _C),
    CommandEntry("/tokens", "Show token usage", _D),
    CommandEntry("/system", "Show system prompt", _D),
    CommandEntry(
        "/diff", "Show file changes",
        _D,
    ),
    CommandEntry("/init", "Generate AGENTS.md", _T),
    CommandEntry("/settings", "Show persistent settings", _D),
    CommandEntry(
        "/plugins", "List / manage plugins",
        _T, ("/plugin",),
    ),
    CommandEntry(
        "/skills", "List local skills",
        _T,
    ),
    CommandEntry(
        "/skill", "Activate/install a skill",
        _T,
    ),
    CommandEntry("/cost", "Session cost breakdown", _D),
    CommandEntry(
        "/log", "Show log file path; '/log tail [N]' prints last N lines",
        _D,
    ),
    CommandEntry("/undo", "Undo last file-modifying tool", _E),
    CommandEntry("/endpoint", "Manage OpenAI/Anthropic-compatible endpoints", _C),
]

# Build lookup dicts for fast dispatch.
_BY_NAME: dict[str, CommandEntry] = {}
_ALIAS_TO_NAME: dict[str, str] = {}
for _entry in REGISTRY:
    _BY_NAME[_entry.name] = _entry
    for _alias in _entry.aliases:
        _ALIAS_TO_NAME[_alias] = _entry.name


def resolve(input_name: str) -> CommandEntry | None:
    """Resolve a slash command name (including aliases)."""
    if input_name in _BY_NAME:
        return _BY_NAME[input_name]
    canonical = _ALIAS_TO_NAME.get(input_name)
    if canonical:
        return _BY_NAME[canonical]
    return None


def _plugin_commands(app: DeepSeekTUI | None) -> dict[str, object]:
    """The engine's registered plugin commands, or empty when unavailable."""
    engine = getattr(app, "_engine", None) if app is not None else None
    commands = getattr(engine, "plugin_commands", None)
    return commands if isinstance(commands, dict) else {}


def _plugin_index(app: DeepSeekTUI | None) -> dict[str, dict[str, Any]]:
    """The engine's lockfile contribution index, or empty when unavailable."""
    engine = getattr(app, "_engine", None) if app is not None else None
    index = getattr(engine, "plugin_index", None)
    return index if isinstance(index, dict) else {}


def _is_plugin_command(cmd_name: str, app: DeepSeekTUI | None) -> bool:
    """True when ``cmd_name`` (``/plugin:command``) is a known plugin command.

    Checks both activated commands (``plugin_commands``) and indexed-but-
    unactivated commands (``plugin_index``) so the user can invoke a
    plugin command before it has been heavy-assembled.
    """
    token = cmd_name.lstrip("/").lower()
    if token in _plugin_commands(app):
        return True
    if ":" not in token:
        return False
    plugin_part, cmd_part = token.split(":", 1)
    for pname, idx in _plugin_index(app).items():
        if pname.lower() != plugin_part or not isinstance(idx, dict):
            continue
        for c in idx.get("commands", []):
            if isinstance(c, dict) and c.get("name", "").lower() == cmd_part:
                return True
    return False


def get_completions(
    prefix: str = "", app: DeepSeekTUI | None = None
) -> list[tuple[str, str]]:
    """Return (name, description) pairs matching a prefix.

    Built-in commands plus any plugin ``/<plugin>:<command>`` entries when an
    engine is available on ``app``.
    """
    results: list[tuple[str, str]] = []
    for entry in REGISTRY:
        if entry.name.startswith(prefix):
            results.append((entry.name, entry.description))
    for cmd in _plugin_commands(app).values():
        name = f"/{cmd.qualified}"
        if name.startswith(prefix):
            desc = getattr(cmd, "description", "") or "plugin command"
            results.append((name, desc))
    # Indexed-but-unactivated plugin commands.
    for pname, idx in _plugin_index(app).items():
        if not isinstance(idx, dict):
            continue
        for c in idx.get("commands", []):
            if not isinstance(c, dict):
                continue
            cmd_name = c.get("name", "")
            if not cmd_name:
                continue
            qual = f"/{pname}:{cmd_name}"
            if qual.startswith(prefix):
                results.append((qual, c.get("description", "") or "plugin command"))
    return results


def dispatch(raw_input: str, app: DeepSeekTUI) -> CommandResult:
    """Parse and dispatch a slash command."""
    parts = raw_input.strip().split(maxsplit=1)
    if not parts:
        return CommandResult(error="empty command")

    cmd_name = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    entry = resolve(cmd_name)
    if entry is None:
        # Plugin prompt command (/<plugin>:<command>): hand the raw text to
        # the engine, which expands the template and sends it as a message.
        if ":" in cmd_name and _is_plugin_command(cmd_name, app):
            return CommandResult(submit_message=raw_input.strip())
        return CommandResult(
            error=f"unknown command: {cmd_name}. Type /help",
        )

    handler_fn = get_handler(entry.name)
    if handler_fn is None:
        return CommandResult(error=f"{entry.name} has no handler")

    try:
        return handler_fn(args, app)
    except Exception as exc:
        _LOG.exception("slash command %s failed", entry.name)
        return CommandResult(error=f"{entry.name} failed: {exc}")


# ======================================================================
# Handlers
# ======================================================================

"""Slash command handler implementations.

Each handler has signature: ``(args: str, app: DeepSeekTUI) -> CommandResult``.
"""




from deepseek_tui.tui.status import StatusBar
from deepseek_tui.tui.transcript import Transcript

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
        lines.append(f"  {entry.name:<14}{entry.description}{alias_str}")
    return CommandResult(output="\n".join(lines))


# ── /clear ───────────────────────────────────────────────────────────────

@_register("/clear")
def cmd_clear(args: str, app: DeepSeekTUI) -> CommandResult:
    """Clear transcript and engine session — delegates to Ctrl+N action."""
    app.action_new_session()
    return CommandResult(output="Conversation cleared.")


# ── /exit ────────────────────────────────────────────────────────────────

@_register("/exit")
def cmd_exit(args: str, app: DeepSeekTUI) -> CommandResult:
    return CommandResult(output="Exiting...", exit_app=True)


# ── /model ───────────────────────────────────────────────────────────────

def _apply_model_to_app(app: DeepSeekTUI, model: str) -> None:
    """Mirror the ModelPicker callback: config + engine + bottom chrome."""
    cfg = getattr(app, "config", None)
    if cfg is not None:
        cfg.model = model
    if app._engine is not None:
        app._engine.default_model = model
    try:
        from deepseek_tui.tui.input import ComposerHint

        app.query_one(StatusBar).set_model(model)
        app.query_one(ComposerHint).set_model(model)
    except Exception:  # noqa: BLE001 — best-effort UI refresh
        pass


@_register("/model")
def cmd_model(args: str, app: DeepSeekTUI) -> CommandResult:
    from deepseek_tui.config.providers import PROVIDER_DEFAULTS

    if not args.strip():
        cfg = getattr(app, "config", None)
        if cfg is not None:
            return CommandResult(output=f"Current model: {cfg.model or cfg.default_text_model}")
        return CommandResult(output="Current model: (unknown — config not attached)")

    requested = args.strip()
    _apply_model_to_app(app, requested)
    for prov_name, defaults in PROVIDER_DEFAULTS.items():
        known = {defaults.model}
        if defaults.flash_model:
            known.add(defaults.flash_model)
        if requested in known:
            return CommandResult(output=f"Model set to: {requested} ({prov_name})")

    return CommandResult(output=f"Model set to: {requested} (unverified — not in registry)")


# ── /mode ────────────────────────────────────────────────────────────────

_VALID_MODES: tuple[str, ...] = ("agent", "plan", "yolo", "ask", "workflow")


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
    _switch_mode(app, arg)
    return CommandResult(output=f"Mode → {arg}")


def _switch_mode(app: DeepSeekTUI, mode: str) -> None:
    """Directly switch the interaction mode (UI + engine.mode)."""
    previous_mode = getattr(app, "_interaction_mode", "agent")
    app._interaction_mode = mode  # type: ignore[attr-defined]
    if app._engine is not None:
        app._engine.mode = mode
        app.run_worker(
            app._engine.run_lifecycle_hook("mode_change", previous_mode=previous_mode),
            name="mode-change-hook",
        )
    try:
        from deepseek_tui.tui.input import ComposerHint
        from deepseek_tui.tui.status import StatusBar

        app.query_one(StatusBar).set_mode(mode)
        app.query_one(ComposerHint).set_mode(mode)
    except Exception:  # noqa: BLE001 — best-effort UI refresh
        pass


# ── /provider ────────────────────────────────────────────────────────────

@_register("/provider")
def cmd_provider(args: str, app: DeepSeekTUI) -> CommandResult:
    from deepseek_tui.config.providers import PROVIDER_DEFAULTS

    if not args.strip():
        cfg = getattr(app, "config", None)
        current = cfg.provider if cfg else "unknown"
        return CommandResult(output=f"Current provider: {current}")

    requested = args.strip().lower()
    cfg = getattr(app, "config", None)
    if cfg is None:
        return CommandResult(error="config not attached — cannot switch provider")

    # Accept any provider: either in PROVIDER_DEFAULTS or user-configured
    # in [providers.X] section. Only reject if completely unknown.
    is_known = requested in PROVIDER_DEFAULTS
    is_user_configured = requested in cfg.providers
    if not is_known and not is_user_configured:
        available = sorted(set(list(PROVIDER_DEFAULTS.keys()) + list(cfg.providers.keys())))
        return CommandResult(
            error=(
                f"Unknown provider: {requested}. "
                f"Available: {', '.join(available)}. "
                f"Add [providers.{requested}] to config.toml or use /endpoint to add one."
            )
        )

    previous_provider = cfg.provider
    previous_model = cfg.model
    cfg.provider = requested

    # Resolve model: user-configured > PROVIDER_DEFAULTS > keep current
    provider_cfg = cfg.providers.get(requested)
    if provider_cfg is not None and provider_cfg.model:
        new_model = provider_cfg.model
    elif is_known:
        new_model = PROVIDER_DEFAULTS[requested].model
    else:
        new_model = cfg.model or cfg.default_text_model

    cfg.model = new_model

    if app._engine is None:
        return CommandResult(
            output=(
                f"Provider set to: {requested} (model: {new_model}). "
                "Engine not started yet — it will be used at startup."
            )
        )

    new_client = app._build_client()
    if new_client is None:
        cfg.provider = previous_provider
        cfg.model = previous_model
        return CommandResult(
            error=(
                f"No API key found for {requested} — run `deepseek-tui login`, "
                f"set the provider env var, or add [providers.{requested}] "
                "api_key to config.toml, then retry."
            )
        )

    old_client = app._engine.client
    app._engine.client = new_client
    app._engine.turn_loop.client = new_client
    _apply_model_to_app(app, new_model)
    close = getattr(old_client, "close", None)
    if close is not None:
        import asyncio

        try:
            asyncio.get_running_loop()
            asyncio.ensure_future(close())
        except RuntimeError:
            pass
    return CommandResult(
        output=(
            f"Provider switched to: {requested} (model: {new_model}). "
            "Note: running subagents keep the previous client until restart."
        )
    )


# ── /endpoint ──────────────────────────────────────────────────────────

def _run_endpoint_test_async(
    app: DeepSeekTUI,
    base_url: str,
    api_key: str,
    model: str,
    label: str,
    *,
    protocol: str = "openai",
) -> None:
    """Fire-and-forget async endpoint test, writes result to transcript."""
    import asyncio

    async def _test() -> None:
        from deepseek_tui.client.factory import test_endpoint
        from deepseek_tui.tui.transcript import Transcript

        result = await test_endpoint(
            base_url, api_key, model, protocol=protocol
        )
        transcript = app.query_one(Transcript)
        if result.success:
            transcript.add_notice(
                f"[{label}] ✓ {result.message}", severity="info"
            )
        else:
            transcript.add_notice(
                f"[{label}] ✗ {result.message}", severity="error"
            )

    try:
        asyncio.ensure_future(_test())
    except RuntimeError:
        pass


@_register("/endpoint")
def cmd_endpoint(args: str, app: DeepSeekTUI) -> CommandResult:
    """Add, list, test, or remove custom endpoints at runtime.

    Usage:
      /endpoint                           — list configured endpoints
      /endpoint add <name> <protocol> <url> <model>  — add, test, and switch
      /endpoint test [name]               — test connectivity
      /endpoint remove <name>             — remove a custom endpoint
    """
    from deepseek_tui.config.models import ProviderConfig

    cfg = getattr(app, "config", None)
    if cfg is None:
        return CommandResult(error="config not attached")

    parts = args.strip().split()

    # /endpoint (no args) — list
    if not parts:
        lines = [f"Current provider: {cfg.provider}\n", "Configured endpoints:"]
        for name, pc in cfg.providers.items():
            url = pc.base_url or "(default)"
            model = pc.model or "(default)"
            has_key = "✓" if pc.api_key else "✗"
            active = " ←" if name == cfg.provider else ""
            lines.append(f"  {name:<20} url={url}  model={model}  key={has_key}{active}")
        if not cfg.providers:
            lines.append(
                "  (none — add with /endpoint add <name> "
                "<openai|anthropic> <url> <model>)"
            )
        lines.append("")
        lines.append("Commands: /endpoint add|test|remove")
        return CommandResult(output="\n".join(lines))

    action = parts[0].lower()

    # API keys deliberately do not travel through slash-command text because
    # commands can be retained in transcripts/session history.
    if action == "add":
        if len(parts) < 5:
            return CommandResult(
                error=(
                    "Usage: /endpoint add <name> <openai|anthropic> "
                    "<base_url> <model>"
                )
            )
        name = parts[1].lower()
        protocol = parts[2].lower()
        if protocol not in {"openai", "anthropic"}:
            return CommandResult(error="protocol must be openai or anthropic")
        base_url = parts[3]
        model = " ".join(parts[4:])

        from deepseek_tui.state.secrets import SecretsManager

        api_key = SecretsManager().resolve_api_key(
            cfg, provider_name=name
        )
        if not api_key:
            return CommandResult(
                error=(
                    f"No API key stored for '{name}'. Configure its provider "
                    "key via keyring/config/environment before adding the endpoint."
                )
            )

        # Register in config
        cfg.providers[name] = ProviderConfig(
            base_url=base_url,
            model=model,
            protocol=protocol,
        )

        # Auto-switch to the new endpoint
        cfg.provider = name
        cfg.model = model

        if app._engine is not None:
            new_client = app._build_client()
            if new_client is not None:
                old_client = app._engine.client
                app._engine.client = new_client
                app._engine.turn_loop.client = new_client
                _apply_model_to_app(app, model)
                close = getattr(old_client, "close", None)
                if close is not None:
                    import asyncio
                    try:
                        asyncio.get_running_loop()
                        asyncio.ensure_future(close())
                    except RuntimeError:
                        pass
            else:
                return CommandResult(
                    error=f"Endpoint registered but failed to build client for {name}"
                )
        else:
            _apply_model_to_app(app, model)

        # Auto-test connectivity
        _run_endpoint_test_async(
            app,
            base_url,
            api_key,
            model,
            f"测试 {name}",
            protocol=protocol,
        )

        return CommandResult(
            output=(
                f"Endpoint '{name}' added and activated.\n"
                f"  url:   {base_url}\n"
                f"  model: {model}\n"
                "正在测试连接..."
            )
        )

    # /endpoint test [name]
    if action == "test":
        name = parts[1].lower() if len(parts) > 1 else cfg.provider
        pc = cfg.providers.get(name)
        if pc is None:
            from deepseek_tui.config.providers import PROVIDER_DEFAULTS
            defaults = PROVIDER_DEFAULTS.get(name)
            if defaults is None:
                return CommandResult(error=f"Provider '{name}' 未配置")
            base_url = defaults.base_url
            model = defaults.model
            protocol = defaults.protocol
            # Try to resolve key
            from deepseek_tui.state.secrets import SecretsManager
            mgr = SecretsManager()
            api_key = mgr.resolve_api_key(cfg, provider_name=name) or ""
        else:
            from deepseek_tui.config.providers import PROVIDER_DEFAULTS
            defaults = PROVIDER_DEFAULTS.get(name)
            base_url = pc.base_url or (defaults.base_url if defaults else "")
            api_key = pc.api_key or ""
            model = pc.model or (defaults.model if defaults else "")
            protocol = pc.protocol or (defaults.protocol if defaults else "openai")
            if not api_key:
                from deepseek_tui.state.secrets import SecretsManager
                mgr = SecretsManager()
                api_key = mgr.resolve_api_key(cfg, provider_name=name) or ""

        if not base_url:
            return CommandResult(error=f"Provider '{name}' 未配置 base_url")
        if not api_key:
            return CommandResult(error=f"Provider '{name}' 未找到 API Key")

        _run_endpoint_test_async(
            app,
            base_url,
            api_key,
            model,
            f"测试 {name}",
            protocol=protocol,
        )
        return CommandResult(output=f"正在测试 '{name}' ({base_url}) ...")

    # /endpoint remove <name>
    if action in ("remove", "rm", "delete"):
        if len(parts) < 2:
            return CommandResult(error="Usage: /endpoint remove <name>")
        name = parts[1].lower()
        if name not in cfg.providers:
            return CommandResult(error=f"Endpoint '{name}' not found")
        if cfg.provider == name:
            return CommandResult(
                error=f"Cannot remove active provider '{name}'. Switch first with /provider."
            )
        del cfg.providers[name]
        return CommandResult(output=f"Endpoint '{name}' removed.")

    return CommandResult(
        error=(
            f"Unknown action: {action}. "
            "Usage: /endpoint [add|test|remove]"
        )
    )


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

    # Validate structure — metadata is optional (auto-persisted current.json).
    if "messages" not in session_data:
        return CommandResult(error="Invalid session file format")

    from deepseek_tui.tui.session_restore import (
        apply_messages_to_engine,
        parse_session_messages,
        session_metadata,
        session_started_at_iso,
    )

    try:
        restored_messages = parse_session_messages(session_data, path=load_path)
        metadata = session_metadata(session_data, path=load_path)
        apply_messages_to_engine(app._engine, restored_messages)
    except Exception as exc:
        return CommandResult(error=f"Failed to restore messages: {exc}")

    # Update UI
    transcript = app.query_one(Transcript)
    transcript.hydrate_from_messages(restored_messages)

    started = session_started_at_iso(metadata, path=load_path)
    if started:
        app._session_started_at_iso = started

    session_id = str(metadata.get("id", "unknown"))[:8]
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
        from deepseek_tui.tui.sidebar import (
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

    The prompt opens via :class:`PlanPromptScreen` (push_screen with a
    callback). Outside of a running Textual app (e.g. unit tests), the call
    short-circuits to a textual hint so the dispatch layer is still testable.
    """
    from deepseek_tui.tui.plan import PlanOutcome, PlanPromptScreen

    if not getattr(app, "is_running", False):
        return CommandResult(output="Switched to Plan mode.")

    _switch_mode(app, "plan")

    def _on_plan_outcome(outcome: PlanOutcome | None) -> None:
        # Map prompt outcomes onto real interaction modes; REVISE /
        # DISMISSED keep the freshly-entered plan mode.
        if outcome == PlanOutcome.ACCEPT_YOLO:
            _switch_mode(app, "yolo")
            from deepseek_tui.engine.handle import AutoApprovalHandler

            if app._engine is not None:
                app._engine.approval_handler = AutoApprovalHandler()
        elif outcome in (PlanOutcome.ACCEPT_AGENT, PlanOutcome.EXIT_PLAN):
            _switch_mode(app, "agent")

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


# ── /workflow ─────────────────────────────────────────────────────────────

@_register("/workflow")
def cmd_workflow(args: str, app: DeepSeekTUI) -> CommandResult:
    """Switch to Workflow mode (shortcut for ``/mode workflow``)."""
    return cmd_mode("workflow", app)


# ── /logout ──────────────────────────────────────────────────────────────

@_register("/logout")
def cmd_logout(args: str, app: DeepSeekTUI) -> CommandResult:
    from deepseek_tui.state.secrets import Secrets
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
    from deepseek_tui.engine.prompts import AppMode, compose_prompt
    prompt = compose_prompt(AppMode.AGENT)
    if len(prompt) > 2000:
        prompt = prompt[:2000] + "\n... (truncated)"
    return CommandResult(output=f"System prompt:\n{prompt}")


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
            "Available hook events (use one of these as `event = \"...\"` "
            "in your `[[hooks.hooks]]` entry):",
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
            "Hooks are globally disabled — set `[hooks].enabled = true` "
            "in config.toml to fire them."
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
    from deepseek_tui.tools.task import TaskStatus
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


def _mcp_focus_preview(app: DeepSeekTUI, name: str) -> CommandResult:
    """预览 `@<name>` 连接器聚焦时模型可见的工具集（连接器"导入测试"）。

    从活动引擎的 MCP manager 读取该 server 已发现的工具，与 `@<name> 问题`
    聚焦模式暴露给模型的工具一致（该 server 工具 + 基础读工具）。引擎未起或
    该连接器无工具时给出明确提示。
    """
    engine = app._engine
    manager = engine.mcp_manager if engine is not None else None
    if manager is None:
        return CommandResult(
            error="MCP not active — start the engine, or run /mcp reload after adding servers."
        )
    server_names = getattr(manager, "server_names", None) or []
    match = next((s for s in server_names if s.lower() == name.lower()), None)
    if match is None:
        available = ", ".join(server_names) or "(none configured)"
        return CommandResult(error=f"Connector not found: {name}. Available: {available}")
    tools = manager.grouped_discovered_tools().get(match, [])
    lines = [f"Connector @{match} — focus mode exposes {len(tools)} tool(s) + base read tools:"]
    for entry in tools:
        desc = (entry.get("description") or "").strip().splitlines()[0:1]
        suffix = f" — {desc[0]}" if desc else ""
        lines.append(f"  • {entry.get('name', '?')}{suffix}")
    if not tools:
        lines.append("  (no tools discovered yet — run /mcp reload to connect)")
    lines.append(f"Use it inline: `@{match} <your question>`")
    return CommandResult(output="\n".join(lines))


@_register("/mcp")
def cmd_mcp(args: str, app: DeepSeekTUI) -> CommandResult:
    from deepseek_tui.mcp.actions import (
        format_status,
        run_add,
        run_disable,
        run_enable,
        run_init,
        run_remove,
    )
    from deepseek_tui.mcp.store import resolve_mcp_config_path

    path = resolve_mcp_config_path(app.config)
    raw = (args or "").strip()
    if not raw or raw.lower() in {"status", "list", "show"}:
        return CommandResult(
            output=format_status(path, restart_required=_mcp_restart_required(app))
        )

    parts = raw.split()
    action = parts[0].lower()
    rest = parts[1:]
    restart_required = _mcp_restart_required(app)

    if action == "focus":
        if not rest:
            return CommandResult(error="Usage: /mcp focus <name>")
        return _mcp_focus_preview(app, rest[0])

    try:
        if action == "init":
            force = any(part in {"--force", "-f"} for part in rest)
            result = run_init(path, force=force)
            return CommandResult(output=result.output)

        if action == "add":
            try:
                result = run_add(
                    path, rest[0], rest, restart_required=restart_required
                )
            except ValueError as exc:
                return CommandResult(error=str(exc))
            _set_mcp_restart_required(app, True)
            return CommandResult(output=result.output)

        if action == "enable":
            if not rest:
                return CommandResult(error="Usage: /mcp enable <name>")
            result = run_enable(path, rest[0], restart_required=restart_required)
            _set_mcp_restart_required(app, True)
            return CommandResult(output=result.output)

        if action == "disable":
            if not rest:
                return CommandResult(error="Usage: /mcp disable <name>")
            result = run_disable(path, rest[0], restart_required=restart_required)
            _set_mcp_restart_required(app, True)
            return CommandResult(output=result.output)

        if action in {"remove", "rm"}:
            if not rest:
                return CommandResult(error="Usage: /mcp remove <name>")
            result = run_remove(path, rest[0], restart_required=restart_required)
            _set_mcp_restart_required(app, True)
            return CommandResult(output=result.output)

        if action in {"validate", "reload", "reconnect"}:
            app.run_worker(
                _mcp_discover_worker(
                    app, path, reload_engine=action in {"reload", "reconnect"}
                ),
                name="mcp-discover",
            )
            return CommandResult(output="Refreshing MCP discovery...")

        return CommandResult(
            error=(
                "Usage: /mcp [init|add stdio <name> <command> [args...]|"
                "add http <name> <url>|enable <name>|disable <name>|"
                "remove <name>|focus <name>|validate|reload]"
            )
        )
    except (KeyError, ValueError, OSError, json.JSONDecodeError) as exc:
        return CommandResult(error=f"MCP action failed: {exc}")


# ── /compact ─────────────────────────────────────────────────────────────

@_register("/compact")
def cmd_compact(args: str, app: DeepSeekTUI) -> CommandResult:
    if app._engine is None:
        return CommandResult(error="Engine not started")
    import asyncio

    async def _do_compact() -> None:
        from deepseek_tui.tui.transcript import Transcript

        engine = app._engine
        before = len(engine.session_messages)
        if before == 0:
            transcript = app.query_one(Transcript)
            transcript.add_notice("Nothing to compact — session is empty.", severity="info")
            return
        result = await engine._run_compaction(list(engine.session_messages))
        engine.session_messages[:] = result.messages
        transcript = app.query_one(Transcript)
        if result.success:
            transcript.add_notice(
                f"Context compacted: {before} → {len(result.messages)} messages.",
                severity="info",
            )
        else:
            transcript.add_notice(
                f"Compaction failed after {result.retries_used} retries — "
                f"messages unchanged ({before} → {len(result.messages)}). "
                f"See log for details; try again or run /clear.",
                severity="error",
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
    """
    from deepseek_tui.integrations.skills import default_skills_dir, fetch_registry

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

    local: list[str] = []
    if skills_dir.is_dir():
        for d in sorted(skills_dir.iterdir()):
            if not d.is_dir() or not (d / "SKILL.md").exists():
                continue
            if prefix and not d.name.lower().startswith(prefix):
                continue
            local.append(d.name)

    # Plugin-contributed skills, labeled by their owning plugin.
    plugin_skills: list[tuple[str, str]] = []
    try:
        from deepseek_tui.integrations.plugins import (
            collect_contributions,
            discover_plugins,
        )

        for p in discover_plugins(workspace=Path.cwd()):
            for s in collect_contributions([p]).skills:
                if prefix and not s.name.lower().startswith(prefix):
                    continue
                plugin_skills.append((s.name, p.name))
    except Exception:  # noqa: BLE001 — plugin listing is best-effort
        pass

    if not local and not plugin_skills:
        if prefix:
            return CommandResult(output=f"No skills match prefix `{prefix}`.")
        return CommandResult(output="No skills installed.")

    lines: list[str] = []
    if local:
        lines.append("Installed skills:\n")
        lines.extend(f"  {n}" for n in local)
    if plugin_skills:
        if lines:
            lines.append("")
        lines.append(f"Plugin skills ({len(plugin_skills)}):\n")
        lines.extend(f"  {n}  ({owner})" for n, owner in plugin_skills)
    return CommandResult(output="\n".join(lines))


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
    """
    from deepseek_tui.integrations.skills import (
        InstallSource,
        default_skills_dir,
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


# ── /plugins ─────────────────────────────────────────────────────────────

@_register("/plugins")
def cmd_plugins(args: str, app: DeepSeekTUI) -> CommandResult:
    """List / manage plugins (skills/hooks/MCP bundles).

    Usage:
        /plugins                     — list installed plugins
        /plugins info <name>         — show plugin description + README/PLAYBOOK
        /plugins install <spec>      — github:owner/repo, local path, or <plugin>@<marketplace>
        /plugins update <name>       — re-install from recorded source
        /plugins remove <name>       — uninstall
        /plugins enable <name>       — enable at user scope
        /plugins disable <name>      — disable at user scope
        /plugins trust <name>        — activate hooks/MCP servers
        /plugins untrust <name>      — deactivate hooks/MCP servers
        /plugins marketplace [add <spec> | list | plugins <name> |
                              update <name> | remove <name>]

    Skills/commands/agents/rules apply after rediscover; hooks/MCP from
    trusted plugins take effect on the next session (engine restart).
    """
    from deepseek_tui.integrations.plugins import (
        discover_plugins,
        install_plugin,
        plugin_description_blurb,
        set_plugin_enabled,
        set_plugin_trusted,
        uninstall_plugin,
        update_plugin,
        user_plugins_dir,
    )

    raw = args.strip()
    if not raw:
        from deepseek_tui.integrations.plugins import collect_contributions

        plugins = discover_plugins(workspace=Path.cwd(), include_disabled=True)
        if not plugins:
            return CommandResult(
                output=(
                    "No plugins installed.\n"
                    "Install one with `/plugins install <github:owner/repo|path>`."
                )
            )
        lines = [f"Installed plugins ({len(plugins)}):\n"]
        for p in plugins:
            flags = [p.scope]
            if not p.enabled:
                flags.append("disabled")
            if p.trusted:
                flags.append("trusted")
            lines.append(f"  {p.name} v{p.manifest.version} ({', '.join(flags)})")
            blurb = plugin_description_blurb(p)
            if blurb:
                lines.append(f"      {blurb}")
            readme = p.path / "README.md"
            playbook = p.path / "PLAYBOOK.md"
            if playbook.is_file():
                lines.append("      · docs: PLAYBOOK.md")
            elif readme.is_file():
                lines.append("      · docs: README.md")
            if not p.enabled:
                continue
            c = collect_contributions([p])
            parts: list[str] = []
            if c.skills:
                parts.append(f"{len(c.skills)} skills")
            if c.commands:
                parts.append(f"{len(c.commands)} commands")
            if c.agents:
                parts.append(f"{len(c.agents)} agents")
            if c.rules:
                parts.append(f"{len(c.rules)} rules")
            if c.hook_entries:
                parts.append(f"{len(c.hook_entries)} hooks")
            elif p.manifest.hooks and not p.trusted:
                parts.append("hooks(needs trust)")
            if c.mcp_servers:
                parts.append(f"{len(c.mcp_servers)} mcp")
            elif p.manifest.mcp_servers and not p.trusted:
                parts.append("mcp(needs trust)")
            if parts:
                lines.append(f"      {', '.join(parts)}")
            for a in c.agents:
                lines.append(f"      · agent: {a.plugin}:{a.name}")
            for r in c.rules:
                lines.append(f"      · rule: {r.plugin}/{r.name}")
        lines.append(
            "\nTip: skills/commands/agents load on demand; "
            "hooks/MCP need trust + a new session. "
            "Use `/plugins info <name>` to read README/PLAYBOOK."
        )
        return CommandResult(output="\n".join(lines))

    parts = raw.split(None, 1)
    head = parts[0]
    rest = parts[1].strip() if len(parts) > 1 else ""
    plugins_dir = user_plugins_dir()
    usage = (
        "Usage: /plugins [info <name> | install <spec> | update <name> | "
        "remove <name> | enable <name> | disable <name> | trust <name> | "
        "untrust <name> | marketplace …]"
    )
    if head == "marketplace":
        return _plugins_marketplace(rest)
    if not rest:
        return CommandResult(error=usage)

    if head == "info":
        return _plugins_info(rest)
    if head == "install":
        outcome, message = install_plugin(rest, plugins_dir)
        if outcome.value == "failed":
            return CommandResult(error=message)
        return CommandResult(output=message)
    if head == "update":
        outcome, message = update_plugin(rest, plugins_dir)
        if outcome.value == "failed":
            return CommandResult(error=message)
        return CommandResult(output=message)
    if head == "remove":
        return CommandResult(output=uninstall_plugin(rest, plugins_dir))
    if head == "enable":
        return CommandResult(output=set_plugin_enabled(rest, True, plugins_dir))
    if head == "disable":
        return CommandResult(output=set_plugin_enabled(rest, False, plugins_dir))
    if head == "trust":
        return CommandResult(output=set_plugin_trusted(rest, True, plugins_dir))
    if head == "untrust":
        return CommandResult(output=set_plugin_trusted(rest, False, plugins_dir))
    return CommandResult(error=usage)


def _plugins_info(name: str) -> CommandResult:
    """Show manifest description plus README/PLAYBOOK for one plugin."""
    from deepseek_tui.integrations.plugins import (
        discover_plugins,
        plugin_description_blurb,
        read_plugin_playbook,
    )

    needle = name.strip().lower()
    if not needle:
        return CommandResult(error="Usage: /plugins info <name>")
    match = None
    for plugin in discover_plugins(workspace=Path.cwd(), include_disabled=True):
        if plugin.name.lower() == needle:
            match = plugin
            break
    if match is None:
        return CommandResult(error=f"Plugin not found: {name}")
    lines = [
        f"{match.name} v{match.manifest.version} ({match.scope})",
        f"path: {match.path}",
    ]
    blurb = plugin_description_blurb(match, max_chars=500)
    if blurb:
        lines.append(f"description: {blurb}")
    docs = read_plugin_playbook(match.path, max_chars=8_000)
    if docs:
        source = (
            "PLAYBOOK.md"
            if (match.path / "PLAYBOOK.md").is_file()
            else "README.md"
        )
        lines.append("")
        lines.append(f"--- {source} ---")
        lines.append(docs)
    else:
        lines.append("")
        lines.append("(no README.md / PLAYBOOK.md in plugin root)")
    return CommandResult(output="\n".join(lines))


def _plugins_marketplace(raw: str) -> CommandResult:
    """Handle ``/plugins marketplace …`` subcommands."""
    from deepseek_tui.integrations.plugins import (
        add_marketplace,
        load_marketplace,
        read_marketplaces,
        remove_marketplace,
        update_marketplace,
    )

    usage = (
        "Usage: /plugins marketplace [add <github:owner/repo|path> | list | "
        "plugins <name> | update <name> | remove <name>]"
    )
    parts = raw.split(None, 1)
    head = parts[0] if parts else "list"
    rest = parts[1].strip() if len(parts) > 1 else ""

    if head == "list" or (head == "" and not rest):
        table = read_marketplaces()
        if not table:
            return CommandResult(
                output=(
                    "No marketplaces registered.\n"
                    "Add one with `/plugins marketplace add "
                    "<github:owner/repo|path>`."
                )
            )
        lines = [f"Registered marketplaces ({len(table)}):\n"]
        for name, entry in sorted(table.items()):
            try:
                count = len(load_marketplace(Path(str(entry.get("path", "")))))
            except (FileNotFoundError, OSError, ValueError):
                count = 0
            lines.append(f"  {name} ({entry.get('source', '?')}) — {count} plugins")
        lines.append(
            "\nInstall one plugin with `/plugins install <plugin>@<marketplace>`."
        )
        return CommandResult(output="\n".join(lines))
    if not rest:
        return CommandResult(error=usage)
    if head == "add":
        outcome, message = add_marketplace(rest)
        if outcome.value == "failed":
            return CommandResult(error=message)
        return CommandResult(output=message)
    if head == "plugins":
        entry = read_marketplaces().get(rest)
        if entry is None:
            return CommandResult(error=f"Marketplace not found: {rest}")
        try:
            entries = load_marketplace(Path(str(entry.get("path", ""))))
        except FileNotFoundError:
            return CommandResult(error=f"Marketplace {rest} has no marketplace.json")
        lines = [f"Plugins in {rest} ({len(entries)}):\n"]
        for e in entries:
            desc = f" — {e.description}" if e.description else ""
            lines.append(f"  {e.name}{desc}")
        lines.append(f"\nInstall with `/plugins install <plugin>@{rest}`.")
        return CommandResult(output="\n".join(lines))
    if head == "update":
        outcome, message = update_marketplace(rest)
        if outcome.value == "failed":
            return CommandResult(error=message)
        return CommandResult(output=message)
    if head == "remove":
        return CommandResult(output=remove_marketplace(rest))
    return CommandResult(error=usage)


# ── /log ──────────────────────────────────────────────────────────────────


@_register("/log")
def cmd_log(args: str, app: DeepSeekTUI) -> CommandResult:
    """Show the active log file path or tail the last N lines.

    Usage:
        /log              → print current log file path
        /log tail         → print last 50 lines
        /log tail 200     → print last 200 lines
    """
    from deepseek_tui.utils import current_log_path, tail_log

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
    """Undo the last file-modifying tool."""
    if app._engine is None:
        return CommandResult(error="Engine not started")
    success, msg = app._engine.undo_last_tool()
    if success:
        return CommandResult(output=msg)
    return CommandResult(error=msg)
