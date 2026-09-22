"""send_input to a terminal agent resumes it instead of erroring."""

import asyncio

from deepseek_tui.tools.subagent.agent import _stub_executor
from deepseek_tui.tools.subagent.manager import SubAgentManager
from deepseek_tui.tools.subagent.types import (
    SpawnRequest,
    SubAgentAssignment,
    SubAgentStatusKind,
    SubAgentType,
)


async def _spawn_to_completion(manager: SubAgentManager, prompt: str):
    spawned = await manager.spawn(
        SpawnRequest(
            prompt=prompt,
            agent_type=SubAgentType.EXPLORE,
            assignment=SubAgentAssignment(objective=prompt, role="qa"),
        )
    )
    agent = manager._agents[spawned.agent_id]
    await asyncio.wait_for(agent.task, 5)
    assert agent.status.kind is SubAgentStatusKind.COMPLETED
    return agent


async def test_send_input_to_completed_agent_resumes(tmp_path):
    manager = SubAgentManager(
        workspace=tmp_path, executor=_stub_executor, state_path=None
    )
    agent = await _spawn_to_completion(manager, "inspect")

    await manager.send_input(agent.id, "follow-up question")
    assert agent.status.kind is SubAgentStatusKind.RUNNING
    assert agent.input_queue.qsize() == 1
    await asyncio.wait_for(agent.task, 5)
    assert agent.status.kind is SubAgentStatusKind.COMPLETED
