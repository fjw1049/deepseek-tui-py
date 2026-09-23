"""Registry reload must restore a runnable child, not just its status."""

import asyncio
import json

import pytest

from deepseek_tui.client.base import LLMClient, RetryConfig
from deepseek_tui.config.models import Config
from deepseek_tui.protocol.responses import StreamDone, StreamTextDelta
from deepseek_tui.tools.subagent import (
    Mailbox,
    SpawnRequest,
    SubAgentAssignment,
    SubAgentManager,
    SubAgentRuntime,
    SubAgentStatus,
    SubAgentType,
    get_real_subagent_executor,
)


class Client(LLMClient):
    def __init__(self):
        super().__init__(RetryConfig(base_delay=0, max_delay=0))
        self.requests = []

    async def stream_chat_completion(self, request):
        self.requests.append(request.model_copy(deep=True))
        yield StreamTextDelta(text="### SUMMARY\nCHECKPOINT EVIDENCE: inspected the files.")
        yield StreamDone()


def manager_for(tmp_path, client):
    mailbox = Mailbox()
    manager = SubAgentManager(
        workspace=tmp_path,
        state_path=tmp_path / "registry.json",
        mailbox=mailbox,
        executor=get_real_subagent_executor(),
    )
    manager.attach_parent_cancel(asyncio.Event())
    manager.attach_loop_runtime(
        SubAgentRuntime(
            manager=manager,
            client=client,
            model="deepseek-chat",
            config=Config(),
            workspace=tmp_path,
            mailbox=mailbox,
            auto_approve=False,
        )
    )
    return manager


@pytest.mark.parametrize("entrypoint", ["resume", "send_input"])
@pytest.mark.parametrize("was_running", [False, True])
async def test_registry_restart_resumes_real_loop_from_checkpoint(
    tmp_path, monkeypatch, entrypoint, was_running
):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    first = manager_for(tmp_path, Client())
    try:
        spawned = await first.spawn(
            SpawnRequest(
                prompt="Inspect files",
                agent_type=SubAgentType.EXPLORE,
                assignment=SubAgentAssignment(objective="Inspect files"),
                parent_depth=1,
            )
        )
        original = first._agents[spawned.agent_id]
        await original.task
        assert original.status.kind.value == "completed"
        if was_running:
            original.status = SubAgentStatus.running()
            first._persist_state()
    finally:
        await first.shutdown()

    client = Client()
    restored = manager_for(tmp_path, client)
    try:
        agent = restored._agents[spawned.agent_id]
        assert agent.status.kind.value == ("interrupted" if was_running else "completed")
        if entrypoint == "resume":
            await restored.resume(agent.id)
        else:
            await restored.send_input(agent.id, "NEW REQUIREMENT")
        await agent.task
        assert agent.status.kind.value == "completed", agent.status.message
        assert "CHECKPOINT EVIDENCE" in client.requests[0].model_dump_json()
        if entrypoint == "send_input":
            assert "NEW REQUIREMENT" in client.requests[0].model_dump_json()
        from deepseek_tui.tools.run_conversation import load_run_conversation

        history = load_run_conversation("subagent", agent.id)
        assert history["status"] == "completed"
        assert len([b for b in history["blocks"] if b.get("agentSegment") == "final_answer"]) == 2
        if entrypoint == "send_input":
            assert any(b.get("text") == "NEW REQUIREMENT" for b in history["blocks"])
        assert agent.loop_runtime.manager is restored
        assert agent.loop_runtime.client is client
        assert agent.loop_runtime.spawn_depth == 2
        assert agent.loop_runtime.auto_approve is False
        assert agent.mailbox is restored.mailbox
        assert agent.parent_cancel is restored._parent_cancel
        assert agent.id in {item.agent_id for item in restored.list_agents()}
    finally:
        await restored.shutdown()


async def test_same_process_resume_preserves_spawn_approval_override(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    manager = manager_for(tmp_path, Client())
    try:
        spawned = await manager.spawn(
            SpawnRequest(
                prompt="Inspect files",
                agent_type=SubAgentType.EXPLORE,
                assignment=SubAgentAssignment(objective="Inspect files"),
                auto_approve=True,
            )
        )
        agent = manager._agents[spawned.agent_id]
        await agent.task
        runtime = agent.loop_runtime
        assert runtime.auto_approve is True
        assert manager.loop_runtime.auto_approve is False
        await manager.resume(agent.id)
        await agent.task
        assert agent.status.kind.value == "completed", agent.status.message
        assert agent.loop_runtime is runtime
        assert agent.loop_runtime.auto_approve is True
    finally:
        await manager.shutdown()


async def test_registry_restart_preserves_agent_execution_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    first = manager_for(tmp_path, Client())
    try:
        spawned = await first.spawn(
            SpawnRequest(
                prompt="Inspect files",
                agent_type=SubAgentType.CUSTOM,
                assignment=SubAgentAssignment(objective="Inspect files"),
                allowed_tools=["read_file"],
                system_prompt="You are a specialist",
                output_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
                background=True,
            )
        )
        agent = first._agents[spawned.agent_id]
        await agent.task
        agent.max_steps_reached = True
        agent.structured_result = {"ok": True}
        first._persist_state()
    finally:
        await first.shutdown()

    restored = manager_for(tmp_path, Client())
    try:
        agent = restored._agents[spawned.agent_id]
        assert agent.system_prompt == "You are a specialist"
        assert agent.output_schema == {"type": "object", "properties": {"ok": {"type": "boolean"}}}
        assert agent.background is True
        assert agent.max_steps_reached is True
        assert agent.structured_result == {"ok": True}
    finally:
        await restored.shutdown()


async def test_registry_reads_previous_schema(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    first = manager_for(tmp_path, Client())
    try:
        spawned = await first.spawn(
            SpawnRequest(
                prompt="Inspect files",
                agent_type=SubAgentType.EXPLORE,
                assignment=SubAgentAssignment(objective="Inspect files"),
            )
        )
        await first._agents[spawned.agent_id].task
    finally:
        await first.shutdown()
    state_path = tmp_path / "registry.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["schema_version"] = 1
    for raw in state["agents"]:
        for key in (
            "system_prompt", "output_schema", "background",
            "max_steps_reached", "structured_result",
        ):
            raw.pop(key, None)
    state_path.write_text(json.dumps(state), encoding="utf-8")

    restored = manager_for(tmp_path, Client())
    try:
        assert spawned.agent_id in restored._agents
        assert restored._agents[spawned.agent_id].allowed_tools is None
    finally:
        await restored.shutdown()
