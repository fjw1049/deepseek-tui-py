from deepseek_tui.engine.context import estimate_context_breakdown
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.tools.registry import ToolRegistry


def _api_tool(name: str) -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": f"{name} description",
            "parameters": {"type": "object", "properties": {}},
        },
    }


def test_context_breakdown_splits_user_controlled_buckets(tmp_path):
    (tmp_path / "AGENTS.md").write_text(
        "Project rule: keep changes surgical.\n",
        encoding="utf-8",
    )

    breakdown = estimate_context_breakdown(
        model="deepseek-chat",
        workspace=tmp_path,
        skills_context="Skill: use the reviewer skill for code review.",
        api_tools=[
            _api_tool("read_file"),
            _api_tool("mcp__github__list_issues"),
        ],
    )

    assert breakdown["rules"] > 0
    assert breakdown["skills"] > 0
    assert breakdown["tool_definitions"] > 0
    assert breakdown["mcp"] > 0
    assert breakdown["tools"] == breakdown["tool_definitions"] + breakdown["mcp"]
    assert breakdown["total"] == (
        breakdown["system_prompt"]
        + breakdown["rules"]
        + breakdown["skills"]
        + breakdown["tools"]
        + breakdown["conversation"]
    )


def test_context_breakdown_scales_static_buckets_when_real_undershoots(tmp_path):
    """Provider real input can be lower than char-based static estimates.

    Without scaling, Conversation clamps to 0 while category rows still show
    the full static sum — e.g. header ~4.5k vs rows ~17k.
    """
    (tmp_path / "AGENTS.md").write_text(
        "Project rule: keep changes surgical.\n",
        encoding="utf-8",
    )
    baseline = estimate_context_breakdown(
        model="deepseek-chat",
        workspace=tmp_path,
        skills_context="Skill: use the reviewer skill for code review.",
        api_tools=[
            _api_tool("read_file"),
            _api_tool("mcp__github__list_issues"),
        ],
    )
    static_total = (
        baseline["system_prompt"]
        + baseline["rules"]
        + baseline["skills"]
        + baseline["tools"]
    )
    assert static_total > 100
    real = max(1, static_total // 4)

    breakdown = estimate_context_breakdown(
        model="deepseek-chat",
        workspace=tmp_path,
        skills_context="Skill: use the reviewer skill for code review.",
        api_tools=[
            _api_tool("read_file"),
            _api_tool("mcp__github__list_issues"),
        ],
        real_input_tokens=real,
    )

    assert breakdown["total"] == real
    assert breakdown["conversation"] == 0
    assert breakdown["tools"] == breakdown["tool_definitions"] + breakdown["mcp"]
    assert breakdown["total"] == (
        breakdown["system_prompt"]
        + breakdown["rules"]
        + breakdown["skills"]
        + breakdown["tools"]
        + breakdown["conversation"]
    )
    # Rows must shrink with the real total — not stay at the unscaled static sum.
    assert (
        breakdown["system_prompt"]
        + breakdown["rules"]
        + breakdown["skills"]
        + breakdown["tools"]
    ) == real
    assert breakdown["system_prompt"] < baseline["system_prompt"]
    assert breakdown["tool_definitions"] < baseline["tool_definitions"]


def test_context_breakdown_back_derives_conversation_when_real_overshoots(tmp_path):
    baseline = estimate_context_breakdown(
        model="deepseek-chat",
        workspace=tmp_path,
        api_tools=[_api_tool("read_file")],
    )
    static_total = (
        baseline["system_prompt"]
        + baseline["rules"]
        + baseline["skills"]
        + baseline["tools"]
    )
    real = static_total + 1234
    breakdown = estimate_context_breakdown(
        model="deepseek-chat",
        workspace=tmp_path,
        api_tools=[_api_tool("read_file")],
        real_input_tokens=real,
    )
    assert breakdown["total"] == real
    assert breakdown["conversation"] == 1234
    assert breakdown["system_prompt"] == baseline["system_prompt"]
    assert breakdown["total"] == (
        breakdown["system_prompt"]
        + breakdown["rules"]
        + breakdown["skills"]
        + breakdown["tools"]
        + breakdown["conversation"]
    )


def test_initial_request_tools_apply_native_deferral(tmp_path):
    engine = Engine(
        handle=EngineHandle(),
        client=object(),  # type: ignore[arg-type]
        tool_registry=ToolRegistry(),
        tool_context=ToolContext(working_directory=tmp_path),
    )
    engine.mode = "agent"

    raw_catalog = [
        _api_tool("read_file"),
        _api_tool("workflow"),
        _api_tool("write_file"),
    ]

    active = engine._initial_request_tools_for_context(raw_catalog)
    active_names = {tool["function"]["name"] for tool in active}

    assert "read_file" in active_names
    assert "workflow" in active_names
    assert "write_file" not in active_names


async def test_live_context_breakdown_counts_initial_active_tools(tmp_path):
    engine = Engine(
        handle=EngineHandle(),
        client=object(),  # type: ignore[arg-type]
        tool_registry=ToolRegistry(),
        tool_context=ToolContext(working_directory=tmp_path),
    )

    async def fake_tools_with_mcp() -> list[dict[str, object]]:
        read_file = _api_tool("read_file")
        dynamic_mcp = _api_tool("mcp__github__list_issues")
        dynamic_mcp["function"]["defer_loading"] = True  # type: ignore[index]
        return [read_file, dynamic_mcp]

    engine._get_tools_with_mcp = fake_tools_with_mcp  # type: ignore[method-assign]

    breakdown = await engine.context_breakdown_live("deepseek-chat")

    assert breakdown["tool_definitions"] > 0
    assert breakdown["mcp"] == 0
    assert breakdown["tools"] == breakdown["tool_definitions"] + breakdown["mcp"]
