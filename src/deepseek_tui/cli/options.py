"""Shared Typer options and config loading for the CLI."""

from __future__ import annotations

from pathlib import Path

import typer

from deepseek_tui.config.loader import ConfigLoader
from deepseek_tui.config.models import Config

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
MCP_WORKSPACE_OPTION = typer.Option(
    None, "--workspace", help="Workspace root (defaults to cwd)."
)


def load_config(
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
