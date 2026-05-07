from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from deepseek_tui.config.loader import ConfigLoader

app = typer.Typer(add_completion=False, no_args_is_help=True)
CONFIG_OPTION = typer.Option(None, "--config", help="Path to config TOML file.")
PROFILE_OPTION = typer.Option(None, help="Config profile name.")
PROVIDER_OPTION = typer.Option(None, help="Override provider name.")
MODEL_OPTION = typer.Option(None, help="Override model name.")


@app.command()
def run(
    config: Path | None = CONFIG_OPTION,
    profile: str | None = PROFILE_OPTION,
    provider: str | None = PROVIDER_OPTION,
    model: str | None = MODEL_OPTION,
) -> None:
    loaded = ConfigLoader().load(
        config_path=config,
        profile_name=profile,
        provider=provider,
        model=model,
    )
    typer.echo(f"Loaded provider={loaded.provider} model={loaded.model}")


@app.command()
def config_show(
    config: Path | None = CONFIG_OPTION,
    profile: str | None = PROFILE_OPTION,
    provider: str | None = PROVIDER_OPTION,
    model: str | None = MODEL_OPTION,
) -> None:
    loaded = ConfigLoader().load(
        config_path=config,
        profile_name=profile,
        provider=provider,
        model=model,
    )
    typer.echo(loaded.model_dump_json(indent=2))


@app.command()
def version() -> None:
    typer.echo("deepseek-tui-py 0.1.0")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host for HTTP."),
    port: int = typer.Option(8787, "--port", help="Bind port for HTTP."),
    stdio: bool = typer.Option(
        False, "--stdio", help="Speak newline-delimited JSON-RPC on stdin/stdout instead of HTTP."
    ),
    config: Path | None = CONFIG_OPTION,
    profile: str | None = PROFILE_OPTION,
    provider: str | None = PROVIDER_OPTION,
    model: str | None = MODEL_OPTION,
) -> None:
    """Start the app-server (HTTP by default; --stdio for JSON-RPC pipe)."""
    from deepseek_tui.app_server import AppServerOptions, run_http, run_stdio

    loaded = ConfigLoader().load(
        config_path=config,
        profile_name=profile,
        provider=provider,
        model=model,
    )
    if stdio:
        typer.echo("app-server: stdio JSON-RPC mode", err=True)
        asyncio.run(run_stdio(config=loaded))
        return
    typer.echo(f"app-server listening on http://{host}:{port}", err=True)
    options = AppServerOptions(host=host, port=port, config_path=config)
    asyncio.run(run_http(options, config=loaded))
