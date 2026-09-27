"""Offline comparison: polling versus joining one driver's completion.

This measures only a single live child; joining is not a production replacement
for multi-id any/all waits, resumed generations, or persisted interrupted agents.
"""
import asyncio
import json
import statistics
import tempfile
import time
from pathlib import Path

from deepseek_tui.tools.subagent import (
    AgentRunOutput, SpawnRequest, SubAgentAssignment, SubAgentManager, SubAgentType,
)


async def trial(root, poll):
    async def execute(agent, cancel):
        await asyncio.sleep(0.003)
        return AgentRunOutput(text="### SUMMARY\n1 result")
    manager = SubAgentManager(root, executor=execute)
    child = await manager.spawn(SpawnRequest(
        prompt="probe", agent_type=SubAgentType.EXPLORE,
        assignment=SubAgentAssignment(objective="probe"),
    ))
    start = time.perf_counter()
    if poll:
        result = (await manager.wait([child.agent_id], "all", 1000))[0]
    else:
        await asyncio.shield(manager._agents[child.agent_id].task)
        result = await manager.get_result(child.agent_id)
    elapsed = 1000 * (time.perf_counter() - start)
    assert result.status.kind.value == "completed"
    await manager.shutdown()
    return elapsed


async def main(root):
    values = {"poll_50ms": [], "join_single_driver": []}
    for _ in range(20):
        for name, poll in (("poll_50ms", True), ("join_single_driver", False)):
            values[name].append(await trial(root, poll))
    return {name: {"samples": len(times), "median_ms": round(statistics.median(times), 3),
                   "max_ms": round(max(times), 3)} for name, times in values.items()}


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="subagent-compare-") as directory:
        print(json.dumps(asyncio.run(main(Path(directory))), indent=2))
