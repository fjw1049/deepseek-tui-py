"""Test helpers for binding evolution services on ToolContext."""

from __future__ import annotations

from deepseek_tui.host.services import ServiceScope
from deepseek_tui.tools.context import ToolContext


def add_named_service(context: ToolContext, key: str, value: object) -> None:
    context.services.add_named(
        key,
        value,
        owner="test",
        scope=ServiceScope.ENGINE,
    )
