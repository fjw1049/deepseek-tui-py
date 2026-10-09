from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.client.base import LLMClient, RetryConfig
from deepseek_tui.config.models import Config, ProviderConfig
from deepseek_tui.protocol.responses import StreamDone, StreamTextDelta
from deepseek_tui.tools.registry import ToolRegistry
from deepseek_tui.tools.subagent import (
    SpawnRequest,
    SubAgentAssignment,
    SubAgentManager,
    SubAgentRuntime,
    SubAgentType,
    get_real_subagent_executor,
)
from deepseek_tui.tools.task import TaskManager, TaskManagerConfig
from deepseek_tui.tools.task.tools import TaskCreateTool

pytestmark = pytest.mark.asyncio


def cfg(name):
    return Config(
        provider=name,
        providers={
            p: ProviderConfig(
                model=p + "-model", base_url="https://" + p + ".invalid/v1", api_key="fake"
            )
            for p in ("alpha", "beta")
        },
    )


class Client(LLMClient):
    def __init__(self):
        super().__init__(RetryConfig(base_delay=0, max_delay=0))
        self.requests = []

    async def stream_chat_completion(self, request):
        self.requests.append(request)
        yield StreamTextDelta(text="### SUMMARY\nVerified without a network call.")
        yield StreamDone()


def manager(path, config, client, task_manager=None):
    m = SubAgentManager(
        workspace=path,
        state_path=path / "state.json",
        default_model=config.effective_provider_config().model,
        executor=get_real_subagent_executor(),
    )
    m.attach_loop_runtime(
        SubAgentRuntime(
            manager=m,
            client=client,
            model=m.default_model,
            config=config,
            workspace=path,
            task_manager=task_manager,
        )
    )
    return m


def req(**kw):
    return SpawnRequest(
        prompt="inspect",
        agent_type=SubAgentType.GENERAL,
        assignment=SubAgentAssignment(objective="inspect"),
        **kw,
    )


async def test_restart_preserves_provider_and_model(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    a = manager(tmp_path, cfg("alpha"), Client())
    s = await a.spawn(req())
    await a._agents[s.agent_id].task
    await a.shutdown()
    c = Client()
    restored_client = Client()
    routes = []

    def build(config):
        routes.append(config)
        return restored_client

    monkeypatch.setattr("deepseek_tui.client.factory.build_llm_client", build)
    b = manager(tmp_path, cfg("beta"), c)
    try:
        await b.resume(s.agent_id)
        await b._agents[s.agent_id].task
        assert b._agents[s.agent_id].loop_runtime.config.provider == "beta"
        assert not c.requests
        assert restored_client.requests[0].model == "alpha-model"
        assert routes[0].provider == "alpha"
        assert routes[0].effective_provider_config().base_url == "https://alpha.invalid/v1"
    finally:
        await b.shutdown()


async def test_task_from_child_inherits_child_route(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    tm = TaskManager(
        TaskManagerConfig(
            data_dir=tmp_path / "tasks", default_workspace=tmp_path, config=cfg("alpha")
        )
    )
    contexts = []
    original = ToolRegistry.set_context

    def capture(self, ctx):
        contexts.append(ctx)
        return original(self, ctx)

    monkeypatch.setattr(ToolRegistry, "set_context", capture)
    m = manager(tmp_path, cfg("beta"), Client(), tm)
    try:
        s = await m.spawn(req())
        await m._agents[s.agent_id].task
        ctx = next(c for c in contexts if c.metadata.get("subagent_id") == s.agent_id)
        r = await TaskCreateTool().execute({"prompt": "nested task"}, ctx)
        task = await tm.get_task(r.metadata["task_id"])
        assert (task.provider, task.model) == ("beta", "beta-model")
        assert ctx.metadata["subagent_runtime"].config.provider == "beta"
    finally:
        await m.shutdown()
        await tm.shutdown()


async def test_nested_spawn_inherits_parent_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    from deepseek_tui.tools.subagent.tools import AgentTool

    contexts = []
    original = ToolRegistry.set_context

    def capture(self, ctx):
        contexts.append(ctx)
        return original(self, ctx)

    monkeypatch.setattr(ToolRegistry, "set_context", capture)
    m = manager(tmp_path, cfg("alpha"), Client())
    beta = Client()
    monkeypatch.setattr("deepseek_tui.client.factory.build_llm_client", lambda _: beta)
    try:
        s = await m.spawn(req(model="beta::beta-model"))
        await m._agents[s.agent_id].task
        ctx = next(c for c in contexts if c.metadata.get("subagent_id") == s.agent_id)
        assert ctx.metadata["subagent_runtime"].config.provider == "beta"
        before = set(m._agents)
        await AgentTool().execute({"action": "spawn", "prompt": "nested agent"}, ctx)
        child = m._agents[(set(m._agents) - before).pop()]
        await child.task
        assert child.loop_runtime.config.provider == "beta"
        assert child.model == "beta-model"
    finally:
        await m.shutdown()


async def test_narration_inherits_selected_model():
    from deepseek_tui.server.phase_bridge import resolve_narration_model

    assert (
        resolve_narration_model(Config(provider="glm", model="selected-custom-model"))
        == "selected-custom-model"
    )
    assert resolve_narration_model(cfg("alpha")) == "alpha-model"


async def test_no_key_subagent_never_returns_synthetic_success(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    from deepseek_tui.tools.runtime import build_subagent_manager

    c = Config(
        provider="audit_missing_key",
        providers={
            "audit_missing_key": ProviderConfig(
                model="custom-model", base_url="https://invalid.test/v1"
            )
        },
    )
    m, mailbox = build_subagent_manager(c, tmp_path, state_path=tmp_path / "registry.json")
    parent = cfg("alpha")
    parent.providers.update(c.providers)
    m.attach_loop_runtime(
        SubAgentRuntime(
            manager=m,
            client=Client(),
            model="alpha-model",
            config=parent,
            workspace=tmp_path,
        )
    )
    try:
        s = await m.spawn(req(model="audit_missing_key::custom-model"))
        agent = m._agents[s.agent_id]
        await agent.task
        assert agent.status.kind.value == "failed"
        assert not agent.result
        assert "API key" in agent.status.message
        from deepseek_tui.client.factory import MissingApiKeyError, build_llm_client

        with pytest.raises(MissingApiKeyError):
            build_llm_client(c)
    finally:
        await m.shutdown()
        mailbox.close()


async def test_legacy_child_without_provider_uses_complete_current_route(tmp_path):
    from deepseek_tui.tools.subagent.store import agent_record, restore_agent

    m = manager(tmp_path, cfg("alpha"), Client())
    try:
        spawned = await m.spawn(req())
        original = m._agents[spawned.agent_id]
        await original.task
        record = agent_record(original)
        assert record["provider"] == "alpha"
        assert "fake" not in str(record)
        record.pop("provider")
        restored = restore_agent(record, tmp_path, "beta-model")
        assert restored.model == "beta-model"
    finally:
        await m.shutdown()


@pytest.mark.parametrize("model", ["beta::beta-model", "arbitrary-model"])
async def test_plugin_persona_accepts_generic_models(tmp_path, monkeypatch, model):
    from deepseek_tui.tools.registry import ToolContext
    from deepseek_tui.tools.subagent.tools import AgentTool

    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    m = manager(tmp_path, cfg("alpha"), Client())
    monkeypatch.setattr("deepseek_tui.client.factory.build_llm_client", lambda _: Client())
    persona = SimpleNamespace(
        name="specialist", plugin="demo", body="Inspect files", model=model, tools=[]
    )
    ctx = ToolContext(
        working_directory=tmp_path,
        subagent_manager=m,
        metadata={"plugin_agents": {"specialist": persona}, "plugin_trust": {"demo": True}},
    )
    try:
        await AgentTool().execute(
            {"action": "spawn", "agent_type": "specialist", "prompt": "inspect"}, ctx
        )
        agent = next(iter(m._agents.values()))
        await agent.task
        assert agent.model == model
        assert agent.provider == ("beta" if "::" in model else "alpha")
        assert agent.status.kind.value == "completed", agent.status.message
    finally:
        await m.shutdown()


async def test_narration_override_routes_and_closes_client(tmp_path, monkeypatch):
    from deepseek_tui.server.phase_bridge import (
        NarrationPlan,
        ReasoningSegment,
        TurnNarrationState,
        compute_narration_display,
    )

    config = cfg("alpha")
    config.ui.process_narration.model = "beta::beta-model"
    owned = SimpleNamespace(close=AsyncMock())
    routes = []

    def build(c):
        routes.append(c)
        return owned

    monkeypatch.setattr("deepseek_tui.client.factory.build_llm_client", build)
    plan = AsyncMock(
        return_value=NarrationPlan(publish=True, phase="verify", finding="Verified", next_goal="")
    )
    monkeypatch.setattr("deepseek_tui.server.phase_bridge.compute_narration_plan", plan)
    await compute_narration_display(
        Client(),
        config,
        user_goal="inspect",
        state=TurnNarrationState(),
        segment=ReasoningSegment(item_id="one", text="read files"),
        tool_calls=(),
        recent_tool_results=(),
        locale="en",
    )
    assert routes[0].provider == "beta"
    assert plan.call_args.args[0] is owned
    assert plan.call_args.kwargs["model"] == "beta-model"
    owned.close.assert_awaited_once()
