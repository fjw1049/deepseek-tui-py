from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.engine.context import MAX_CONTEXT_SIZE, load_project_context_with_parents
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.integrations.skills import (
    Skill,
    SkillRegistry,
    discover_in_workspace,
    render_available_skills_context,
)
from deepseek_tui.protocol.messages import Message, MessageOrigin, MessageRequest
from deepseek_tui.tools.registry import ToolContext


def test_manual_skill_visible_only_for_explicit_focus(tmp_path):
    skill = Skill(
        "deploy", "Deploy production", "body", tmp_path / "SKILL.md", disable_model_invocation=True
    )
    registry = SkillRegistry(skills=[skill])
    engine = Engine(
        handle=EngineHandle(),
        client=AsyncMock(),
        tool_context=ToolContext(working_directory=tmp_path),
        skill_registry=registry,
    )
    assert "- deploy:" not in engine._render_skills_context()
    assert "- deploy:" in engine._render_skills_context(only=skill)
    # Merely mounting a plugin must not authorize its manual-only skills.
    assert "- deploy:" not in engine._render_skills_context(only=[skill])
    engine.tool_context.metadata["user_invoked_skill_path"] = str(skill.path.resolve())
    assert "- deploy:" in engine._compose_system_prompt()
    engine.tool_context.metadata.clear()
    assert "- deploy:" not in engine._compose_system_prompt()


def test_explicit_manual_skill_survives_catalog_budget(tmp_path):
    registry = SkillRegistry(
        skills=[
            Skill(f"ordinary{i}", "description " * 100, "body", tmp_path / str(i) / "SKILL.md")
            for i in range(100)
        ]
    )
    manual = Skill(
        "deploy", "Deploy", "body", tmp_path / "deploy/SKILL.md", disable_model_invocation=True
    )
    registry.skills.append(manual)
    prompt = render_available_skills_context(registry, invoked_skill_path=manual.path)
    assert "additional skills omitted" in prompt
    assert "- deploy:" in prompt
    assert registry.skills[-1] is manual


def test_skill_collisions_do_not_fill_prompt_warnings(tmp_path, monkeypatch, caplog):
    roots = [tmp_path / name for name in ("first", "linked", "different")]
    for root in roots:
        root.mkdir()
    original = roots[0] / "demo"
    original.mkdir()
    (original / "SKILL.md").write_text("---\nname: demo\n---\nBody")
    (roots[1] / "demo").symlink_to(original, target_is_directory=True)
    different = roots[2] / "demo"
    different.mkdir()
    (different / "SKILL.md").write_text("---\nname: demo\n---\nOther")
    monkeypatch.setattr(
        "deepseek_tui.integrations.skills.skills_directories", lambda *a, **kw: roots
    )
    with caplog.at_level("INFO"):
        registry = discover_in_workspace()
    assert len(registry.skills) == 1
    assert not registry.warnings
    assert sum("shadowed" in row.message for row in caplog.records) == 1
    assert "shadowed" not in render_available_skills_context(registry)


def test_non_git_uses_nearest_rule_only(tmp_path):
    (tmp_path / "AGENTS.md").write_text("UNRELATED_PARENT")
    child = tmp_path / "child"
    child.mkdir()
    (child / "AGENTS.md").write_text("LOCAL")
    context = load_project_context_with_parents(
        child, home_dir=tmp_path / "home", allow_auto_generate=False
    )
    assert context.instructions == "LOCAL"
    (child / "AGENTS.md").unlink()
    context = load_project_context_with_parents(
        child, home_dir=tmp_path / "home", allow_auto_generate=False
    )
    assert context.instructions == "UNRELATED_PARENT"


def test_git_rule_chain_has_utf8_total_budget(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "AGENTS.md").write_text("根" * 25000)
    child = tmp_path / "child"
    child.mkdir()
    (child / "AGENTS.md").write_text("子" * 25000)
    home = tmp_path / "home"
    (home / ".deepseek").mkdir(parents=True)
    (home / ".deepseek/AGENTS.md").write_text("全" * 25000)
    result = load_project_context_with_parents(child, home_dir=home, allow_auto_generate=False)
    assert len(result.instructions.encode("utf-8")) <= MAX_CONTEXT_SIZE
    assert "子" in result.instructions
    assert any("budget exceeded" in warning for warning in result.warnings)
    assert result.source_paths == [child / "AGENTS.md"]


def test_rule_file_at_size_limit_is_not_dropped_by_merge_headers(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "AGENTS.md").write_text("R" * MAX_CONTEXT_SIZE)
    home = tmp_path / "home"
    (home / ".deepseek").mkdir(parents=True)
    result = load_project_context_with_parents(tmp_path, home_dir=home, allow_auto_generate=False)
    assert result.instructions == "R" * MAX_CONTEXT_SIZE
    assert not any("budget exceeded" in warning for warning in result.warnings)


@pytest.mark.parametrize("operation", ["summary", "cycle"])
async def test_summary_without_tools_omits_tool_choice(operation):
    from deepseek_tui.engine.capacity import _create_summary
    from deepseek_tui.engine.cycle import produce_briefing
    from deepseek_tui.protocol.responses import StreamTextDelta

    requests = []

    async def stream(request):
        requests.append(request)
        yield StreamTextDelta(text="### Goal\nPreserve constraints\n### Next step\nVerify")

    client = SimpleNamespace(stream_chat_completion=stream)
    template = MessageRequest(model="deepseek-chat", tools=[], tool_choice="auto")
    if operation == "summary":
        await _create_summary(
            client, [Message.user("task")], template.model, request_template=template
        )
    else:
        await produce_briefing(
            client, template.model, [Message.user("task")], 1000, request_template=template
        )
    assert requests[0].tool_choice is None
    # Inspect actual provider payloads offline; no HTTP requests are made.
    from deepseek_tui.client.anthropic import AnthropicCompatClient
    from deepseek_tui.client.deepseek import DeepSeekClient
    from deepseek_tui.client.openai_responses import OpenAIResponsesClient

    for cls in (DeepSeekClient, AnthropicCompatClient, OpenAIResponsesClient):
        native = cls(api_key="offline-test", base_url="https://offline.invalid")
        try:
            payload = native._build_payload(requests[0])
            assert "tool_choice" not in payload
            assert "tools" not in payload
        finally:
            await native.close()
    assert template.tool_choice == "auto"


async def test_large_mcp_catalog_is_stable_without_new_search_layer(tmp_path):
    from deepseek_tui.mcp.config import McpServerConfig
    from deepseek_tui.mcp.manager import McpManager
    from deepseek_tui.tools.mcp import MCP_MANAGER_KEY

    manager = McpManager([McpServerConfig(name="linear", command="unused")])
    manager.schedule_background_discover = lambda: None
    manager._discovered_tools_cache = [
        {
            "type": "function",
            "function": {
                "name": f"mcp_linear_tool_{i}",
                "description": "Linear issue " * 500,
                "parameters": {"type": "object"},
            },
        }
        for i in range(15)
    ]
    ctx = ToolContext(working_directory=tmp_path, metadata={MCP_MANAGER_KEY: manager})
    engine = Engine(handle=EngineHandle(), client=AsyncMock(), tool_context=ctx)
    tools = await engine._get_tools_with_mcp()
    assert len([t for t in tools if t["function"]["name"].startswith("mcp_")]) == 15
    assert tools == await engine._get_tools_with_mcp()
    assert not any(t["function"]["name"] in {"search_mcp_tools", "task_state"} for t in tools)


def test_retired_task_state_still_deserializes_as_synthetic():
    from deepseek_tui.engine.context_pressure import collect_user_requests

    message = Message.model_validate(
        {"role": "user", "content": [{"type": "text", "text": "old state"}], "origin": "task_state"}
    )
    assert message.origin is MessageOrigin.TASK_STATE
    assert collect_user_requests([message, Message.user("real request")]) == ["real request"]


def test_focus_aliases_do_not_widen_argument_matchers(caplog):
    from deepseek_tui.integrations.skills import focus_tool_names

    assert focus_tool_names(("Read", "Grep", "Bash(git status)")) == {"read_file", "grep_files"}
    assert "Unsupported allowed-tools" in caplog.text
