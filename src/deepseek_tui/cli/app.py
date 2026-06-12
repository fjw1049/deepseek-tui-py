"""CLI entry point — mirrors ``crates/cli/src/lib.rs``.

Subcommands register through ``deepseek_tui.cli.commands.register_commands``.
"""
from __future__ import annotations

import typer

from deepseek_tui.cli.commands import register_commands

app = typer.Typer(
    name="deepseek-tui",
    add_completion=True,
    no_args_is_help=False,
    help="DeepSeek TUI — terminal AI agent (Python edition).",
)

register_commands(app)
