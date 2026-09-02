"""API-key resolution and config.toml persistence."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

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


def write_active_api_key(value: str | None, *, path: Path | None = None) -> Path:
    """Set or clear the key for the provider selected by config.toml."""
    from deepseek_tui.config.paths import user_config_path

    config_path = path or user_config_path()
    content = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    provider = _read_top_level_string(content.splitlines(), "provider") or "deepseek"
    return write_api_key(provider, value, path=config_path)


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
    active_provider = _read_top_level_string(lines, "provider") or "deepseek"

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
    if updated != original:
        write_text_atomic(config_path, updated)
    return config_path


def _format_key(value: str) -> str:
    return value if _BARE_KEY_RE.fullmatch(value) else json.dumps(value, ensure_ascii=False)


def _format_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _is_key_assignment(line: str, key: str) -> bool:
    return re.match(rf"^\s*{re.escape(key)}\s*=", line) is not None


def _read_top_level_string(lines: list[str], key: str) -> str | None:
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=\s*(?:\"([^\"]*)\"|'([^']*)')")
    for line in lines:
        if _SECTION_RE.match(line):
            break
        match = pattern.match(line)
        if match:
            return (match.group(1) or match.group(2) or "").strip()
    return None


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
            updated.append(f"{key} = {_format_string(value)}")

    if value is not None and not found:
        while updated and not updated[-1].strip():
            updated.pop()
        updated.append(f"{key} = {_format_string(value)}")

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
                updated.append(f"{key} = {_format_string(value)}")
            in_section = header.group(1).strip() == section
            found_section = found_section or in_section
            updated.append(line)
            continue

        if in_section and _is_key_assignment(line, key):
            if value is not None and not found_key:
                updated.append(f"{key} = {_format_string(value)}")
            found_key = True
            continue
        updated.append(line)

    if in_section and value is not None and not found_key:
        updated.append(f"{key} = {_format_string(value)}")
    elif not found_section and value is not None:
        if updated and updated[-1].strip():
            updated.append("")
        updated.extend((f"[{section}]", f"{key} = {_format_string(value)}"))

    return updated


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
