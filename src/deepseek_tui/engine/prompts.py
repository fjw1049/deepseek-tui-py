from __future__ import annotations


def build_system_prompt(override: str | None = None) -> str:
    if override is not None and override.strip():
        return override
    return "You are DeepSeek-TUI Python rewrite."
