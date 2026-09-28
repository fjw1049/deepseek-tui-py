"""CLI entry point.

Subcommands + global flags, using typer (Python equivalent of clap).
Passthrough subcommands (doctor/resume/fork/init/setup/exec/review/apply/
mcp/features) become direct calls into the corresponding Python modules
rather than spawning a sibling binary.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import typer
from click import get_current_context

from deepseek_tui.config.loader import ConfigLoader
from deepseek_tui.config.models import Config

# ── Global Typer app ─────────────────────────────────────────────────────

app = typer.Typer(
    name="deepseek-tui",
    add_completion=True,
    no_args_is_help=False,
    help="DeepSeek TUI — terminal AI agent (Python edition).",
)

# ── Global flags ─────────────────────────────────────────────────────────

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
    options = _global_options()
    overrides = {key: options[key] for key in (
        "api_key", "base_url", "approval_policy", "sandbox_mode"
    ) if options.get(key) is not None}
    logging_options = {key: options[source] for key, source in (
        ("level", "log_level"), ("dir", "log_dir"), ("console", "log_console")
    ) if options.get(source) is not None}
    if logging_options:
        overrides["logging"] = logging_options
    return ConfigLoader().load(
        config_path=config or options.get("config"),
        profile_name=profile or options.get("profile"),
        provider=provider or options.get("provider"),
        model=model or options.get("model"),
        overrides=overrides,
    )


def _global_options() -> dict[str, Any]:
    ctx = get_current_context(silent=True)
    return (ctx.find_root().obj or {}) if ctx is not None else {}



# ── @app.callback: default action (no subcommand → launch TUI) ──────────

# 主要功能：CLI 默认入口。解析全局 flags，无子命令时启动 TUI；带 -p 走 one-shot
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

    if output_mode not in (None, "text"):
        raise typer.BadParameter("Only --output-mode text is supported")
    ctx.obj = {
        "config": config, "profile": profile, "provider": provider, "model": model,
        "api_key": api_key, "base_url": base_url, "approval_policy": approval_policy,
        "sandbox_mode": sandbox_mode, "log_level": log_level, "log_dir": log_dir,
        "log_console": True if log_console else None,
    }
    if ctx.invoked_subcommand is not None:
        return

    # 合并配置（默认→config.toml→profile→环境变量→命令行覆盖），产出生效 Config
    loaded = _load_config(config, profile, provider, model)

    # Wire the rotating log handlers up before any subsystem runs so the
    # very first INFO event ("engine starting") lands in the file.
    from deepseek_tui.config.layout import ensure_user_home_layout
    from deepseek_tui.utils import setup_logging

    ensure_user_home_layout()

    # 装配按小时滚动的日志 handler（须在子系统启动前，确保首条 INFO 落盘）
    setup_logging(
        loaded,
        level_override=log_level,
        dir_override=log_dir,
        console_override=log_console if log_console else None,
    )

    from deepseek_tui.tools.runtime import prune_older_than

    # 清理过期的 spillover 溢出文件（超大工具输出落盘后的残留），non-fatal
    prune_older_than()

    if prompt is not None:
        _run_one_shot(loaded, prompt)
        return

    _launch_tui(loaded)


def _launch_tui(config: Config) -> None:
    """Start the Textual TUI app with a fully wired Engine."""
    try:
        from deepseek_tui.tui.app import DeepSeekTUI
        tui_app = DeepSeekTUI(config=config)
        # 启动 Textual 事件循环（阻塞）：compose 搭 UI → on_mount 装技能/画状态栏/后台起引擎 → 进消息循环
        tui_app.run()
    except ImportError as exc:
        typer.echo("TUI not available — textual not installed.", err=True)
        raise typer.Exit(1) from exc


def _run_one_shot(config: Config, prompt: str) -> None:
    """Non-interactive single-shot execution."""
    asyncio.run(_run_one_shot_async(config, prompt))


async def _run_one_shot_async(config: Config, prompt: str) -> None:
    """Async implementation of one-shot mode."""
    from deepseek_tui.client.factory import build_llm_client
    from deepseek_tui.engine.events import (
        ErrorEvent,
        TextDeltaEvent,
        ToolCallEvent,
        ToolResultEvent,
        TurnCompleteEvent,
    )
    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.engine.orchestrator import Engine

    client = build_llm_client(config)
    handle = EngineHandle()
    from deepseek_tui.tools.runtime import default_runtime_model

    try:
        engine = await Engine.create(
            handle, client, config=config, default_model=default_runtime_model(config)
        )
    except BaseException:
        await client.close()
        raise
    engine_task = asyncio.create_task(engine.run())
    next_event = None
    try:
        await handle.send_message(prompt)
        events = handle.events().__aiter__()
        while True:
            next_event = asyncio.create_task(events.__anext__())
            done, _ = await asyncio.wait(
                (next_event, engine_task), return_when=asyncio.FIRST_COMPLETED
            )
            if engine_task in done:
                engine_task.result()  # Propagate a crash even if an event raced with it.
                if next_event not in done:
                    raise RuntimeError("Engine stopped before completing the turn")
            try:
                event = next_event.result()
            except StopAsyncIteration as exc:
                raise RuntimeError("Event stream closed before completing the turn") from exc
            if isinstance(event, TextDeltaEvent):
                print(event.text, end="", flush=True)
            elif isinstance(event, ToolCallEvent):
                typer.echo(f"\n[tool: {event.tool_call.name}]", err=True)
            elif isinstance(event, ToolResultEvent):
                status = "ok" if event.success else "error"
                typer.echo(f"[tool result: {status}]", err=True)
            elif isinstance(event, ErrorEvent):
                typer.echo(f"\nError: {event.message}", err=True)
                raise typer.Exit(1)
            elif isinstance(event, TurnCompleteEvent):
                if not event.success:
                    typer.echo(event.error_message or "Turn failed", err=True)
                    raise typer.Exit(1)
                print()
                return
    finally:
        tasks = [engine_task] + ([next_event] if next_event is not None else [])
        for task in tasks:
            task.cancel()
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            await engine.shutdown()  # Engine owns the client after successful construction.


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Subcommand: version
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.command()
def version() -> None:
    """Print the version string."""
    typer.echo("deepseek-tui-py 0.1.0")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Subcommand: doctor
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
    from deepseek_tui.tools.runtime import default_runtime_model

    typer.echo(f"  model: {default_runtime_model(loaded)}")
    from deepseek_tui.config.paths import user_config_path
    typer.echo(f"  config path: {user_config_path()}")

    api_key = loaded.api_key or loaded.effective_provider_config().api_key
    typer.echo(f"  api_key: {'set' if api_key else 'NOT SET'}")

    git_path = shutil.which("git")
    typer.echo(f"  git: {git_path or 'NOT FOUND'}")

    typer.echo("  status: OK" if api_key else "  status: MISSING API KEY")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Subcommand: serve
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _is_loopback_host(host: str) -> bool:
    """True for 127.0.0.0/8, ::1, and ``localhost``."""
    h = host.strip().lower().strip("[]")
    if h == "localhost":
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host for HTTP."),
    port: int | None = typer.Option(
        None,
        "--port",
        help="Bind port (default 7878 with --http, else 8787).",
    ),
    stdio: bool = typer.Option(
        False, "--stdio", help="Speak newline-delimited JSON-RPC on stdin/stdout."
    ),
    http: bool = typer.Option(
        False,
        "--http",
        help="Workbench runtime API mode (bare JSON + SSE for DeepSeek GUI).",
    ),
    auth_token: str | None = typer.Option(
        None, "--auth-token", help="Bearer token for /v1/* routes."
    ),
    insecure: bool = typer.Option(
        False,
        "--insecure",
        help="Disable /v1 auth (local dev only; GUI passes this when no token set).",
    ),
    cors_origin: list[str] = typer.Option(
        [],
        "--cors-origin",
        help="Allowed CORS origin for direct renderer access (repeatable).",
    ),
    config: Path | None = CONFIG_OPTION,
    profile: str | None = PROFILE_OPTION,
    provider: str | None = PROVIDER_OPTION,
    model: str | None = MODEL_OPTION,
) -> None:
    """Start the app-server (HTTP by default; --stdio for JSON-RPC pipe)."""
    from deepseek_tui.server import AppServerOptions, run_http, run_stdio

    if insecure and not _is_loopback_host(host):
        typer.echo(
            f"Refusing to start: --insecure disables all auth, but --host "
            f"{host!r} is not a loopback address. Bind to 127.0.0.1 or pass "
            "--auth-token instead.",
            err=True,
        )
        raise typer.Exit(1)

    loaded = _load_config(config, profile, provider, model)
    if stdio:
        typer.echo("app-server: stdio JSON-RPC mode", err=True)
        asyncio.run(run_stdio(config=loaded))
        return
    effective_port = port if port is not None else (7878 if http else 8787)
    typer.echo(
        f"app-server listening on http://{host}:{effective_port}"
        + (" (runtime API)" if http else ""),
        err=True,
    )
    options = AppServerOptions(
        host=host,
        port=effective_port,
        config_path=config,
        http_mode=http,
        auth_token=auth_token,
        insecure_no_auth=insecure,
        cors_origins=cors_origin or None,
    )
    asyncio.run(run_http(options, config=loaded))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Subcommand group: auth
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

auth_app = typer.Typer(help="Manage authentication credentials and provider keys.")
app.add_typer(auth_app, name="auth")

def _provider_config_has_key(config: Config, provider_name: str) -> bool:
    """Check if a provider has an API key in the config file."""
    prov_cfg = config.providers.get(provider_name)
    if prov_cfg is not None and prov_cfg.api_key:
        return True
    if provider_name == config.provider and config.api_key:
        return True
    return False


@auth_app.command("status")
def auth_status(
    config: Path | None = CONFIG_OPTION,
    profile: str | None = PROFILE_OPTION,
) -> None:
    """Show current provider and auth state for all providers."""
    from deepseek_tui.state.secrets import credential_providers, env_for

    loaded = _load_config(config, profile)
    typer.echo(f"provider: {loaded.provider}")
    for prov in credential_providers(loaded):
        env_set = env_for(prov) is not None
        file_set = _provider_config_has_key(loaded, prov)
        typer.echo(f"{prov} auth: env={env_set}, config={file_set}")


@auth_app.command("set")
def auth_set(
    provider: str = typer.Option(..., "--provider", help="Provider name."),
    api_key: str | None = typer.Option(None, "--api-key", help="API key value."),
    api_key_stdin: bool = typer.Option(False, "--api-key-stdin", help="Read key from stdin."),
) -> None:
    """Save a provider API key to config.toml."""
    if api_key is not None:
        key = api_key
    elif api_key_stdin:
        key = sys.stdin.read().strip()
    else:
        key = typer.prompt(f"Enter API key for {provider}", hide_input=True)
    if not key:
        typer.echo("error: empty API key provided", err=True)
        raise typer.Exit(1)
    from deepseek_tui.state.secrets import write_api_key

    path = write_api_key(provider, key)
    typer.echo(f"saved API key for {provider} to {path}")


@auth_app.command("get")
def auth_get(
    provider: str = typer.Option(..., "--provider", help="Provider name."),
    config: Path | None = CONFIG_OPTION,
    profile: str | None = PROFILE_OPTION,
) -> None:
    """Report whether a provider has a key configured (never prints the value)."""
    loaded = _load_config(config, profile)
    from deepseek_tui.state.secrets import env_for as _env_for

    in_env = _env_for(provider) is not None
    in_file = _provider_config_has_key(loaded, provider)
    resolved = in_env or in_file
    if resolved:
        source = "env" if in_env else "config-file"
        typer.echo(f"{provider}: set (source: {source})")
    else:
        typer.echo(f"{provider}: not set")


@auth_app.command("clear")
def auth_clear(
    provider: str = typer.Option(..., "--provider", help="Provider name."),
) -> None:
    """Delete a provider's key from config.toml."""
    from deepseek_tui.state.secrets import write_api_key

    write_api_key(provider, None)
    typer.echo(f"cleared API key for {provider}")


@auth_app.command("list")
def auth_list(
    config: Path | None = CONFIG_OPTION,
    profile: str | None = PROFILE_OPTION,
) -> None:
    """List all known providers with their auth state."""
    loaded = _load_config(config, profile)
    from deepseek_tui.state.secrets import credential_providers
    from deepseek_tui.state.secrets import env_for as _env_for

    typer.echo("provider     env  config")
    for prov in credential_providers(loaded):
        env = "yes" if _env_for(prov) is not None else "no "
        file = "yes" if _provider_config_has_key(loaded, prov) else "no "
        typer.echo(f"{prov:<12}  {env}     {file}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Subcommand group: config
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

config_app = typer.Typer(help="Read/write/list config values.")
app.add_typer(config_app, name="config")


@config_app.command("get")
def config_get(
    key: str = typer.Argument(..., help="Config key to read."),
    config: Path | None = CONFIG_OPTION,
    profile: str | None = PROFILE_OPTION,
    show_secrets: bool = typer.Option(False, "--show-secrets", help="Reveal this value explicitly."),
) -> None:
    """Get a single config value."""
    loaded = _load_config(config, profile)
    value = _config_get_value(loaded, key, show_secrets=show_secrets)
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
    from deepseek_tui.state.secrets import write_config_value

    options = _global_options()
    config = config or options.get("config")
    profile = profile or options.get("profile")
    if profile:
        if not profile.replace("_", "").replace("-", "").isalnum():
            raise typer.BadParameter("Profile name must contain letters, digits, '_' or '-'")
    if key == "api_key":
        from deepseek_tui.state.secrets import write_active_api_key, write_profile_api_key

        try:
            path = (write_profile_api_key(profile, value, path=config) if profile
                    else write_active_api_key(value, path=config))
        except ValueError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(1) from exc
        typer.echo(f"set api_key in {path}")
        return
    if profile:
        key = f"profiles.{profile}.{key}"
    try:
        path = write_config_value(key, value, path=config)
    except ValueError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"set {key} in {path}")


@config_app.command("unset")
def config_unset(
    key: str = typer.Argument(..., help="Config key to remove."),
    config: Path | None = CONFIG_OPTION,
    profile: str | None = PROFILE_OPTION,
) -> None:
    """Remove a config key (writes to config.toml)."""
    from deepseek_tui.state.secrets import write_config_value

    options = _global_options()
    config = config or options.get("config")
    profile = profile or options.get("profile")
    if profile:
        if not profile.replace("_", "").replace("-", "").isalnum():
            raise typer.BadParameter("Profile name must contain letters, digits, '_' or '-'")
    if key == "api_key":
        from deepseek_tui.state.secrets import write_active_api_key, write_profile_api_key

        path = (write_profile_api_key(profile, None, path=config) if profile
                else write_active_api_key(None, path=config))
        typer.echo(f"unset api_key from {path}")
        return
    if profile:
        key = f"profiles.{profile}.{key}"
    try:
        path = write_config_value(key, None, path=config)
    except ValueError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"unset {key} from {path}")


@config_app.command("list")
def config_list(
    config: Path | None = CONFIG_OPTION,
    profile: str | None = PROFILE_OPTION,
) -> None:
    """List all config key-value pairs."""
    loaded = _load_config(config, profile)
    for key, val in sorted(_redacted_config(loaded).items()):
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
    typer.echo(json.dumps(_redacted_config(loaded), indent=2))


def _redacted_config(config: Config, *, show_secrets: bool = False) -> dict[str, Any]:
    def redact(value: Any, key: str = "") -> Any:
        sensitive = key.lower() in {
            "extra_headers", "extra_body", "webhook_urls", "password", "secret", "token"
        } or key.lower().endswith(("_key", "_password", "_secret", "_token"))
        if sensitive and value not in (None, "", {}, []):
            return "[REDACTED]"
        if isinstance(value, dict):
            return {k: redact(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [redact(item) for item in value]
        return value

    values = config.model_dump(mode="json", exclude_none=True)
    return values if show_secrets else redact(values)


def _config_get_value(config: Config, key: str, *, show_secrets: bool = False) -> str | None:
    obj: Any = _redacted_config(config, show_secrets=show_secrets)
    for part in key.split("."):
        if not isinstance(obj, dict) or part not in obj:
            return None
        obj = obj[part]
    return None if obj is None else str(obj)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Subcommand group: model
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

model_app = typer.Typer(help="Resolve or list available models across providers.")
app.add_typer(model_app, name="model")


@model_app.command("list")
def model_list(
    provider: str | None = typer.Option(None, "--provider", help="Filter by provider."),
) -> None:
    """List all models in the provider registry."""
    from deepseek_tui.config.providers import PROVIDER_DEFAULTS

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
    from deepseek_tui.config.providers import PROVIDER_DEFAULTS
    from deepseek_tui.config.routing import config_for_model

    loaded = _load_config(provider=provider)
    selected_provider = provider
    if model_name and "::" not in model_name and not provider:
        for name, defaults in PROVIDER_DEFAULTS.items():
            if model_name in {defaults.model, defaults.flash_model}:
                selected_provider = name
                break
    resolved = config_for_model(loaded, model_name, provider=selected_provider)
    typer.echo(f"requested: {model_name or ''}")
    typer.echo(f"resolved: {resolved.effective_provider_config().model}")
    typer.echo(f"provider: {resolved.provider}")
    typer.echo(f"used_fallback: {model_name is None}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Subcommand group: thread
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

thread_app = typer.Typer(help="Manage thread/session metadata.")
app.add_typer(thread_app, name="thread")


def _thread_store() -> Any:
    from deepseek_tui.config.paths import user_threads_dir
    from deepseek_tui.server.threads.store import RuntimeThreadStore

    return RuntimeThreadStore(user_threads_dir())


def _load_thread_or_exit(thread_id: str) -> Any:
    try:
        return _thread_store().load_thread(thread_id)
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


@thread_app.command("list")
def thread_list(
    all_threads: bool = typer.Option(False, "--all", help="Include archived threads."),
    limit: int | None = typer.Option(20, "--limit", help="Max threads to show."),
) -> None:
    """List saved threads."""
    threads = [t for t in _thread_store().list_threads() if all_threads or not t.archived]
    if limit is not None:
        threads = threads[:limit]
    if not threads:
        typer.echo("No saved threads.")
        return
    for thread in threads:
        label = thread.title or Path(thread.workspace).name or "(unnamed)"
        tag = " [archived]" if thread.archived else ""
        typer.echo(f"{thread.id}  {label}{tag}  {thread.updated_at.isoformat()}")


@thread_app.command("read")
def thread_read(
    thread_id: str = typer.Argument(..., help="Thread ID to read."),
) -> None:
    """Read a thread's metadata as JSON."""
    thread = _load_thread_or_exit(thread_id)
    typer.echo(json.dumps(thread.model_dump(mode="json"), indent=2))


def _update_thread_metadata(thread_id: str, **changes: Any) -> None:
    from deepseek_tui.workspace.project_lease import ThreadLease

    lease = ThreadLease(thread_id)
    if not lease.acquire_blocking(nonblocking=True):
        typer.echo("Thread is in use; retry after its runtime releases it", err=True)
        raise typer.Exit(1)
    try:
        store = _thread_store()
        try:
            thread = store.load_thread(thread_id)
        except FileNotFoundError as exc:
            typer.echo(f"Thread not found: {thread_id}", err=True)
            raise typer.Exit(1) from exc
        for name, value in changes.items():
            setattr(thread, name, value)
        thread.updated_at = datetime.now(timezone.utc)
        store.save_thread(thread)
    finally:
        lease.release()


@thread_app.command("archive")
def thread_archive(
    thread_id: str = typer.Argument(..., help="Thread ID to archive."),
) -> None:
    """Archive a thread."""
    _update_thread_metadata(thread_id, archived=True)
    typer.echo(f"Archived {thread_id}")


@thread_app.command("unarchive")
def thread_unarchive(
    thread_id: str = typer.Argument(..., help="Thread ID to unarchive."),
) -> None:
    """Unarchive a thread."""
    _update_thread_metadata(thread_id, archived=False)
    typer.echo(f"Unarchived {thread_id}")


@thread_app.command("set-name")
def thread_set_name(
    thread_id: str = typer.Argument(..., help="Thread ID."),
    name: str = typer.Argument(..., help="New thread name."),
) -> None:
    """Rename a thread."""
    _update_thread_metadata(thread_id, title=name)
    typer.echo(f"Renamed {thread_id} to {name!r}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Subcommand: sandbox
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

sandbox_app = typer.Typer(help="Evaluate sandbox/approval policy decisions.")
app.add_typer(sandbox_app, name="sandbox")


@sandbox_app.command("check")
def sandbox_check(
    command: str = typer.Argument(..., help="Shell command to check."),
    ask: str | None = typer.Option(None, "--ask", help="Unsupported: this is a safety heuristic."),
) -> None:
    """Inspect command safety heuristics, without evaluating runtime approval policy."""
    from deepseek_tui.policy.command_safety import analyze_command

    if ask is not None:
        raise typer.BadParameter("--ask is unsupported; this command only checks safety heuristics")
    result = analyze_command(command)
    typer.echo(json.dumps({
        "command": command,
        "safety_level": result.level.value,
        "reasons": result.reasons,
        "suggestions": result.suggestions,
        "scope": "command-safety-heuristic",
    }, indent=2))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Subcommand: features
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
# Subcommand: init
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
def resume(
    session_id: str = typer.Argument(..., help="Canonical thread ID to resume."),
    config: Path | None = CONFIG_OPTION,
    profile: str | None = PROFILE_OPTION,
    provider: str | None = PROVIDER_OPTION,
    model: str | None = MODEL_OPTION,
) -> None:
    """Resume a canonical thread in the TUI."""
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
    session_id: str = typer.Argument(..., help="Canonical thread ID to fork."),
    config: Path | None = CONFIG_OPTION,
    profile: str | None = PROFILE_OPTION,
    provider: str | None = PROVIDER_OPTION,
    model: str | None = MODEL_OPTION,
) -> None:
    """Fork a canonical thread into a new TUI thread."""
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
    from deepseek_tui.mcp.actions import format_status

    path = _mcp_path(config)
    text = format_status(path)
    if "No MCP servers configured." in text:
        typer.echo("No MCP servers configured.")
        typer.echo(f"Config: {path}")
        typer.echo("Run `deepseek-tui mcp init` to create a template.")
        return
    typer.echo(text)


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
    from deepseek_tui.mcp.actions import run_init

    typer.echo(run_init(_mcp_path(config), force=force).message)


@mcp_app.command("add")
def mcp_add_cmd(
    transport: str = typer.Argument(..., help="stdio or http"),
    name: str = typer.Argument(..., help="Server name."),
    command_or_url: str = typer.Argument(..., help="Command (stdio) or URL (http)."),
    extra_args: list[str] = typer.Argument(None, help="Extra args for stdio transport."),
    config: Path | None = CONFIG_OPTION,
) -> None:
    """Add an MCP server entry."""
    from deepseek_tui.mcp.actions import run_add

    path = _mcp_path(config)
    args = [transport.lower(), name, command_or_url]
    if extra_args:
        args.extend(extra_args)
    try:
        result = run_add(path, transport.lower(), args, restart_required=False)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(result.message)


@mcp_app.command("enable")
def mcp_enable_cmd(
    name: str = typer.Argument(..., help="Server name."),
    config: Path | None = CONFIG_OPTION,
) -> None:
    from deepseek_tui.mcp.actions import run_enable

    run_enable(_mcp_path(config), name, restart_required=False)
    typer.echo(f"Enabled MCP server '{name}'")


@mcp_app.command("disable")
def mcp_disable_cmd(
    name: str = typer.Argument(..., help="Server name."),
    config: Path | None = CONFIG_OPTION,
) -> None:
    from deepseek_tui.mcp.actions import run_disable

    run_disable(_mcp_path(config), name, restart_required=False)
    typer.echo(f"Disabled MCP server '{name}'")


@mcp_app.command("remove")
def mcp_remove_cmd(
    name: str = typer.Argument(..., help="Server name."),
    config: Path | None = CONFIG_OPTION,
) -> None:
    from deepseek_tui.mcp.actions import run_remove

    run_remove(_mcp_path(config), name, restart_required=False)
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
        try:
            summary = await manager.start_all()
            errors = {item.server_name: item.error for item in summary.failed}
            snapshot = snapshot_from_configs(path, configs, connection_errors=errors)
            typer.echo(format_manager_snapshot(snapshot))
            if summary.failed:
                raise typer.Exit(1)
        finally:
            await manager.stop_all()

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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Subcommand group: plugin
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

plugin_app = typer.Typer(help="Manage plugins (skills/hooks/MCP bundles).")
app.add_typer(plugin_app, name="plugin")

_PLUGIN_PROJECT_OPTION = typer.Option(
    False,
    "--project",
    help="Target the project scope (<cwd>/.deepseek/plugins) instead of user scope.",
)


def _plugins_dir(project: bool) -> Path:
    from deepseek_tui.integrations.plugins import project_plugins_dir, user_plugins_dir

    return project_plugins_dir() if project else user_plugins_dir()


def _plugin_list() -> None:
    from deepseek_tui.integrations.plugins import discover_plugins

    plugins = discover_plugins(workspace=Path.cwd(), include_disabled=True)
    if not plugins:
        typer.echo("No plugins installed.")
        typer.echo("Install one with `deepseek-tui plugin install <github:owner/repo|path>`.")
        return
    for p in plugins:
        flags: list[str] = [p.scope]
        if not p.enabled:
            flags.append("disabled")
        if p.trusted:
            flags.append("trusted")
        components: list[str] = []
        if p.manifest.skills:
            components.append("skills")
        if p.manifest.commands:
            components.append("commands")
        if p.manifest.agents:
            components.append("agents")
        if p.manifest.rules:
            components.append("rules")
        if p.manifest.hooks:
            components.append("hooks")
        if p.manifest.mcp_servers:
            components.append("mcp")
        comp = f" [{', '.join(components)}]" if components else ""
        perms = (
            f" perms={','.join(p.manifest.permissions)}"
            if p.manifest.permissions
            else ""
        )
        desc = f" — {p.manifest.description}" if p.manifest.description else ""
        typer.echo(
            f"{p.name} v{p.manifest.version} ({', '.join(flags)}){comp}{perms}{desc}"
        )


@plugin_app.callback(invoke_without_command=True)
def plugin_callback(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        _plugin_list()


@plugin_app.command("list")
def plugin_list_cmd() -> None:
    """List installed plugins across scopes."""
    _plugin_list()


@plugin_app.command("install")
def plugin_install_cmd(
    spec: str = typer.Argument(
        ...,
        help="Source: github:owner/repo, local path, npm:pkg[@ver], or <plugin>@<marketplace>.",
    ),
    trust: bool = typer.Option(
        False, "--trust", help="Trust immediately (activates hooks/MCP servers)."
    ),
    plugin_id: str | None = typer.Option(
        None,
        "--plugin",
        help="Plugin id to select when the source contains multiple plugins.",
    ),
    candidate_root: str | None = typer.Option(
        None,
        "--candidate",
        help="Exact relative package root used to disambiguate duplicate plugin ids.",
    ),
    project: bool = _PLUGIN_PROJECT_OPTION,
) -> None:
    """Install a plugin from GitHub, local path, marketplace, or npm:<pkg>."""
    from deepseek_tui.plugins import InstallPlugin, PluginHost

    result = PluginHost().apply(
        InstallPlugin(
            source=spec,
            plugins_dir=_plugins_dir(project),
            trust=trust,
            plugin_id=plugin_id,
            candidate_root=candidate_root,
        )
    )
    typer.echo(result.message)
    if result.outcome == "failed":
        raise typer.Exit(1)


@plugin_app.command("migrate")
def plugin_migrate_cmd(
    project: bool = _PLUGIN_PROJECT_OPTION,
) -> None:
    """Migrate CodeBuddy-format plugins to the canonical layout.

    Moves .codebuddy-plugin/plugin.json to .deepseek-plugin/, converts
    agentName/expertType into settings.json defaultAgent, rewrites
    CODEBUDDY_* hook tokens, rebuilds indexes, prunes dead lockfile
    entries, and re-binds trust grants.
    """
    from deepseek_tui.integrations.plugins import migrate_codebuddy_plugins

    for line in migrate_codebuddy_plugins(plugins_dir=_plugins_dir(project)):
        typer.echo(line)


@plugin_app.command("new")
def plugin_new_cmd(
    name: str = typer.Argument(..., help="Plugin name (lowercase kebab-case)."),
    directory: Path = typer.Option(
        Path("."), "--dir", help="Parent directory for the new plugin."
    ),
) -> None:
    """Scaffold a new plugin in the canonical Claude Code layout."""
    from deepseek_tui.integrations.plugins import scaffold_plugin
    from deepseek_tui.integrations.skills import InstallOutcome

    outcome, message = scaffold_plugin(name, directory.expanduser())
    typer.echo(message)
    if outcome == InstallOutcome.FAILED:
        raise typer.Exit(1)


# ── plugin marketplace … ─────────────────────────────────────────────────

marketplace_app = typer.Typer(
    help="Register plugin marketplaces (repos advertising many plugins)."
)
plugin_app.add_typer(marketplace_app, name="marketplace")


@marketplace_app.callback(invoke_without_command=True)
def marketplace_callback(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        _marketplace_list()


def _marketplace_list() -> None:
    from deepseek_tui.integrations.plugins import load_marketplace, read_marketplaces

    table = read_marketplaces()
    if not table:
        typer.echo("No marketplaces registered.")
        typer.echo(
            "Add one with `deepseek-tui plugin marketplace add "
            "<github:owner/repo|path>`."
        )
        return
    for name, entry in sorted(table.items()):
        path = Path(str(entry.get("path", "")))
        try:
            count = len(load_marketplace(path))
        except (FileNotFoundError, OSError, ValueError):
            count = 0
        typer.echo(f"{name} ({entry.get('source', '?')}) — {count} plugins")


@marketplace_app.command("add")
def marketplace_add_cmd(
    spec: str = typer.Argument(..., help="Source: github:owner/repo or local path."),
) -> None:
    """Register a marketplace (downloads GitHub repos, references local ones)."""
    from deepseek_tui.integrations.plugins import add_marketplace
    from deepseek_tui.integrations.skills import InstallOutcome

    outcome, message = add_marketplace(spec)
    typer.echo(message)
    if outcome == InstallOutcome.FAILED:
        raise typer.Exit(1)


@marketplace_app.command("list")
def marketplace_list_cmd() -> None:
    """List registered marketplaces."""
    _marketplace_list()


@marketplace_app.command("remove")
def marketplace_remove_cmd(
    name: str = typer.Argument(..., help="Marketplace name."),
) -> None:
    """Unregister a marketplace (deletes its downloaded copy)."""
    from deepseek_tui.integrations.plugins import remove_marketplace

    typer.echo(remove_marketplace(name))


@marketplace_app.command("update")
def marketplace_update_cmd(
    name: str = typer.Argument(..., help="Marketplace name."),
) -> None:
    """Refresh a GitHub marketplace's downloaded copy."""
    from deepseek_tui.integrations.plugins import update_marketplace
    from deepseek_tui.integrations.skills import InstallOutcome

    outcome, message = update_marketplace(name)
    typer.echo(message)
    if outcome == InstallOutcome.FAILED:
        raise typer.Exit(1)


@marketplace_app.command("plugins")
def marketplace_plugins_cmd(
    name: str = typer.Argument(..., help="Marketplace name."),
) -> None:
    """List the plugins a registered marketplace advertises."""
    from deepseek_tui.integrations.plugins import load_marketplace, read_marketplaces

    entry = read_marketplaces().get(name)
    if entry is None:
        typer.echo(f"Marketplace not found: {name}")
        raise typer.Exit(1)
    try:
        entries = load_marketplace(Path(str(entry.get("path", ""))))
    except FileNotFoundError:
        typer.echo(f"Marketplace {name} has no marketplace.json anymore")
        raise typer.Exit(1) from None
    for e in entries:
        cat = f" [{e.category}]" if e.category else ""
        desc = f" — {e.description}" if e.description else ""
        typer.echo(f"{e.name}{cat}{desc}")
        typer.echo(f"  install: deepseek-tui plugin install {e.name}@{name}")


@plugin_app.command("remove")
def plugin_remove_cmd(
    name: str = typer.Argument(..., help="Plugin name."),
    project: bool = _PLUGIN_PROJECT_OPTION,
) -> None:
    """Uninstall a plugin."""
    from deepseek_tui.plugins import PluginHost, RemovePlugin

    result = PluginHost().apply(RemovePlugin(name, _plugins_dir(project)))
    typer.echo(result.message)
    if result.outcome == "failed":
        raise typer.Exit(1)


@plugin_app.command("update")
def plugin_update_cmd(
    name: str = typer.Argument(..., help="Plugin name."),
    project: bool = _PLUGIN_PROJECT_OPTION,
) -> None:
    """Re-install a plugin from its recorded source."""
    from deepseek_tui.plugins import PluginHost, UpdatePlugin

    result = PluginHost().apply(UpdatePlugin(name, _plugins_dir(project)))
    typer.echo(result.message)
    if result.outcome == "failed":
        raise typer.Exit(1)


@plugin_app.command("enable")
def plugin_enable_cmd(
    name: str = typer.Argument(..., help="Plugin name."),
    project: bool = _PLUGIN_PROJECT_OPTION,
) -> None:
    from deepseek_tui.plugins import EnablePlugin, PluginHost

    result = PluginHost().apply(EnablePlugin(name, True, _plugins_dir(project)))
    typer.echo(result.message)
    if result.outcome == "failed":
        raise typer.Exit(1)


@plugin_app.command("disable")
def plugin_disable_cmd(
    name: str = typer.Argument(..., help="Plugin name."),
    project: bool = _PLUGIN_PROJECT_OPTION,
) -> None:
    from deepseek_tui.plugins import EnablePlugin, PluginHost

    result = PluginHost().apply(EnablePlugin(name, False, _plugins_dir(project)))
    typer.echo(result.message)
    if result.outcome == "failed":
        raise typer.Exit(1)


@plugin_app.command("trust")
def plugin_trust_cmd(
    name: str = typer.Argument(..., help="Plugin name."),
    project: bool = _PLUGIN_PROJECT_OPTION,
) -> None:
    """Trust a plugin — hooks/MCP activate on the next session.

    Trust allows arbitrary shell hooks and MCP processes under your user
    account; only trust plugins you have reviewed.
    """
    from deepseek_tui.plugins import PluginHost, TrustPlugin

    result = PluginHost().apply(TrustPlugin(name, True, _plugins_dir(project)))
    typer.echo(result.message)
    if result.outcome == "failed":
        raise typer.Exit(1)


@plugin_app.command("untrust")
def plugin_untrust_cmd(
    name: str = typer.Argument(..., help="Plugin name."),
    project: bool = _PLUGIN_PROJECT_OPTION,
) -> None:
    """Revoke trust — deactivates the plugin's hooks and MCP servers."""
    from deepseek_tui.plugins import PluginHost, TrustPlugin

    result = PluginHost().apply(TrustPlugin(name, False, _plugins_dir(project)))
    typer.echo(result.message)
    if result.outcome == "failed":
        raise typer.Exit(1)


@plugin_app.command("grant")
def plugin_grant_cmd(
    name: str = typer.Argument(..., help="Plugin name."),
    digest: str = typer.Option(
        "",
        "--digest",
        help="Store content digest to bind (default: sha256 of the installed copy).",
    ),
    project: bool = _PLUGIN_PROJECT_OPTION,
) -> None:
    """Grant digest-bound execution capabilities (hooks/MCP/sidecar)."""
    from deepseek_tui.integrations.plugins import resolve_plugin_dir, user_plugins_dir
    from deepseek_tui.plugins import GrantPlugin, PluginHost
    from deepseek_tui.plugins.identity import source_content_digest

    plugins_dir = _plugins_dir(project)
    bound = digest.strip()
    if not bound:
        resolved = resolve_plugin_dir(name, plugins_dir or user_plugins_dir())
        if resolved is None:
            typer.echo(f"Plugin not found: {name}")
            raise typer.Exit(1)
        bound = source_content_digest(resolved)
    result = PluginHost().apply(GrantPlugin(name, bound, plugins_dir))
    typer.echo(result.message)
    if result.outcome == "failed":
        raise typer.Exit(1)


@plugin_app.command("revoke")
def plugin_revoke_cmd(
    name: str = typer.Argument(..., help="Plugin name."),
    digest: str = typer.Option(
        "",
        "--digest",
        help="Digest to revoke (default: all grants for the plugin).",
    ),
    project: bool = _PLUGIN_PROJECT_OPTION,
) -> None:
    """Revoke digest-bound execution grants."""
    from deepseek_tui.plugins import PluginHost, RevokePlugin

    result = PluginHost().apply(
        RevokePlugin(name, digest.strip() or None, _plugins_dir(project))
    )
    typer.echo(result.message)
    if result.outcome == "failed":
        raise typer.Exit(1)


@plugin_app.command("gc")
def plugin_gc_cmd(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="List unreferenced digests without deleting them.",
    ),
) -> None:
    """Remove content-addressed source trees that no lockfile/symlink references."""
    from deepseek_tui.plugins import GcPlugins, PluginHost

    result = PluginHost().apply(GcPlugins(dry_run=dry_run))
    typer.echo(result.message)


@plugin_app.command("rollback")
def plugin_rollback_cmd(
    name: str = typer.Argument(..., help="Plugin name."),
    digest: str = typer.Argument(
        ...,
        help="Store digest (sha256 hex, or sha256:/fp: prefixed).",
    ),
    project: bool = _PLUGIN_PROJECT_OPTION,
) -> None:
    """Point an installed plugin back at a previously published store digest."""
    from deepseek_tui.plugins import PluginHost, RollbackPlugin

    result = PluginHost().apply(
        RollbackPlugin(name, digest, _plugins_dir(project))
    )
    typer.echo(result.message)
    if result.outcome == "failed":
        raise typer.Exit(1)


@plugin_app.command("reindex")
def plugin_reindex_cmd(
    project: bool = typer.Option(
        False,
        "--project",
        help="Only reindex the project scope (default: all scopes).",
    ),
) -> None:
    """Rebuild contribution indexes for deferred plugin assembly.

    Older installs without an index get one written into the lockfile so
    Engine.create can skip heavy disk scans. Safe to re-run anytime.
    """
    from deepseek_tui.integrations.plugins import (
        project_plugins_dir,
        reindex_contribution_indexes,
    )

    if project:
        n = reindex_contribution_indexes(
            project_plugins_dir(), Path.cwd(), include_claude=False
        )
    else:
        n = reindex_contribution_indexes(workspace=Path.cwd())
    typer.echo(f"Reindexed {n} plugin(s).")


@plugin_app.command("search")
def plugin_search_cmd(
    query: str = typer.Argument("", help="Filter by name/description (optional)."),
    registry_url: str = typer.Option(
        None, "--registry", help="Override the registry index URL."
    ),
) -> None:
    """Search the curated plugin marketplace index."""
    from deepseek_tui.integrations.plugins import fetch_plugin_registry

    doc = fetch_plugin_registry(registry_url)
    if doc is None:
        typer.echo("Plugin registry unavailable (network or host not allowed).")
        raise typer.Exit(1)
    q = query.strip().lower()
    matches = [
        e
        for e in doc.plugins
        if not q or q in e.name.lower() or q in e.description.lower()
    ]
    if not matches:
        typer.echo("No plugins matched.")
        return
    for e in matches:
        comp = f" [{', '.join(e.components)}]" if e.components else ""
        perms = f" perms={','.join(e.permissions)}" if e.permissions else ""
        desc = f" — {e.description}" if e.description else ""
        typer.echo(f"{e.name} ({e.source}){comp}{perms}{desc}")
        typer.echo(f"  install: deepseek-tui plugin install {e.source}")


@plugin_app.command("doctor")
def plugin_doctor_cmd(
    target: str = typer.Argument(
        ...,
        help="Path to a plugin dir, or a repo/marketplace.json to scan all plugins.",
    ),
) -> None:
    """Inspect a plugin or collection without installing or executing it."""
    from collections import Counter

    from deepseek_tui.plugins import PluginHost
    from deepseek_tui.plugins.source import PluginSourceError

    root = Path(target).expanduser()
    try:
        inspection = PluginHost().inspect(source=root)
    except PluginSourceError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1) from exc

    if not inspection.candidates:
        typer.echo("No plugins found to analyze.")
        raise typer.Exit(1)

    totals: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    for package in inspection.candidates:
        counts = Counter(item.kind for item in package.contributions)
        totals.update(counts)
        status = package.compatibility.status.value
        statuses[status] += 1
        summary = " ".join(f"{kind}={count}" for kind, count in sorted(counts.items()))
        mark = "×" if status in {"blocked", "unsupported"} else "✓"
        typer.echo(
            f"{mark} {package.plugin_id} "
            f"[{status}/{package.compatibility.adapter_id}]: "
            f"{summary or 'no contributions'}"
        )
        for diagnostic in package.compatibility.diagnostics:
            typer.echo(
                f"    {diagnostic.severity.value}: "
                f"{diagnostic.code} — {diagnostic.message}"
            )

    for diagnostic in inspection.diagnostics:
        typer.echo(
            f"! {diagnostic.severity.value}: "
            f"{diagnostic.code} — {diagnostic.message}"
        )

    typer.echo("")
    typer.echo(
        f"Analyzed {len(inspection.candidates)} plugin(s): "
        + ", ".join(f"{name}={count}" for name, count in sorted(statuses.items()))
    )
    typer.echo("Totals — " + ", ".join(f"{k}: {v}" for k, v in sorted(totals.items())))


@plugin_app.command("install-all")
def plugin_install_all_cmd(
    repo: str = typer.Argument(
        ..., help="Path to a repo containing .claude-plugin/marketplace.json."
    ),
    trust: bool = typer.Option(
        False, "--trust", help="Trust each plugin immediately (activates hooks/MCP)."
    ),
    project: bool = _PLUGIN_PROJECT_OPTION,
) -> None:
    """Bulk-install every local plugin advertised by a repo marketplace.json."""
    from deepseek_tui.integrations.plugins import install_plugin, load_marketplace
    from deepseek_tui.integrations.skills import InstallOutcome

    try:
        entries = load_marketplace(Path(repo))
    except FileNotFoundError:
        typer.echo(f"No marketplace.json found under {repo}")
        raise typer.Exit(1) from None
    if not entries:
        typer.echo("Marketplace has no local plugins to install.")
        raise typer.Exit(1)

    installed = skipped = failed = 0
    dest = _plugins_dir(project)
    for entry in entries:
        outcome, message = install_plugin(str(entry.path), dest, trust=trust)
        if outcome == InstallOutcome.INSTALLED:
            installed += 1
        elif outcome == InstallOutcome.ALREADY_EXISTS:
            skipped += 1
        else:
            failed += 1
            typer.echo(f"✗ {entry.name}: {message}")
    typer.echo(
        f"Installed {installed}, skipped {skipped} (already present), "
        f"failed {failed} of {len(entries)} plugins into {dest}."
    )

    if failed:
        raise typer.Exit(1)


@app.command()
def metrics(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
    config: Path | None = CONFIG_OPTION,
) -> None:
    """Print a thread-count rollup from the canonical runtime store."""
    total_sessions = len(_thread_store().list_threads())
    data = {"total_sessions": total_sessions}
    if json_output:
        typer.echo(json.dumps(data, indent=2))
    else:
        typer.echo("DeepSeek TUI Metrics")
        typer.echo(f"  Total sessions: {total_sessions}")
