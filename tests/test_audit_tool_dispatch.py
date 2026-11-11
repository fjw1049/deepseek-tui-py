"""Exercise provider name round trips through the real engine and filesystem."""

from unittest.mock import AsyncMock

import pytest

from deepseek_tui.engine.handle import AutoApprovalHandler, EngineHandle
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.tools.approval import ExecPolicyEngine
from deepseek_tui.tools.encoding import from_api_tool_name
from deepseek_tui.tools.file import ReadFileTool
from deepseek_tui.tools.registry import ToolCapability, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["files.read", "files:read", "读取文件", "files--read", "files-x00002E-read"])
async def test_registered_tool_roundtrips_provider_name_before_catalog_gate(tmp_path, name):
    class NamedReadFile(ReadFileTool):
        def name(self):
            return name

    (tmp_path / "example.txt").write_text("真实文件内容\n", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(NamedReadFile())
    engine = Engine(
        handle=EngineHandle(),
        client=AsyncMock(),
        tool_registry=registry,
        tool_context=ToolContext(working_directory=tmp_path),
        exec_policy=ExecPolicyEngine(approval_policy="auto"),
        approval_handler=AutoApprovalHandler(),
    )
    catalog = registry.to_api_tools()
    # Streaming clients decode the wire name before constructing ToolCall.
    decoded = from_api_tool_name(catalog[0]["function"]["name"])
    call = ToolCall(id="read-example", name=decoded, arguments={"path": "example.txt"})
    result = await engine._execute_single_tool(call, catalog, "test-model")
    assert result is not None and result.success
    assert "真实文件内容" in result.content
    with pytest.raises(ToolError):
        await engine._execute_single_tool(call, [], "test-model")


@pytest.mark.asyncio
async def test_registry_validates_dictionary_values_without_breaking_legacy_extra_fields(tmp_path):
    class ScoreTool(ToolSpec):
        def name(self):
            return "sum_scores"

        def description(self):
            return "Sum integer scores by label."

        def capabilities(self):
            return [ToolCapability.READ_ONLY]

        def input_schema(self):
            return {"type": "object", "properties": {
                "scores": {"type": "object", "additionalProperties": {"type": "integer"}}
            }, "required": ["scores"], "additionalProperties": False}

        async def execute(self, input_data, context):
            return ToolResult(True, str(sum(input_data["scores"].values())))

    context = ToolContext(working_directory=tmp_path)
    registry = ToolRegistry(context)
    registry.register(ScoreTool())
    with pytest.raises(ToolError, match="invalid arguments"):
        await registry.execute("sum_scores", {"scores": {"quality": "invalid"}}, context)
    result = await registry.execute("sum_scores", {"scores": {"quality": 2, "speed": 3}, "legacy": True}, context)
    assert result.success and result.content == "5"
