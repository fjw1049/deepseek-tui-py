"""API-key resolution and config.toml persistence."""

from __future__ import annotations

import json
import os
import re
import threading
from copy import deepcopy
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, ParamSpec, TypeVar

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

from deepseek_tui.utils import write_text_atomic

if TYPE_CHECKING:
    from deepseek_tui.config.models import Config


_PROVIDER_ENV_CANDIDATES: dict[str, tuple[str, ...]] = {
    "deepseek": ("DEEPSEEK_API_KEY",),
    "kimi": ("KIMI_API_KEY", "MOONSHOT_API_KEY"),
    "moonshot": ("MOONSHOT_API_KEY", "KIMI_API_KEY"),
    "glm": ("GLM_API_KEY", "ZHIPU_API_KEY", "BIGMODEL_API_KEY"),
    "zhipu": ("ZHIPU_API_KEY", "GLM_API_KEY", "BIGMODEL_API_KEY"),
    "openrouter": ("OPENROUTER_API_KEY",),
    "novita": ("NOVITA_API_KEY",),
    "nvidia": ("NVIDIA_API_KEY", "NVIDIA_NIM_API_KEY", "DEEPSEEK_API_KEY"),
    "nvidia-nim": ("NVIDIA_API_KEY", "NVIDIA_NIM_API_KEY", "DEEPSEEK_API_KEY"),
    "nvidia_nim": ("NVIDIA_API_KEY", "NVIDIA_NIM_API_KEY", "DEEPSEEK_API_KEY"),
    "nim": ("NVIDIA_API_KEY", "NVIDIA_NIM_API_KEY", "DEEPSEEK_API_KEY"),
    "openai": ("OPENAI_API_KEY",),
    "volcengine-ark": ("ARK_API_KEY", "VOLCENGINE_API_KEY"),
    "volcengine-ark-anthropic": ("ARK_API_KEY", "VOLCENGINE_API_KEY"),
}

_BARE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_PROVIDER_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_SECTION_RE = re.compile(r"^\s*\[([^]]+)]\s*(?:#.*)?$")


def env_for(name: str) -> str | None:
    """Return the first non-empty environment key for a provider."""
    for variable in _PROVIDER_ENV_CANDIDATES.get(name.lower(), ()):
        value = os.environ.get(variable)
        if value is not None and value.strip():
            return value
    return None


def credential_providers(config: Config) -> list[str]:
    """Return every built-in or configured provider that can own a key."""
    from deepseek_tui.config.providers import PROVIDER_DEFAULTS

    return sorted(set(PROVIDER_DEFAULTS) | set(config.providers) | {config.provider})


_CONFIG_WRITE_LOCK = threading.RLock()
_P = ParamSpec("_P")
_R = TypeVar("_R")


def _serialized_write(function: Callable[_P, _R]) -> Callable[_P, _R]:
    @wraps(function)
    def run(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        with _CONFIG_WRITE_LOCK:
            return function(*args, **kwargs)

    return run


def _section_parts(section: str) -> tuple[str, ...]:
    node = tomllib.loads(f"[{section}]\n")
    parts = []
    while isinstance(node, dict) and len(node) == 1:
        key, node = next(iter(node.items()))
        parts.append(key)
    return tuple(parts)


def _assign(document: dict[str, Any], keys: tuple[str, ...], value: object) -> None:
    node = document
    for key in keys[:-1]:
        if value is None and key not in node:
            return
        child = node.setdefault(key, {})
        if not isinstance(child, dict):
            raise ValueError("Config update conflicts with an existing scalar")
        node = child
    if value is None:
        node.pop(keys[-1], None)
    else:
        node[keys[-1]] = value


def _checked_write(path: Path, original: str, updated: str, expected: dict[str, Any]) -> None:
    if tomllib.loads(updated) != expected:
        raise ValueError(
            "Cannot safely preserve TOML structure for this update; original file unchanged"
        )
    if updated != original:
        write_text_atomic(path, updated)


@_serialized_write
def write_active_api_key(value: str | None, *, path: Path | None = None) -> Path:
    """Set or clear the key for the provider selected by config.toml."""
    from deepseek_tui.config.paths import user_config_path

    config_path = path or user_config_path()
    content = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    provider = tomllib.loads(content).get("provider") or "deepseek"
    return write_api_key(provider, value, path=config_path)


@_serialized_write
def write_api_key(
    provider: str,
    value: str | None,
    *,
    path: Path | None = None,
) -> Path:
    """Set or clear a provider key in config.toml using an atomic write."""
    from deepseek_tui.config.paths import user_config_path

    provider = provider.strip()
    if not _PROVIDER_NAME_RE.fullmatch(provider):
        raise ValueError("provider name may contain only letters, numbers, '.', '_' and '-'")

    if value is not None:
        value = value.strip()
        if not value:
            raise ValueError("API key cannot be empty")

    config_path = path or user_config_path()
    original = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    lines = original.splitlines()
    expected = deepcopy(tomllib.loads(original))
    active_provider = expected.get("provider") or "deepseek"
    _assign(expected, ("providers", provider, "api_key"), value)
    if provider == active_provider:
        _assign(expected, ("api_key",), value)

    lines = _update_section_value(
        lines,
        section=f"providers.{_format_key(provider)}",
        key="api_key",
        value=value,
    )
    if provider == active_provider:
        # Workbench still reads the top-level api_key for the active provider.
        lines = _update_top_level_value(lines, "api_key", value)

    updated = "\n".join(lines)
    if updated:
        updated += "\n"
    _checked_write(config_path, original, updated, expected)
    return config_path


def _format_key(value: str) -> str:
    return value if _BARE_KEY_RE.fullmatch(value) else json.dumps(value, ensure_ascii=False)


def _format_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _format_scalar(value: object) -> str:
    """TOML literal for a str/bool/int value."""
    if isinstance(value, str):
        return _format_string(value)
    return json.dumps(value)


def _is_key_assignment(line: str, key: str) -> bool:
    return re.match(rf"^\s*{re.escape(key)}\s*=", line) is not None


def _update_top_level_value(lines: list[str], key: str, value: str | None) -> list[str]:
    section_index = next(
        (index for index, line in enumerate(lines) if _SECTION_RE.match(line)),
        len(lines),
    )
    head = lines[:section_index]
    rest = lines[section_index:]
    found = False
    updated: list[str] = []

    for line in head:
        if not _is_key_assignment(line, key):
            updated.append(line)
            continue
        found = True
        if value is not None:
            updated.append(f"{key} = {_format_scalar(value)}")

    if value is not None and not found:
        while updated and not updated[-1].strip():
            updated.pop()
        updated.append(f"{key} = {_format_scalar(value)}")

    if rest and updated and updated[-1].strip():
        updated.append("")
    return updated + rest


def _update_section_value(
    lines: list[str],
    *,
    section: str,
    key: str,
    value: str | None,
) -> list[str]:
    found_section = False
    found_key = False
    in_section = False
    updated: list[str] = []

    for line in lines:
        header = _SECTION_RE.match(line)
        if header:
            if in_section and value is not None and not found_key:
                updated.append(f"{key} = {_format_scalar(value)}")
            in_section = _section_parts(header.group(1)) == _section_parts(section)
            found_section = found_section or in_section
            updated.append(line)
            continue

        if in_section and _is_key_assignment(line, key):
            if value is not None and not found_key:
                updated.append(f"{key} = {_format_scalar(value)}")
            found_key = True
            continue
        updated.append(line)

    if in_section and value is not None and not found_key:
        updated.append(f"{key} = {_format_scalar(value)}")
    elif not found_section and value is not None:
        if updated and updated[-1].strip():
            updated.append("")
        updated.extend((f"[{section}]", f"{key} = {_format_scalar(value)}"))

    return updated


@_serialized_write
def write_config_value(key: str, value: str | None, *, path: Path | None = None) -> Path:
    """Set or clear a config.toml value by dotted key (``a`` or ``section.a``).

    ``value`` is a raw CLI string: "true"/"false" become booleans, digit-only
    strings become integers, anything else is stored as a TOML string.
    """
    from deepseek_tui.config.paths import user_config_path

    if not key or any(not _BARE_KEY_RE.fullmatch(part) for part in key.split(".")):
        raise ValueError(f"invalid config key: {key!r} (letters, digits, '_', '-', '.' only)")

    config_path = path or user_config_path()
    original = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    lines = original.splitlines()
    expected = deepcopy(tomllib.loads(original))
    _assign(expected, tuple(key.split(".")), _format_value(value))

    if "." in key:
        section, leaf = key.rsplit(".", 1)
        lines = _update_section_value(lines, section=section, key=leaf, value=_format_value(value))
    else:
        lines = _update_top_level_value(lines, key, value=_format_value(value))

    updated = "\n".join(lines)
    if updated:
        updated += "\n"
    _checked_write(config_path, original, updated, expected)
    return config_path


def _format_value(value: str | None) -> object:
    if value is None:
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    if value.isdigit():
        return int(value)
    return value


class SecretsManager:
    """Resolve provider credentials using environment, then config.toml."""

    def resolve_api_key(self, config: Config, provider_name: str | None = None) -> str | None:
        provider = provider_name or config.provider

        env_value = env_for(provider)
        if env_value is not None and env_value.strip():
            return env_value

        provider_config = config.providers.get(provider)
        if provider_config and provider_config.api_key:
            value = provider_config.api_key
            if value.strip():
                return value

        # The top-level key belongs only to the active provider. Reusing it
        # for endpoint tests of another provider can send the wrong credential.
        if provider == config.provider and config.api_key and config.api_key.strip():
            return config.api_key

        return None
