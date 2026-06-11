from __future__ import annotations

import json
from typing import Any

from deepseek_tui.mcp.manager import McpManager
from deepseek_tui.tools._validators import optional_string as _optional_string
from deepseek_tui.tools._validators import require_string as _require_string
from deepseek_tui.tools.base import ToolCapability, ToolError, ToolResult, ToolSpec
from deepseek_tui.tools.context import ToolContext

MCP_MANAGER_KEY = "mcp_manager"


class ListMcpResourcesTool(ToolSpec):
    def name(self) -> str:
        return "list_mcp_resources"

    def description(self) -> str:
        return "List resources exposed by configured MCP servers."

    def input_schema(self) -> dict[str, object]:
        return {"type": "object", "properties": {"server": {"type": "string"}}}

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        server = _optional_string(input_data, "server")
        resources = await _manager(context).list_resources(server)
        return _json_result(resources)


class ListMcpResourceTemplatesTool(ToolSpec):
    def name(self) -> str:
        return "list_mcp_resource_templates"

    def description(self) -> str:
        return "List resource templates exposed by configured MCP servers."

    def input_schema(self) -> dict[str, object]:
        return {"type": "object", "properties": {"server": {"type": "string"}}}

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        server = _optional_string(input_data, "server")
        templates = await _manager(context).list_resource_templates(server)
        return _json_result(templates)


class ReadMcpResourceTool(ToolSpec):
    def name(self) -> str:
        return "read_mcp_resource"

    def description(self) -> str:
        return "Read a resource from an MCP server."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "server": {"type": "string"},
                "uri": {"type": "string"},
            },
            "required": ["server", "uri"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        result = await _manager(context).read_resource(
            _require_string(input_data, "server"),
            _require_string(input_data, "uri"),
        )
        return _json_result(result)


class McpGetPromptTool(ToolSpec):
    def name(self) -> str:
        return "mcp_get_prompt"

    def description(self) -> str:
        return "Get a prompt from an MCP server."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "server": {"type": "string"},
                "name": {"type": "string"},
                "arguments": {"type": "object"},
            },
            "required": ["server", "name"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        arguments = input_data.get("arguments")
        if arguments is not None and not isinstance(arguments, dict):
            raise ToolError("arguments must be an object")
        result = await _manager(context).get_prompt(
            _require_string(input_data, "server"),
            _require_string(input_data, "name"),
            arguments if isinstance(arguments, dict) else None,
        )
        return _json_result(result)


def _manager(context: ToolContext) -> McpManager:
    manager = context.services.optional(McpManager)
    if manager is None:
        raw = context.services.optional_named(MCP_MANAGER_KEY)
        manager = raw if isinstance(raw, McpManager) else None
    if manager is None:
        manager = context.metadata.get(MCP_MANAGER_KEY)
    if not isinstance(manager, McpManager):
        raise ToolError("MCP manager is not configured")
    return manager


def _json_result(value: Any) -> ToolResult:
    return ToolResult(
        success=True,
        content=json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True),
        metadata={"result": value},
    )


