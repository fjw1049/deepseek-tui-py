"""Cross-turn memory, cancellation, and bounded-search regression scenarios."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.client.base import LLMClient
from deepseek_tui.config import Config
from deepseek_tui.engine import Engine
from deepseek_tui.engine.handle import EngineHandle, SendMessageOp
from deepseek_tui.protocol.messages import Message, ToolResultBlock, ToolUseBlock
from deepseek_tui.protocol.responses import StreamDone, StreamToolCallComplete, ToolCall
from deepseek_tui.tools.knowledge import NoteTool
from deepseek_tui.tools.registry import ToolContext, ToolError
from tests.test_audit_tool_pipeline import _engine


@pytest.mark.asyncio
async def test_note_config_roundtrip_and_readonly_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("DEEPSEEK_NOTES_PATH", raising=False)
    cfg = Config(notes_path=tmp_path / "custom" / "notes.txt")
    for feature in ("tasks", "subagents", "mcp", "automations", "plugins"):
        setattr(cfg.features, feature, False)
    for mode in ("agent", "ask", "plan"):
        engine = await Engine.create(
            handle=EngineHandle(),
            client=AsyncMock(),
            config=cfg,
            working_directory=tmp_path,
            mode=mode,
            start_mcp=False,
        )
        try:
            if mode == "agent":
                await NoteTool().execute(
                    {"content": "Remember this actual decision"}, engine.tool_context
                )
            catalog = await engine._get_tools_with_mcp()
            read = await engine._execute_single_tool(
                ToolCall(id="read", name="note", arguments={"action": "read"}), catalog, "test"
            )
            assert "Remember this actual decision" in read.content
            if mode != "agent":
                with pytest.raises(ToolError, match="Only reading"):
                    await engine._execute_single_tool(
                        ToolCall(id="write", name="note", arguments={"content": "wrong"}),
                        catalog,
                        "test",
                    )
        finally:
            await engine.shutdown_session()
    assert "wrong" not in cfg.notes_path.read_text()
    assert not (tmp_path / "home" / "notes.txt").exists()


@pytest.mark.asyncio
async def test_hard_cancel_keeps_completed_file_and_history(tmp_path, monkeypatch):
    from deepseek_tui.engine.transcript import Transcript, read_transcript

    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    waiting = asyncio.Event()

    class Client(LLMClient):
        count = 0

        async def stream_chat_completion(self, request):
            self.count += 1
            if self.count == 1:
                yield StreamToolCallComplete(
                    tool_call=ToolCall(
                        id="done",
                        name="write_file",
                        arguments={"path": "done.txt", "content": "written"},
                    )
                )
                yield StreamDone()
            else:
                waiting.set()
                await asyncio.Event().wait()

    engine, _ = await _engine(tmp_path, [])
    transcript_path = tmp_path / "interrupted.jsonl"
    engine.transcript = Transcript(transcript_path)
    engine.client = Client()
    engine.turn_loop.client = engine.client
    engine._handle_approval_flow = AsyncMock(return_value=False)
    job = asyncio.create_task(
        engine._handle_send_message(SendMessageOp(content="Write and continue"))
    )
    try:
        await asyncio.wait_for(waiting.wait(), 2)
        job.cancel()
        await job
        assert (tmp_path / "done.txt").read_text() == "written"
        assert "Write and continue" in engine.session_messages[0].text_content()
        calls = {
            b.id for m in engine.session_messages for b in m.content if isinstance(b, ToolUseBlock)
        }
        results = {
            b.tool_use_id
            for m in engine.session_messages
            for b in m.content
            if isinstance(b, ToolResultBlock)
        }
        assert calls == results == {"done"}
        restored = read_transcript(transcript_path)
        assert restored.messages() == engine.session_messages
        assert '"type":"interrupted"' in transcript_path.read_text().replace(" ", "")
    finally:
        await engine.shutdown_session()


def test_fork_prefix_contains_current_user_and_prior_results():
    from deepseek_tui.engine.history import complete_tool_prefix, interrupted_turn_messages

    messages = [
        Message.user("Current request"),
        Message.assistant_with_tools([ToolUseBlock(id="read", name="read_file", input={})]),
        Message.tool_result("read", "actual evidence"),
        Message.assistant_with_tools([ToolUseBlock(id="agent", name="agent", input={})]),
    ]
    assert complete_tool_prefix(messages) == messages[:-1]
    repaired = interrupted_turn_messages(messages, {})
    assert repaired[-1].content[0].tool_use_id == "agent"
    assert repaired[-1].content[0].is_error
    assert "may have had side effects" in repaired[-1].content[0].content


@pytest.mark.asyncio
async def test_grep_keeps_real_matches_when_traversal_budget_expires(tmp_path, monkeypatch):
    from deepseek_tui.tools import search

    path = tmp_path / "first.txt"
    path.write_text("needle found\n")

    def bounded_files(*args, **kwargs):
        yield path
        raise search.SearchBudgetExceeded("Search traversal budget exceeded")

    monkeypatch.setattr(search, "_iter_files", bounded_files)
    result = await search.GrepFilesTool().execute(
        {"path": ".", "pattern": "needle", "output_mode": "content"},
        ToolContext(working_directory=tmp_path),
    )
    assert result.success and result.metadata["incomplete"]
    assert "needle found" in result.content and "Search incomplete" in result.content


@pytest.mark.asyncio
async def test_skill_read_root_does_not_follow_external_symlinks_or_grant_write(tmp_path):
    from deepseek_tui.integrations.skills import Skill, SkillRegistry
    from deepseek_tui.tools.file import ReadFileTool
    from deepseek_tui.tools.knowledge import SkillLoadTool

    root = tmp_path / "skills" / "one"
    root.mkdir(parents=True)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (root / "SKILL.md").write_text("Read files")
    (root / "guide.txt").write_text("authorized guide")
    (root / ".env").write_text("secret")
    outside = tmp_path / "outside.txt"
    outside.write_text("not authorized")
    (root / "escape.txt").symlink_to(outside)
    context = ToolContext(working_directory=workspace)
    context.metadata["skill_registry"] = SkillRegistry(
        skills=[Skill("one", "one", "Read files", root / "SKILL.md")]
    )
    await SkillLoadTool().execute({"name": "one"}, context)
    assert (await ReadFileTool().execute({"path": str(root / "guide.txt")}, context)).success
    for path in (root / "escape.txt", root / ".env"):
        with pytest.raises((ValueError, ToolError)):
            await ReadFileTool().execute({"path": str(path)}, context)
    assert not context.check_path(str(root / "guide.txt"), write=True).allowed


@pytest.mark.asyncio
async def test_empty_mcp_catalog_hides_resource_helpers_and_trust_typos_are_visible(tmp_path):
    from deepseek_tui.engine.events import StatusEvent
    from deepseek_tui.mcp.config import McpServerConfig
    from deepseek_tui.mcp.manager import McpManager
    from deepseek_tui.tools.mcp import MCP_MANAGER_KEY
    from deepseek_tui.tools.registry import build_default_registry

    engine, _ = await _engine(tmp_path, [])
    engine.tool_registry = build_default_registry(Config())
    empty = McpManager([])
    engine.tool_context.metadata[MCP_MANAGER_KEY] = empty
    engine.tool_runtime.mcp_manager = empty
    try:
        names = {tool["function"]["name"] for tool in await engine._get_tools_with_mcp()}
        assert not names & {
            "read_mcp_resource",
            "list_mcp_resources",
            "list_mcp_resource_templates",
        }
        engine._app_config.mcp_read_only_tools = ["mcp_misspelled_read"]
        await engine._get_tools_with_mcp()
        await engine._get_tools_with_mcp()
        warnings = [
            event.message
            for event in engine.handle.drain_events()
            if isinstance(event, StatusEvent) and "not discovered" in event.message
        ]
        assert len(warnings) == 1 and "mcp_misspelled_read" in warnings[0]
        # A configured lazy service retains discovery helpers before connecting.
        lazy = McpManager([McpServerConfig(name="lazy", command="unused-fixture-command")])
        engine.tool_context.metadata[MCP_MANAGER_KEY] = lazy
        engine.tool_runtime.mcp_manager = lazy
        names = {tool["function"]["name"] for tool in await engine._get_tools_with_mcp()}
        assert "list_mcp_resources" in names
    finally:
        await engine.shutdown_session()
