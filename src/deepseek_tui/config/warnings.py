"""Warn when config.toml fields are parsed but not yet consumed at runtime."""

from __future__ import annotations

import logging

from deepseek_tui.config.models import Config

logger = logging.getLogger(__name__)

# Fields present in TOML for Rust parity but not wired in Python yet.
_UNCONSUMED_TOP_LEVEL: dict[str, str] = {
    "tools_file": "custom tool manifest path (not loaded)",
}

_UNCONSUMED_CONTEXT: dict[str, str] = {
    "enabled": "global context expansion toggle (file_context always partial)",
}


def warn_unconsumed_config_fields(config: Config) -> None:
    """Log once per process for known placeholder settings."""
    for field, note in _UNCONSUMED_TOP_LEVEL.items():
        value = getattr(config, field, None)
        if value is not None and value != "":
            logger.warning(
                "config field %s is set (%r) but not consumed: %s",
                field,
                value,
                note,
            )
    ctx = config.context
    if ctx is not None and not ctx.enabled:
        logger.warning(
            "config context.enabled=false is stored but global disable is not "
            "enforced; %s",
            _UNCONSUMED_CONTEXT["enabled"],
        )
