from unittest.mock import AsyncMock

import pytest

from deepseek_tui.engine.context import load_project_context_with_parents
from deepseek_tui.engine.orchestrator.helpers import _detect_focus_skill
from deepseek_tui.integrations.skills import (
    Skill,
    SkillRegistry,
    _parse_skill_file,
    render_available_skills_context,
)
from deepseek_tui.mcp.manager import McpManager
from deepseek_tui.plugins.runtime import CompositeMcpManager
from deepseek_tui.tools.knowledge import SkillLoadTool, SkillSearchTool
from deepseek_tui.tools.registry import ToolContext, ToolError


@pytest.mark.asyncio
async def test_composite_resource_templates_routes_to_owner():
    manager = McpManager([])
    manager.list_resource_templates = AsyncMock(
        return_value={"demo": [{"uriTemplate": "demo://{id}"}]}
    )
    composite = CompositeMcpManager(manager)
    composite._manager_for_server = lambda name: manager if name == "demo" else None
    assert await composite.list_resource_templates() == {"demo": [{"uriTemplate": "demo://{id}"}]}
    assert await composite.list_resource_templates("demo") == {
        "demo": [{"uriTemplate": "demo://{id}"}]
    }
    assert manager.list_resource_templates.await_count == 2
    with pytest.raises(Exception, match="Unknown or ambiguous"):
        await composite.list_resource_templates("missing")


def test_nested_rules_keep_parent_and_stop_at_repo(tmp_path):
    repo = tmp_path / "repo"
    child = repo / "child"
    child.mkdir(parents=True)
    (repo / ".git").mkdir()
    (tmp_path / "AGENTS.md").write_text("OUTSIDE")
    (repo / "AGENTS.md").write_text("ROOT")
    (child / "AGENTS.md").write_text("CHILD")
    result = load_project_context_with_parents(
        child, home_dir=tmp_path / "home", allow_auto_generate=False
    )
    assert result.instructions.index("ROOT") < result.instructions.index("CHILD")
    assert "OUTSIDE" not in result.instructions
    assert result.source_paths == [repo / "AGENTS.md", child / "AGENTS.md"]


@pytest.mark.asyncio
async def test_manual_skill_blocked_until_explicit_invocation(tmp_path):
    path = tmp_path / "SKILL.md"
    path.write_text(
        "---\nname: deploy\ndescription: deploy production\ndisable-model-invocation: true\n"
        "allowed-tools: Read Grep Bash(git status)\n---\nDeploy body"
    )
    skill = _parse_skill_file(path)
    assert skill.allowed_tools == ("Read", "Grep", "Bash(git status)")
    registry = SkillRegistry(skills=[skill])
    assert "- deploy:" not in render_available_skills_context(registry)
    context = ToolContext(working_directory=tmp_path, metadata={"skill_registry": registry})
    for args in ({"name": "deploy"}, {"path": str(path)}):
        with pytest.raises(ToolError, match="explicit user invocation"):
            await SkillLoadTool().execute(args, context)
    assert "deploy" not in (await SkillSearchTool().execute({"query": "deploy"}, context)).content
    context.metadata["user_invoked_skill_path"] = str(path.resolve())
    assert "Deploy body" in (await SkillLoadTool().execute({"name": "deploy"}, context)).content


def test_non_user_invocable_skill_not_focused(tmp_path):
    skill = Skill(
        "background", "background knowledge", "body", tmp_path / "SKILL.md", user_invocable=False
    )
    assert _detect_focus_skill("/background", SkillRegistry(skills=[skill])) is None


@pytest.mark.asyncio
async def test_search_finds_skill_beyond_prompt_budget(tmp_path):
    skills = [
        Skill(f"skill-{i:03}", "long description " * 35, "body", tmp_path / str(i) / "SKILL.md")
        for i in range(100)
    ]
    registry = SkillRegistry(skills=skills)
    assert "- skill-099:" not in render_available_skills_context(registry)
    result = await SkillSearchTool().execute(
        {"query": "skill-099"},
        ToolContext(working_directory=tmp_path, metadata={"skill_registry": registry}),
    )
    assert "skill-099" in result.content


async def test_summary_request_disables_tools_and_preserves_history():
    from types import SimpleNamespace

    from deepseek_tui.engine.capacity import _create_summary
    from deepseek_tui.protocol.messages import Message, MessageRequest

    seen = []

    class Client:
        async def stream_chat_completion(self, request):
            seen.append(request)
            yield SimpleNamespace(text="handoff")

    messages = [Message.user("task")]
    tools = [
        {"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}
    ]
    template = MessageRequest(model="deepseek-chat", tools=tools, tool_choice={"type": "auto"})
    assert (
        await _create_summary(Client(), messages, "deepseek-chat", request_template=template)
        == "handoff"
    )
    assert seen[0].tool_choice == "none"
    assert seen[0].tools == tools
    assert seen[0].messages[0] == messages[0]
    assert template.tool_choice == {"type": "auto"}


def test_override_applies_only_to_its_directory(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "AGENTS.md").write_text("root")
    child = tmp_path / "child"
    child.mkdir()
    (child / "AGENTS.md").write_text("ignored")
    (child / "AGENTS.override.md").write_text("override")
    result = load_project_context_with_parents(
        child, home_dir=tmp_path / "home", allow_auto_generate=False
    )
    assert "root" in result.instructions and "override" in result.instructions
    assert "ignored" not in result.instructions
