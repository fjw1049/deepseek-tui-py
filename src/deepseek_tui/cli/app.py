from __future__ import annotations

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
