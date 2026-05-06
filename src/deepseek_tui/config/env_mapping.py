from __future__ import annotations

import os
from pathlib import Path
from typing import Any

ENV_TO_FIELD: dict[str, tuple[str, ...]] = {
    "DEEPSEEK_PROVIDER": ("provider",),
    "DEEPSEEK_TUI_PROVIDER": ("provider",),
    "DEEPSEEK_MODEL": ("model",),
    "DEEPSEEK_DEFAULT_TEXT_MODEL": ("default_text_model",),
    "DEEPSEEK_TUI_MODEL": ("model",),
    "DEEPSEEK_TUI_PROFILE": ("profile",),
    "DEEPSEEK_TUI_DATABASE_PATH": ("state", "database_path"),
    "DEEPSEEK_TUI_SHOW_THINKING": ("ui", "show_thinking"),
    "DEEPSEEK_LOG_LEVEL": ("log_level",),
    "DEEPSEEK_API_KEY": ("providers", "deepseek", "api_key"),
    "DEEPSEEK_BASE_URL": ("providers", "deepseek", "base_url"),
    "DEEPSEEK_SKILLS_DIR": ("skills_dir",),
    "DEEPSEEK_MCP_CONFIG": ("mcp_config_path",),
    "DEEPSEEK_NOTES_PATH": ("notes_path",),
    "DEEPSEEK_MEMORY_PATH": ("memory_path",),
    "DEEPSEEK_ALLOW_SHELL": ("allow_shell",),
    "DEEPSEEK_APPROVAL_POLICY": ("approval_policy",),
    "DEEPSEEK_SANDBOX_MODE": ("sandbox_mode",),
    "DEEPSEEK_MANAGED_CONFIG_PATH": ("managed_config_path",),
    "DEEPSEEK_REQUIREMENTS_PATH": ("requirements_path",),
    "DEEPSEEK_MAX_SUBAGENTS": ("max_subagents",),
    "DEEPSEEK_CAPACITY_ENABLED": ("capacity", "enabled"),
    "DEEPSEEK_CAPACITY_LOW_RISK_MAX": ("capacity", "low_risk_max"),
    "DEEPSEEK_CAPACITY_MEDIUM_RISK_MAX": ("capacity", "medium_risk_max"),
}


def read_env_overrides() -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for env_name, path in ENV_TO_FIELD.items():
        value = os.getenv(env_name)
        if value is None:
            continue
        typed_value: Any = value
        if path[-1] in {"show_thinking", "allow_shell", "enabled"}:
            typed_value = value.lower() in {"1", "true", "yes", "on"}
        elif path[-1] in {
            "database_path",
            "skills_dir",
            "mcp_config_path",
            "notes_path",
            "memory_path",
            "managed_config_path",
            "requirements_path",
        }:
            typed_value = Path(value)
        elif path[-1] in {"max_subagents"}:
            typed_value = int(value)
        elif path[-1] in {"low_risk_max", "medium_risk_max"}:
            typed_value = float(value)
        cursor = overrides
        for part in path[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[path[-1]] = typed_value
    return overrides
