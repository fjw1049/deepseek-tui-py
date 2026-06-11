from __future__ import annotations

from typing import TYPE_CHECKING

from deepseek_tui.config.models import Config

if TYPE_CHECKING:
    from deepseek_tui.client.base import LLMClient
from deepseek_tui.tools.base import ToolSpec
from deepseek_tui.tools.registry import ToolRegistry
from deepseek_tui.tools.rlm import RlmTool


def build_default_registry(config: Config | None = None, *, mode: str = "agent") -> ToolRegistry:
    """Build the model tool registry through host assembly."""
    from deepseek_tui.host.assembler import assemble_registry_only

    return assemble_registry_only(config or Config(), mode=mode)


def build_subagent_registry(
    config: Config | None = None,
    *,
    mode: str = "agent",
    allowed_tools: list[str] | None = None,
    client: LLMClient | None = None,
    root_model: str | None = None,
    extra_tools: list[ToolSpec] | None = None,
) -> ToolRegistry:
    """Tool surface for a sub-agent loop (mirrors Rust ``SubAgentToolRegistry``).

    Default ``allowed_tools=None`` inherits the full agent registry. Custom
    agents pass an explicit allowlist.
    """
    cfg = config or Config()
    registry = build_default_registry(cfg, mode=mode)
    wire_registry_client(registry, client, root_model=root_model or "deepseek-chat")
    if allowed_tools is not None:
        registry.filter_by_names(set(allowed_tools))
    if extra_tools:
        registry.register_all(extra_tools)
    return registry


def wire_registry_client(
    registry: ToolRegistry,
    client: LLMClient | None,
    *,
    root_model: str | None = None,
) -> None:
    """Re-register ``rlm`` with a live client after :class:`Engine` construction.

    ``build_default_registry`` registers ``RlmTool(client=None)`` because the
    registry is built before the HTTP client exists. Call this from
    :meth:`Engine.create` once the client is available.
    """
    if not registry.contains("rlm"):
        return
    model = root_model or "deepseek-chat"
    registry.remove("rlm")
    registry.register(RlmTool(client=client, root_model=model))
