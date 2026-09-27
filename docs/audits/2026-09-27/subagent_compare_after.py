"""Offline comparison: event-driven wait versus joining one driver's completion.

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


async def trial(root, use_wait):
    async def execute(agent, cancel):
        await asyncio.sleep(0.003)
        return AgentRunOutput(text="### SUMMARY\n1 result")
    manager = SubAgentManager(root, executor=execute)
    child = await manager.spawn(SpawnRequest(
        prompt="probe", agent_type=SubAgentType.EXPLORE,
        assignment=SubAgentAssignment(objective="probe"),
    ))
    start = time.perf_counter()
    if use_wait:
        result = (await manager.wait([child.agent_id], "all", 1000))[0]
    else:
        await asyncio.shield(manager._agents[child.agent_id].task)
        result = await manager.get_result(child.agent_id)
    elapsed = 1000 * (time.perf_counter() - start)
    assert result.status.kind.value == "completed"
    await manager.shutdown()
    return elapsed


async def main(root):
    values = {"event_wait": [], "join_single_driver": []}
    for _ in range(20):
        for name, use_wait in (("event_wait", True), ("join_single_driver", False)):
            values[name].append(await trial(root, use_wait))
    return {name: {"samples": len(times), "median_ms": round(statistics.median(times), 3),
                   "max_ms": round(max(times), 3)} for name, times in values.items()}


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="subagent-compare-") as directory:
        print(json.dumps(asyncio.run(main(Path(directory))), indent=2))
