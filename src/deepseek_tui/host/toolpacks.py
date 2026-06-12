"""ToolPack host contract for registry assembly."""

from __future__ import annotations

from typing import Protocol

from deepseek_tui.config.models import Config
from deepseek_tui.tools.base import ToolSpec


class ToolPack(Protocol):
    @property
    def id(self) -> str: ...

    def tools(self, config: Config, *, mode: str) -> list[ToolSpec]: ...
