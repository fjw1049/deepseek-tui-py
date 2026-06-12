"""Config file read/write helpers for CLI commands."""

from __future__ import annotations

from pathlib import Path

import typer

from deepseek_tui.config.models import Config


def config_get_value(config: Config, key: str) -> str | None:
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


def cli_config_write(key: str, value: str | None) -> None:
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
