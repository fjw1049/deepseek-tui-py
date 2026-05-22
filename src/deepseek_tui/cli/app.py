"""CLI entry point — mirrors ``crates/cli/src/lib.rs``.

22 subcommands + global flags, using typer (Python equivalent of clap).
Rust passthroughs (doctor/models/sessions/resume/fork/init/setup/exec/
review/apply/eval/mcp/features/completions) become direct calls into the
corresponding Python modules rather than spawning a sibling binary.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import typer

from deepseek_tui.config.loader import ConfigLoader
from deepseek_tui.config.models import Config

# ── Global Typer app ─────────────────────────────────────────────────────

app = typer.Typer(
    name="deepseek-tui",
    add_completion=True,
    no_args_is_help=False,
    help="DeepSeek TUI — terminal AI agent (Python edition).",
)

# ── Global flags (mirrors Cli struct in Rust lib.rs:50-96) ───────────────

CONFIG_OPTION = typer.Option(None, "--config", help="Path to config TOML file.")
PROFILE_OPTION = typer.Option(None, "--profile", help="Config profile name.")
PROVIDER_OPTION = typer.Option(None, "--provider", help="Provider name override.")
MODEL_OPTION = typer.Option(None, "--model", help="Model name override.")
OUTPUT_MODE_OPTION = typer.Option(None, "--output-mode", help="Output mode (text/json).")
LOG_LEVEL_OPTION = typer.Option(None, "--log-level", help="Log level (debug/info/warn/error).")
LOG_DIR_OPTION = typer.Option(
    None, "--log-dir", help="Directory for per-hour rotating log files."
)
LOG_CONSOLE_OPTION = typer.Option(
    False, "--log-console", help="Also write log records to stderr."
)
API_KEY_OPTION = typer.Option(None, "--api-key", help="API key override.")
BASE_URL_OPTION = typer.Option(None, "--base-url", help="Base URL override.")
APPROVAL_POLICY_OPTION = typer.Option(None, "--approval-policy", help="Approval policy.")
SANDBOX_MODE_OPTION = typer.Option(None, "--sandbox-mode", help="Sandbox mode.")


def _load_config(
    config: Path | None = None,
    profile: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> Config:
    return ConfigLoader().load(
        config_path=config,
        profile_name=profile,
        provider=provider,
        model=model,
    )


# ── @app.callback: default action (no subcommand → launch TUI) ──────────

@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    config: Path | None = CONFIG_OPTION,
    profile: str | None = PROFILE_OPTION,
    provider: str | None = PROVIDER_OPTION,
    model: str | None = MODEL_OPTION,
    output_mode: str | None = OUTPUT_MODE_OPTION,
    log_level: str | None = LOG_LEVEL_OPTION,
    log_dir: Path | None = LOG_DIR_OPTION,
    log_console: bool = LOG_CONSOLE_OPTION,
    api_key: str | None = API_KEY_OPTION,
    base_url: str | None = BASE_URL_OPTION,
    approval_policy: str | None = APPROVAL_POLICY_OPTION,
    sandbox_mode: str | None = SANDBOX_MODE_OPTION,
    prompt: str | None = typer.Option(None, "-p", "--prompt", help="One-shot prompt."),
    version: bool = typer.Option(False, "--version", help="Print version and exit."),
) -> None:
    """Launch the interactive TUI (default when no subcommand given)."""
    if version:
        typer.echo("deepseek-tui-py 0.1.0")
        raise typer.Exit()

    if ctx.invoked_subcommand is not None:
        return

    loaded = _load_config(config, profile, provider, model)

    # Wire the rotating log handlers up before any subsystem runs so the
    # very first INFO event ("engine starting") lands in the file.
    from deepseek_tui.logging_setup import setup_logging

    setup_logging(
        loaded,
        level_override=log_level,
        dir_override=log_dir,
        console_override=log_console if log_console else None,
    )

    if prompt is not None:
        _run_one_shot(loaded, prompt)
        return

    _launch_tui(loaded)


def _launch_tui(config: Config) -> None:
    """Start the Textual TUI app with a fully wired Engine."""
    try:
        from deepseek_tui.tui.app import DeepSeekTUI
        tui_app = DeepSeekTUI(config=config)
        tui_app.run()
    except ImportError as exc:
        typer.echo("TUI not available — textual not installed.", err=True)
        raise typer.Exit(1) from exc


def _run_one_shot(config: Config, prompt: str) -> None:
    """Non-interactive single-shot execution (mirrors Rust ``-p`` flag)."""
    asyncio.run(_run_one_shot_async(config, prompt))


async def _run_one_shot_async(config: Config, prompt: str) -> None:
    """Async implementation of one-shot mode."""
    from deepseek_tui.client.deepseek import DeepSeekClient
    from deepseek_tui.engine.engine import Engine
    from deepseek_tui.engine.events import (
        ErrorEvent,
        TextDeltaEvent,
        ToolCallEvent,
        ToolResultEvent,
        TurnCompleteEvent,
    )
    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.secrets.manager import SecretsManager

    mgr = SecretsManager()
    api_key = mgr.resolve_api_key(config)
    if not api_key:
        typer.echo("No API key configured. Run `deepseek-tui login` first.", err=True)
        raise typer.Exit(1)

    pc = config.effective_provider_config()
    client = DeepSeekClient(
        api_key=api_key,
        base_url=pc.base_url or "https://api.deepseek.com",
        timeout_seconds=float(pc.timeout),
    )
    handle = EngineHandle()
    model = config.model or config.default_text_model
    engine = await Engine.create(handle, client, config=config, default_model=model)
    engine_task = asyncio.create_task(engine.run())

    try:
        await handle.send_message(prompt)
        async for event in handle.events():
            if isinstance(event, TextDeltaEvent):
                print(event.text, end="", flush=True)
            elif isinstance(event, ToolCallEvent):
                tc = event.tool_call
                typer.echo(f"\n[tool: {tc.name}]", err=True)
            elif isinstance(event, ToolResultEvent):
                status = "ok" if event.success else "error"
                typer.echo(f"[tool result: {status}]", err=True)
            elif isinstance(event, ErrorEvent):
                typer.echo(f"\nError: {event.message}", err=True)
                break
            elif isinstance(event, TurnCompleteEvent):
                print()
                break
    finally:
        engine_task.cancel()
        await engine.shutdown()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Subcommand: version
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.command()
def version() -> None:
    """Print the version string."""
    typer.echo("deepseek-tui-py 0.1.0")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Subcommand: doctor  (mirrors Rust Commands::Doctor)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.command()
def doctor(
    config: Path | None = CONFIG_OPTION,
    profile: str | None = PROFILE_OPTION,
    provider: str | None = PROVIDER_OPTION,
    model: str | None = MODEL_OPTION,
) -> None:
    """Run diagnostics on the DeepSeek TUI environment."""
    import platform
    import shutil

    typer.echo("deepseek-tui doctor")
    typer.echo(f"  python: {sys.version}")
    typer.echo(f"  platform: {platform.system()} {platform.release()}")
    typer.echo("  textual: ", nl=False)
    try:
        import textual
        typer.echo(textual.__version__)
    except ImportError:
        typer.echo("NOT INSTALLED", err=True)
    typer.echo("  httpx: ", nl=False)
    try:
        import httpx
        typer.echo(httpx.__version__)
    except ImportError:
        typer.echo("NOT INSTALLED", err=True)

    loaded = _load_config(config, profile, provider, model)
    typer.echo(f"  provider: {loaded.provider}")
    typer.echo(f"  model: {loaded.model or loaded.default_text_model}")
    from deepseek_tui.config.paths import user_config_path
    typer.echo(f"  config path: {user_config_path()}")

    api_key = loaded.api_key or loaded.effective_provider_config().api_key
    typer.echo(f"  api_key: {'set' if api_key else 'NOT SET'}")

    git_path = shutil.which("git")
    typer.echo(f"  git: {git_path or 'NOT FOUND'}")

    typer.echo("  status: OK" if api_key else "  status: MISSING API KEY")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Subcommand: models  (mirrors Rust Commands::Models → Model list)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.command()
def models(
    provider: str | None = PROVIDER_OPTION,
) -> None:
    """List available models from the provider registry."""
    from deepseek_tui.config.provider_registry import PROVIDER_DEFAULTS

    for prov_name, defaults in PROVIDER_DEFAULTS.items():
        if provider and prov_name != provider:
            continue
        typer.echo(f"{defaults.model} ({prov_name})")
        if defaults.flash_model:
            typer.echo(f"{defaults.flash_model} ({prov_name})")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Subcommand: serve  (mirrors Rust Commands::Serve → AppServer)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host for HTTP."),
    port: int = typer.Option(8787, "--port", help="Bind port for HTTP."),
    stdio: bool = typer.Option(
        False, "--stdio", help="Speak newline-delimited JSON-RPC on stdin/stdout."
    ),
    config: Path | None = CONFIG_OPTION,
    profile: str | None = PROFILE_OPTION,
    provider: str | None = PROVIDER_OPTION,
    model: str | None = MODEL_OPTION,
) -> None:
    """Start the app-server (HTTP by default; --stdio for JSON-RPC pipe)."""
    from deepseek_tui.app_server import AppServerOptions, run_http, run_stdio

    loaded = _load_config(config, profile, provider, model)
    if stdio:
        typer.echo("app-server: stdio JSON-RPC mode", err=True)
        asyncio.run(run_stdio(config=loaded))
        return
    typer.echo(f"app-server listening on http://{host}:{port}", err=True)
    options = AppServerOptions(host=host, port=port, config_path=config)
    asyncio.run(run_http(options, config=loaded))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Subcommand group: auth  (mirrors Rust Commands::Auth)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

auth_app = typer.Typer(help="Manage authentication credentials and provider keys.")
app.add_typer(auth_app, name="auth")

_PROVIDER_LIST = ["deepseek", "nvidia-nim", "openrouter", "novita", "openai"]


def _keyring_slot(provider_name: str) -> str:
    """Map provider name to keyring slot (mirrors Rust keyring_slot)."""
    return provider_name


def _provider_config_has_key(config: Config, provider_name: str) -> bool:
    """Check if a provider has an API key in the config file."""
    prov_cfg = config.providers.get(provider_name)
    if prov_cfg is not None and prov_cfg.api_key:
        return True
    if provider_name == "deepseek" and config.api_key:
        return True
    return False


def _get_secrets() -> Any:
    from deepseek_tui.secrets.facade import Secrets
    return Secrets.auto_detect()


@auth_app.command("status")
def auth_status(
    config: Path | None = CONFIG_OPTION,
    profile: str | None = PROFILE_OPTION,
) -> None:
    """Show current provider and auth state for all providers."""
    from deepseek_tui.secrets.env_map import env_for

    loaded = _load_config(config, profile)
    secrets = _get_secrets()
    typer.echo(f"provider: {loaded.provider}")
    typer.echo(f"keyring backend: {secrets.backend_name}")
    for prov in _PROVIDER_LIST:
        slot = _keyring_slot(prov)
        keyring_set = bool(secrets.get(slot))
        env_set = env_for(slot) is not None
        file_set = _provider_config_has_key(loaded, prov)
        typer.echo(f"{slot} auth: keyring={keyring_set}, env={env_set}, config={file_set}")


@auth_app.command("set")
def auth_set(
    provider: str = typer.Option(..., "--provider", help="Provider name."),
    api_key: str | None = typer.Option(None, "--api-key", help="API key value."),
    api_key_stdin: bool = typer.Option(False, "--api-key-stdin", help="Read key from stdin."),
) -> None:
    """Save an API key to the keyring (never written to disk in plaintext)."""
    secrets = _get_secrets()
    slot = _keyring_slot(provider)
    if api_key is not None:
        key = api_key
    elif api_key_stdin:
        key = sys.stdin.read().strip()
    else:
        key = typer.prompt(f"Enter API key for {slot}", hide_input=True)
    if not key:
        typer.echo("error: empty API key provided", err=True)
        raise typer.Exit(1)
    secrets.set(slot, key)
    typer.echo(f"saved API key for {slot} to {secrets.backend_name}")


@auth_app.command("get")
def auth_get(
    provider: str = typer.Option(..., "--provider", help="Provider name."),
    config: Path | None = CONFIG_OPTION,
    profile: str | None = PROFILE_OPTION,
) -> None:
    """Report whether a provider has a key configured (never prints the value)."""
    loaded = _load_config(config, profile)
    secrets = _get_secrets()
    slot = _keyring_slot(provider)
    in_keyring = bool(secrets.get(slot))
    from deepseek_tui.secrets.env_map import env_for as _env_for
    in_env = _env_for(slot) is not None
    in_file = _provider_config_has_key(loaded, provider)
    resolved = in_keyring or in_env or in_file
    if resolved:
        source = "keyring" if in_keyring else ("env" if in_env else "config-file")
        typer.echo(f"{slot}: set (source: {source})")
    else:
        typer.echo(f"{slot}: not set")


@auth_app.command("clear")
def auth_clear(
    provider: str = typer.Option(..., "--provider", help="Provider name."),
) -> None:
    """Delete a provider's key from the keyring."""
    secrets = _get_secrets()
    slot = _keyring_slot(provider)
    secrets.delete(slot)
    typer.echo(f"cleared API key for {slot}")


@auth_app.command("list")
def auth_list(
    config: Path | None = CONFIG_OPTION,
    profile: str | None = PROFILE_OPTION,
) -> None:
    """List all known providers with their auth state."""
    loaded = _load_config(config, profile)
    secrets = _get_secrets()
    from deepseek_tui.secrets.env_map import env_for as _env_for

    typer.echo(f"keyring backend: {secrets.backend_name}")
    typer.echo("provider     keyring  env  config")
    for prov in _PROVIDER_LIST:
        slot = _keyring_slot(prov)
        kr = "yes" if secrets.get(slot) else "no "
        env = "yes" if _env_for(slot) is not None else "no "
        file = "yes" if _provider_config_has_key(loaded, prov) else "no "
        typer.echo(f"{slot:<12}  {kr}        {env}     {file}")


@auth_app.command("migrate")
def auth_migrate(
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview only."),
    config: Path | None = CONFIG_OPTION,
    profile: str | None = PROFILE_OPTION,
) -> None:
    """Migrate plaintext keys from config.toml into the keyring."""
    loaded = _load_config(config, profile)
    secrets = _get_secrets()
    migrated: list[str] = []

    for prov in _PROVIDER_LIST:
        slot = _keyring_slot(prov)
        prov_cfg = loaded.providers.get(prov)
        value = prov_cfg.api_key if prov_cfg is not None else None
        if prov == "deepseek" and not value:
            value = loaded.api_key
        if not value or not value.strip():
            continue
        if not dry_run:
            secrets.set(slot, value)
        migrated.append(slot)

    typer.echo(f"keyring backend: {secrets.backend_name}")
    if not migrated:
        typer.echo("nothing to migrate (config.toml has no plaintext api_key entries)")
    else:
        action = "would migrate" if dry_run else "migrated"
        typer.echo(f"{action} {len(migrated)} provider key(s):")
        for slot in migrated:
            typer.echo(f"  - {slot}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Subcommand: login / logout  (mirrors Rust Commands::Login/Logout)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.command()
def login(
    provider: str = typer.Option("deepseek", "--provider", help="Provider name."),
    api_key: str | None = typer.Option(None, "--api-key", help="API key value."),
) -> None:
    """Save a DeepSeek API key to the shared config."""
    if api_key is None:
        api_key = typer.prompt(f"Enter API key for {provider}", hide_input=True)
    if not api_key or not api_key.strip():
        typer.echo("error: empty API key provided", err=True)
        raise typer.Exit(1)
    secrets = _get_secrets()
    secrets.set(_keyring_slot(provider), api_key)
    typer.echo(f"logged in using API key mode ({provider})")


@app.command()
def logout() -> None:
    """Remove saved authentication state for all providers."""
    secrets = _get_secrets()
    for prov in _PROVIDER_LIST:
        secrets.delete(_keyring_slot(prov))
    typer.echo("logged out")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Subcommand group: config  (mirrors Rust Commands::Config)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

config_app = typer.Typer(help="Read/write/list config values.")
app.add_typer(config_app, name="config")


@config_app.command("get")
def config_get(
    key: str = typer.Argument(..., help="Config key to read."),
    config: Path | None = CONFIG_OPTION,
    profile: str | None = PROFILE_OPTION,
) -> None:
    """Get a single config value."""
    loaded = _load_config(config, profile)
    value = _config_get_value(loaded, key)
    if value is not None:
        typer.echo(value)
    else:
        typer.echo(f"key not found: {key}", err=True)
        raise typer.Exit(1)


@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Config key to write."),
    value: str = typer.Argument(..., help="Value to write."),
    config: Path | None = CONFIG_OPTION,
    profile: str | None = PROFILE_OPTION,
) -> None:
    """Set a single config value (writes to config.toml)."""
    _cli_config_write(key, value)


@config_app.command("unset")
def config_unset(
    key: str = typer.Argument(..., help="Config key to remove."),
    config: Path | None = CONFIG_OPTION,
    profile: str | None = PROFILE_OPTION,
) -> None:
    """Remove a config key (writes to config.toml)."""
    _cli_config_write(key, None)


@config_app.command("list")
def config_list(
    config: Path | None = CONFIG_OPTION,
    profile: str | None = PROFILE_OPTION,
) -> None:
    """List all config key-value pairs."""
    loaded = _load_config(config, profile)
    for key, val in sorted(loaded.model_dump(exclude_none=True).items()):
        if isinstance(val, dict):
            for k2, v2 in sorted(val.items()):
                typer.echo(f"{key}.{k2} = {v2}")
        else:
            typer.echo(f"{key} = {val}")


@config_app.command("path")
def config_path() -> None:
    """Print the config file path."""
    from deepseek_tui.config.paths import user_config_path
    typer.echo(user_config_path())


@config_app.command("show")
def config_show(
    config: Path | None = CONFIG_OPTION,
    profile: str | None = PROFILE_OPTION,
    provider: str | None = PROVIDER_OPTION,
    model: str | None = MODEL_OPTION,
) -> None:
    """Show the fully resolved config as JSON."""
    loaded = _load_config(config, profile, provider, model)
    typer.echo(loaded.model_dump_json(indent=2))


def _config_get_value(config: Config, key: str) -> str | None:
    """Retrieve a config value by dotted key path."""
    parts = key.split(".")
    obj: object = config
    for part in parts:
        if hasattr(obj, part):
            obj = getattr(obj, part)
        elif isinstance(obj, dict):
            obj = obj.get(part)
            if obj is None:
                return None
        else:
            return None
    if obj is None:
        return None
    return str(obj)


def _cli_config_write(key: str, value: str | None) -> None:
    """Set or unset a key in the config TOML file."""
    from deepseek_tui.config.paths import user_config_path

    config_path = user_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    if config_path.exists():
        lines = config_path.read_text(encoding="utf-8").splitlines()

    found = False
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{key}") and "=" in stripped:
            left = stripped.split("=", 1)[0].strip()
            if left == key:
                found = True
                if value is not None:
                    new_lines.append(f'{key} = "{value}"')
                continue
        new_lines.append(line)

    if not found and value is not None:
        new_lines.append(f'{key} = "{value}"')

    config_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    if value is not None:
        typer.echo(f"set {key} = {value} in {config_path}")
    else:
        typer.echo(f"unset {key} from {config_path}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Subcommand group: model  (mirrors Rust Commands::Model)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

model_app = typer.Typer(help="Resolve or list available models across providers.")
app.add_typer(model_app, name="model")


@model_app.command("list")
def model_list(
    provider: str | None = typer.Option(None, "--provider", help="Filter by provider."),
) -> None:
    """List all models in the provider registry."""
    from deepseek_tui.config.provider_registry import PROVIDER_DEFAULTS

    for prov_name, defaults in PROVIDER_DEFAULTS.items():
        if provider and prov_name != provider:
            continue
        typer.echo(f"{defaults.model} ({prov_name})")
        if defaults.flash_model:
            typer.echo(f"{defaults.flash_model} ({prov_name})")


@model_app.command("resolve")
def model_resolve(
    model_name: str | None = typer.Argument(None, help="Model name to resolve."),
    provider: str | None = typer.Option(None, "--provider", help="Provider name."),
) -> None:
    """Resolve a model name to its canonical provider + model."""
    from deepseek_tui.config.provider_registry import PROVIDER_DEFAULTS

    requested = model_name or ""
    resolved_model = requested
    resolved_provider = provider or "deepseek"
    used_fallback = False

    if provider:
        defaults = PROVIDER_DEFAULTS.get(provider)
        if defaults:
            known = {defaults.model}
            if defaults.flash_model:
                known.add(defaults.flash_model)
            if requested in known:
                resolved_model = requested
            else:
                resolved_model = defaults.model
                used_fallback = True
    else:
        for prov_name, defaults in PROVIDER_DEFAULTS.items():
            known = {defaults.model}
            if defaults.flash_model:
                known.add(defaults.flash_model)
            if requested in known:
                resolved_provider = prov_name
                resolved_model = requested
                break
        else:
            used_fallback = True

    typer.echo(f"requested: {requested}")
    typer.echo(f"resolved: {resolved_model}")
    typer.echo(f"provider: {resolved_provider}")
    typer.echo(f"used_fallback: {used_fallback}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Subcommand group: thread  (mirrors Rust Commands::Thread)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

thread_app = typer.Typer(help="Manage thread/session metadata.")
app.add_typer(thread_app, name="thread")


def _open_session_manager() -> tuple[Any, Any]:
    """Open Database + SessionManager. Returns (db, manager) or (None, None)."""
    from deepseek_tui.config.paths import user_state_db_path
    from deepseek_tui.state.database import Database
    from deepseek_tui.state.session_manager import SessionManager

    db_path = user_state_db_path()
    if not db_path.exists():
        return None, None
    db = Database(db_path)
    return db, SessionManager(db)


@thread_app.command("list")
def thread_list(
    all_threads: bool = typer.Option(False, "--all", help="Include archived threads."),
    limit: int | None = typer.Option(20, "--limit", help="Max threads to show."),
) -> None:
    """List saved threads."""

    async def _run() -> None:
        db, mgr = _open_session_manager()
        if mgr is None:
            typer.echo("No saved threads (no state.db).")
            return
        await db.initialize()
        sessions = await mgr.list_sessions(limit=limit, include_archived=all_threads)
        if not sessions:
            typer.echo("No saved threads.")
            return
        for s in sessions:
            tag = " [archived]" if getattr(s, "archived", False) else ""
            typer.echo(f"{s.id}  {getattr(s, 'preview', '(unnamed)')}{tag}")

    asyncio.run(_run())


@thread_app.command("read")
def thread_read(
    thread_id: str = typer.Argument(..., help="Thread ID to read."),
) -> None:
    """Read a thread's metadata as JSON."""

    async def _run() -> None:
        db, mgr = _open_session_manager()
        if mgr is None:
            typer.echo("No saved threads (no state.db).", err=True)
            raise typer.Exit(1)
        await db.initialize()
        meta = await mgr.get_session(thread_id)
        if meta is None:
            typer.echo(f"Thread not found: {thread_id}", err=True)
            raise typer.Exit(1)
        from dataclasses import asdict, is_dataclass

        if is_dataclass(meta):
            typer.echo(json.dumps(asdict(meta), indent=2, default=str))
        else:
            typer.echo(json.dumps(getattr(meta, "__dict__", {}), indent=2, default=str))

    asyncio.run(_run())


@thread_app.command("resume")
def thread_resume(
    thread_id: str = typer.Argument(..., help="Thread ID to resume."),
    config: Path | None = CONFIG_OPTION,
    profile: str | None = PROFILE_OPTION,
) -> None:
    """Resume a saved thread (delegates to top-level `resume`)."""
    loaded = _load_config(config, profile)
    try:
        from deepseek_tui.tui.app import DeepSeekTUI
        DeepSeekTUI(config=loaded, resume_session_id=thread_id).run()
    except ImportError as exc:
        typer.echo(f"TUI not available: {exc}", err=True)
        raise typer.Exit(1) from exc


@thread_app.command("fork")
def thread_fork(
    thread_id: str = typer.Argument(..., help="Thread ID to fork."),
    config: Path | None = CONFIG_OPTION,
    profile: str | None = PROFILE_OPTION,
) -> None:
    """Fork a saved thread (delegates to top-level `fork`)."""
    loaded = _load_config(config, profile)
    try:
        from deepseek_tui.tui.app import DeepSeekTUI
        DeepSeekTUI(config=loaded, fork_session_id=thread_id).run()
    except ImportError as exc:
        typer.echo(f"TUI not available: {exc}", err=True)
        raise typer.Exit(1) from exc


@thread_app.command("archive")
def thread_archive(
    thread_id: str = typer.Argument(..., help="Thread ID to archive."),
) -> None:
    """Archive a thread."""

    async def _run() -> None:
        db, mgr = _open_session_manager()
        if mgr is None:
            typer.echo("No state.db found.", err=True)
            raise typer.Exit(1)
        await db.initialize()
        await mgr.archive(thread_id)
        typer.echo(f"Archived {thread_id}")

    asyncio.run(_run())


@thread_app.command("unarchive")
def thread_unarchive(
    thread_id: str = typer.Argument(..., help="Thread ID to unarchive."),
) -> None:
    """Unarchive a thread."""

    async def _run() -> None:
        db, mgr = _open_session_manager()
        if mgr is None:
            typer.echo("No state.db found.", err=True)
            raise typer.Exit(1)
        await db.initialize()
        await mgr.unarchive(thread_id)
        typer.echo(f"Unarchived {thread_id}")

    asyncio.run(_run())


@thread_app.command("set-name")
def thread_set_name(
    thread_id: str = typer.Argument(..., help="Thread ID."),
    name: str = typer.Argument(..., help="New thread name."),
) -> None:
    """Rename a thread."""

    async def _run() -> None:
        db, mgr = _open_session_manager()
        if mgr is None:
            typer.echo("No state.db found.", err=True)
            raise typer.Exit(1)
        await db.initialize()
        await mgr.set_name(thread_id, name)
        typer.echo(f"Renamed {thread_id} to {name!r}")

    asyncio.run(_run())


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Subcommand: sandbox  (mirrors Rust Commands::Sandbox)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

sandbox_app = typer.Typer(help="Evaluate sandbox/approval policy decisions.")
app.add_typer(sandbox_app, name="sandbox")


@sandbox_app.command("check")
def sandbox_check(
    command: str = typer.Argument(..., help="Shell command to check."),
    ask: str = typer.Option("on-request", "--ask", help="Approval mode."),
) -> None:
    """Check a command against the exec policy."""
    from deepseek_tui.execpolicy.command_safety import analyze_command

    result = analyze_command(command)
    typer.echo(json.dumps({
        "command": command,
        "safety_level": result.level.value,
        "reasons": result.reasons,
        "suggestions": result.suggestions,
        "ask": ask,
    }, indent=2))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Subcommand: features  (mirrors Rust Commands::Features)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.command()
def features(
    config: Path | None = CONFIG_OPTION,
    profile: str | None = PROFILE_OPTION,
) -> None:
    """Inspect feature flags."""
    loaded = _load_config(config, profile)
    feature_cfg = loaded.features
    typer.echo("Feature Flags:")
    for key, val in sorted(feature_cfg.model_dump().items()):
        status = "enabled" if val else "disabled"
        typer.echo(f"  {key}: {status}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Subcommand: init  (mirrors Rust Commands::Init)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.command()
def init() -> None:
    """Create a default AGENTS.md in the current directory."""
    target = Path.cwd() / "AGENTS.md"
    if target.exists():
        typer.echo(f"AGENTS.md already exists at {target}")
        raise typer.Exit(1)
    target.write_text(
        "# AGENTS.md\n\n"
        "Project instructions for AI assistants.\n\n"
        "## Project Type\n\n"
        "<!-- Add your project type and build commands here -->\n",
        encoding="utf-8",
    )
    typer.echo(f"Created {target}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Subcommands that are stubs (require later stages)
# Mirrors Rust: exec, review, apply, eval, sessions, resume, fork,
#               setup, mcp, completions, mcp-server, app-server,
#               metrics, update
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.command()
def exec(
    config: Path | None = CONFIG_OPTION,
    profile: str | None = PROFILE_OPTION,
    provider: str | None = PROVIDER_OPTION,
    model: str | None = MODEL_OPTION,
    prompt: str | None = typer.Option(None, "-p", "--prompt", help="Prompt text."),
) -> None:
    """Run a non-interactive single-shot agent command."""
    loaded = _load_config(config, profile, provider, model)
    text = prompt
    if text is None:
        if not sys.stdin.isatty():
            text = sys.stdin.read().strip()
        else:
            typer.echo("error: --prompt or stdin required", err=True)
            raise typer.Exit(1)
    if not text:
        typer.echo("error: empty prompt", err=True)
        raise typer.Exit(1)
    _run_one_shot(loaded, text)


@app.command()
def review(
    config: Path | None = CONFIG_OPTION,
    profile: str | None = PROFILE_OPTION,
    provider: str | None = PROVIDER_OPTION,
    model: str | None = MODEL_OPTION,
) -> None:
    """Run a DeepSeek-powered code review over a git diff."""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "diff", "HEAD"],
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        typer.echo("error: git not available or timed out", err=True)
        raise typer.Exit(1) from exc

    if result.returncode != 0 or not result.stdout.strip():
        typer.echo("No changes to review (git diff HEAD is empty).", err=True)
        raise typer.Exit(1)

    diff = result.stdout.strip()
    loaded = _load_config(config, profile, provider, model)
    prompt_text = (
        "Review the following git diff. Point out bugs, security issues, "
        "style problems, and suggest improvements. Be concise.\n\n"
        f"```diff\n{diff}\n```"
    )
    _run_one_shot(loaded, prompt_text)


@app.command()
def apply(
    patch_file: str | None = typer.Argument(None, help="Path to patch file (or stdin)."),
) -> None:
    """Apply a patch file or stdin to the working tree."""
    import subprocess

    if patch_file:
        path = Path(patch_file)
        if not path.exists():
            typer.echo(f"error: file not found: {path}", err=True)
            raise typer.Exit(1)
        patch_data = path.read_text(encoding="utf-8")
    elif not sys.stdin.isatty():
        patch_data = sys.stdin.read()
    else:
        typer.echo("error: provide a patch file or pipe patch via stdin", err=True)
        raise typer.Exit(1)

    if not patch_data.strip():
        typer.echo("error: empty patch", err=True)
        raise typer.Exit(1)

    result = subprocess.run(
        ["git", "apply", "--stat"],
        input=patch_data, capture_output=True, text=True, timeout=30,
    )
    typer.echo(result.stdout or "(no stats)")

    result = subprocess.run(
        ["git", "apply"],
        input=patch_data, capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        typer.echo(f"error: git apply failed:\n{result.stderr}", err=True)
        raise typer.Exit(1)
    typer.echo("Patch applied successfully.")


@app.command()
def sessions(
    config: Path | None = CONFIG_OPTION,
    limit: int = typer.Option(20, "--limit", help="Max sessions to show."),
) -> None:
    """List saved TUI sessions."""
    from deepseek_tui.config.paths import user_state_db_path
    from deepseek_tui.state.database import Database
    from deepseek_tui.state.session_manager import SessionManager

    async def _list() -> None:
        db_path = user_state_db_path()
        if not db_path.exists():
            typer.echo("No saved sessions.")
            return
        db = Database(db_path)
        await db.initialize()
        mgr = SessionManager(db)
        all_sessions = await mgr.list_sessions(limit=limit)
        if not all_sessions:
            typer.echo("No saved sessions.")
            return
        for s in all_sessions:
            name = getattr(s, "preview", None) or "(unnamed)"
            sid = getattr(s, "id", "?")
            ts = getattr(s, "updated_at", "")
            typer.echo(f"{sid}  {name}  {ts}")

    asyncio.run(_list())


@app.command()
def resume(
    session_id: str = typer.Argument(..., help="Session ID to resume."),
    config: Path | None = CONFIG_OPTION,
    profile: str | None = PROFILE_OPTION,
    provider: str | None = PROVIDER_OPTION,
    model: str | None = MODEL_OPTION,
) -> None:
    """Resume a saved TUI session."""
    loaded = _load_config(config, profile, provider, model)
    try:
        from deepseek_tui.tui.app import DeepSeekTUI
        tui_app = DeepSeekTUI(config=loaded, resume_session_id=session_id)
        tui_app.run()
    except ImportError as exc:
        typer.echo(f"TUI not available: {exc}", err=True)
        raise typer.Exit(1) from exc


@app.command()
def fork(
    session_id: str = typer.Argument(..., help="Session ID to fork."),
    config: Path | None = CONFIG_OPTION,
    profile: str | None = PROFILE_OPTION,
    provider: str | None = PROVIDER_OPTION,
    model: str | None = MODEL_OPTION,
) -> None:
    """Fork a saved TUI session."""
    loaded = _load_config(config, profile, provider, model)
    try:
        from deepseek_tui.tui.app import DeepSeekTUI
        tui_app = DeepSeekTUI(config=loaded, fork_session_id=session_id)
        tui_app.run()
    except ImportError as exc:
        typer.echo(f"TUI not available: {exc}", err=True)
        raise typer.Exit(1) from exc


@app.command()
def setup() -> None:
    """Bootstrap MCP config and/or skills directories."""
    from deepseek_tui.config.paths import (
        user_deepseek_dir,
        user_mcp_config_path,
        user_skills_dir,
    )
    from deepseek_tui.mcp.store import McpWriteStatus, init_config

    config_dir = user_deepseek_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    mcp_path = user_mcp_config_path()
    status = init_config(mcp_path, force=False)
    if status == McpWriteStatus.CREATED:
        typer.echo(f"Created {mcp_path}")
    elif not mcp_path.exists():
        typer.echo(f"Created {mcp_path}")
    skills_dir = user_skills_dir()
    skills_dir.mkdir(parents=True, exist_ok=True)
    typer.echo(f"Skills directory: {skills_dir}")
    typer.echo("Setup complete.")


mcp_app = typer.Typer(help="Manage MCP servers.")
app.add_typer(mcp_app, name="mcp")


def _mcp_path(config: Path | None) -> Path:
    from deepseek_tui.mcp.store import resolve_mcp_config_path

    loaded = _load_config(config)
    return resolve_mcp_config_path(loaded)


def _mcp_list(config: Path | None) -> None:
    from deepseek_tui.mcp.store import format_manager_snapshot, manager_snapshot_from_config

    path = _mcp_path(config)
    snapshot = manager_snapshot_from_config(path)
    if not snapshot.servers:
        typer.echo("No MCP servers configured.")
        typer.echo(f"Config: {path}")
        typer.echo("Run `deepseek-tui mcp init` to create a template.")
        return
    typer.echo(format_manager_snapshot(snapshot))


@mcp_app.callback(invoke_without_command=True)
def mcp_callback(
    ctx: typer.Context,
    config: Path | None = CONFIG_OPTION,
) -> None:
    if ctx.invoked_subcommand is None:
        _mcp_list(config)


@mcp_app.command("init")
def mcp_init_cmd(
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing config."),
    config: Path | None = CONFIG_OPTION,
) -> None:
    """Initialize MCP config template."""
    from deepseek_tui.mcp.store import McpWriteStatus, init_config

    path = _mcp_path(config)
    status = init_config(path, force=force)
    if status == McpWriteStatus.SKIPPED_EXISTS:
        typer.echo(f"MCP config already exists at {path} (use --force to overwrite)")
    elif status == McpWriteStatus.CREATED:
        typer.echo(f"Created MCP config at {path}")
    else:
        typer.echo(f"Overwrote MCP config at {path}")


@mcp_app.command("add")
def mcp_add_cmd(
    transport: str = typer.Argument(..., help="stdio or http"),
    name: str = typer.Argument(..., help="Server name."),
    command_or_url: str = typer.Argument(..., help="Command (stdio) or URL (http)."),
    extra_args: list[str] = typer.Argument(None, help="Extra args for stdio transport."),
    config: Path | None = CONFIG_OPTION,
) -> None:
    """Add an MCP server entry."""
    from deepseek_tui.mcp.store import add_server_config

    path = _mcp_path(config)
    transport = transport.lower()
    if transport == "stdio":
        add_server_config(
            path, name, command=command_or_url, args=list(extra_args or [])
        )
        typer.echo(f"Added MCP stdio server '{name}'")
    elif transport in {"http", "sse"}:
        add_server_config(path, name, url=command_or_url)
        typer.echo(f"Added MCP HTTP/SSE server '{name}'")
    else:
        typer.echo("Transport must be stdio or http", err=True)
        raise typer.Exit(1)


@mcp_app.command("enable")
def mcp_enable_cmd(
    name: str = typer.Argument(..., help="Server name."),
    config: Path | None = CONFIG_OPTION,
) -> None:
    from deepseek_tui.mcp.store import set_server_enabled

    set_server_enabled(_mcp_path(config), name, True)
    typer.echo(f"Enabled MCP server '{name}'")


@mcp_app.command("disable")
def mcp_disable_cmd(
    name: str = typer.Argument(..., help="Server name."),
    config: Path | None = CONFIG_OPTION,
) -> None:
    from deepseek_tui.mcp.store import set_server_enabled

    set_server_enabled(_mcp_path(config), name, False)
    typer.echo(f"Disabled MCP server '{name}'")


@mcp_app.command("remove")
def mcp_remove_cmd(
    name: str = typer.Argument(..., help="Server name."),
    config: Path | None = CONFIG_OPTION,
) -> None:
    from deepseek_tui.mcp.store import remove_server_config

    remove_server_config(_mcp_path(config), name)
    typer.echo(f"Removed MCP server '{name}'")


@mcp_app.command("validate")
def mcp_validate_cmd(
    config: Path | None = CONFIG_OPTION,
) -> None:
    """Connect to configured MCP servers and print a discovery snapshot."""
    from deepseek_tui.mcp.store import discover_manager_snapshot, format_manager_snapshot

    path = _mcp_path(config)

    async def _run() -> None:
        snapshot = await discover_manager_snapshot(path)
        typer.echo(format_manager_snapshot(snapshot))

    asyncio.run(_run())


@mcp_app.command("connect")
def mcp_connect_cmd(
    server: str | None = typer.Argument(None, help="Optional server name."),
    config: Path | None = CONFIG_OPTION,
) -> None:
    """Connect to MCP servers and report status."""
    from deepseek_tui.mcp.config import load_mcp_config
    from deepseek_tui.mcp.manager import McpManager
    from deepseek_tui.mcp.store import format_manager_snapshot, snapshot_from_configs

    path = _mcp_path(config)
    configs = load_mcp_config(path) if path.exists() else []
    if server is not None:
        configs = [cfg for cfg in configs if cfg.name == server]
        if not configs:
            typer.echo(f"MCP server '{server}' not found in {path}", err=True)
            raise typer.Exit(1)

    async def _run() -> None:
        manager = McpManager(configs, config_path=path)
        summary = await manager.start_all()
        errors = {item.server_name: item.error for item in summary.failed}
        snapshot = snapshot_from_configs(path, configs, connection_errors=errors)
        typer.echo(format_manager_snapshot(snapshot))
        await manager.stop_all()
        if summary.failed:
            raise SystemExit(1)

    asyncio.run(_run())


@mcp_app.command("tools")
def mcp_tools_cmd(
    server: str | None = typer.Argument(None, help="Optional server name."),
    config: Path | None = CONFIG_OPTION,
) -> None:
    """List tools discovered from configured MCP servers."""
    from deepseek_tui.mcp.store import discover_manager_snapshot, format_manager_snapshot

    path = _mcp_path(config)

    async def _run() -> None:
        snapshot = await discover_manager_snapshot(path)
        if server is not None:
            snapshot.servers = [s for s in snapshot.servers if s.name == server]
            if not snapshot.servers:
                typer.echo(f"MCP server '{server}' not found", err=True)
                raise SystemExit(1)
        typer.echo(format_manager_snapshot(snapshot))

    asyncio.run(_run())


@mcp_app.command("add-self")
def mcp_add_self_cmd(
    name: str = typer.Option("deepseek", "--name", help="Server name in mcp.json."),
    workspace: Path | None = typer.Option(None, "--workspace", help="Workspace root."),
    config: Path | None = CONFIG_OPTION,
) -> None:
    """Register this binary as a local MCP stdio server."""
    import shutil
    import sys

    from deepseek_tui.mcp.config import load_mcp_config
    from deepseek_tui.mcp.store import add_server_config

    path = _mcp_path(config)
    if path.exists():
        existing = {cfg.name for cfg in load_mcp_config(path)}
        if name in existing:
            typer.echo(
                f"MCP server '{name}' already exists in {path}. "
                f"Use `deepseek-tui mcp remove {name}` first.",
                err=True,
            )
            raise typer.Exit(1)

    exe = shutil.which("deepseek-tui") or sys.argv[0]
    args = ["mcp-server"]
    if workspace is not None:
        args.extend(["--workspace", str(workspace.resolve())])
    add_server_config(path, name, command=exe, args=args)
    typer.echo(f"Registered MCP server '{name}' using {exe}")


@app.command()
def completions(
    shell: str = typer.Argument("bash", help="Shell type (bash/zsh/fish)."),
) -> None:
    """Generate shell completions for deepseek-tui."""
    typer.echo(f"# Shell completions for {shell}")
    typer.echo("# Add to your shell profile:")
    if shell == "bash":
        typer.echo('eval "$(deepseek-tui --show-completion bash)"')
    elif shell == "zsh":
        typer.echo('eval "$(deepseek-tui --show-completion zsh)"')
    elif shell == "fish":
        typer.echo("deepseek-tui --show-completion fish | source")
    else:
        typer.echo(f"Unknown shell: {shell}", err=True)


_MCP_WORKSPACE_OPTION = typer.Option(
    None, "--workspace", help="Workspace root (defaults to cwd)."
)


@app.command(name="mcp-server")
def mcp_server(workspace: Path | None = _MCP_WORKSPACE_OPTION) -> None:
    """Run as MCP server mode over stdio JSON-RPC."""
    from deepseek_tui.mcp.server import run_mcp_server

    ws = (workspace or Path.cwd()).resolve()
    typer.echo(f"mcp-server: starting on stdio (workspace={ws})", err=True)
    asyncio.run(run_mcp_server(ws))


@app.command(name="app-server")
def app_server(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host."),
    port: int = typer.Option(8787, "--port", help="Bind port."),
    stdio: bool = typer.Option(False, "--stdio", help="Use stdio JSON-RPC."),
    config: Path | None = CONFIG_OPTION,
) -> None:
    """Run the app-server transport (alias for serve)."""
    from deepseek_tui.app_server import AppServerOptions, run_http, run_stdio

    loaded = _load_config(config)
    if stdio:
        asyncio.run(run_stdio(config=loaded))
        return
    options = AppServerOptions(host=host, port=port, config_path=config)
    asyncio.run(run_http(options, config=loaded))


@app.command()
def metrics(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
    since: str | None = typer.Option(None, "--since", help="Duration filter (e.g. 7d, 24h)."),
    config: Path | None = CONFIG_OPTION,
) -> None:
    """Print a usage rollup from the audit log."""
    from deepseek_tui.config.paths import user_state_db_path
    from deepseek_tui.state.database import Database
    from deepseek_tui.state.session_manager import SessionManager

    async def _metrics() -> None:
        db_path = user_state_db_path()
        if not db_path.exists():
            total_sessions = 0
        else:
            db = Database(db_path)
            await db.initialize()
            mgr = SessionManager(db)
            all_sessions = await mgr.list_sessions(include_archived=True)
            total_sessions = len(all_sessions)
        data = {
            "total_sessions": total_sessions,
            "period": since or "all-time",
        }
        if json_output:
            typer.echo(json.dumps(data, indent=2))
        else:
            typer.echo("DeepSeek TUI Metrics")
            typer.echo(f"  Total sessions: {total_sessions}")
            typer.echo(f"  Period: {since or 'all-time'}")

    asyncio.run(_metrics())


@app.command()
def update() -> None:
    """Check for and apply updates."""
    typer.echo("update — self-update not applicable for pip-installed Python package.")
    typer.echo("Use: pip install --upgrade deepseek-tui-py")
