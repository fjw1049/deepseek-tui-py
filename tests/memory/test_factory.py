from __future__ import annotations

import pytest

from deepseek_tui.config.models import Config, MemoryConfig, MemorySmartConfig
from deepseek_tui.memory.coordinator import create_smart_memory_provider
from deepseek_tui.memory.seed import NativeMemoryProvider


class _FakeClient:
    pass


def test_factory_native() -> None:
    cfg = Config(memory=MemoryConfig(smart=MemorySmartConfig(enabled=True)))
    provider = create_smart_memory_provider(cfg, _FakeClient())  # type: ignore[arg-type]
    assert isinstance(provider, NativeMemoryProvider)


def test_factory_disabled_raises() -> None:
    cfg = Config(memory=MemoryConfig(smart=MemorySmartConfig(enabled=False)))
    with pytest.raises(ValueError, match="disabled"):
        create_smart_memory_provider(cfg, _FakeClient())  # type: ignore[arg-type]
