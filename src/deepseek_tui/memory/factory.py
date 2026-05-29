"""Create the native smart-memory provider."""

from __future__ import annotations

from typing import TYPE_CHECKING

from deepseek_tui.memory.native.provider import NativeMemoryProvider
from deepseek_tui.memory.provider import MemoryProvider

if TYPE_CHECKING:
    from deepseek_tui.client.base import LLMClient
    from deepseek_tui.config.models import Config


def create_smart_memory_provider(config: Config, client: LLMClient) -> MemoryProvider:
    """Instantiate ``NativeMemoryProvider`` (L0+L1+FTS, local ``memory_data``)."""
    if not config.smart_memory_enabled():
        raise ValueError("smart memory is disabled in config")
    return NativeMemoryProvider(config, client)
