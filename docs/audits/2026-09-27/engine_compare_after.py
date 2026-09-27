"""Compare completion publication after E08 with the former gather barrier."""

import asyncio
import json
import statistics
import time
from types import SimpleNamespace

from deepseek_tui.engine.orchestrator.tooling import ToolExecutionMixin
from deepseek_tui.engine.tool_dedup import ToolCallDeduplicator
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.tools.registry import ToolResult


async def trial(current):
    started = time.perf_counter()
    visible = {}
    calls = [
        ToolCall(id=name, name="read_file", arguments={"path": name}) for name in ("slow", "fast")
    ]

    async def execute(call, *args):
        await asyncio.sleep(0.04 if call.id == "slow" else 0.003)
        return ToolResult(content=call.id, success=True)

    async def publish(call, result):
        visible[call.id] = 1000 * (time.perf_counter() - started)

    async def finish(call, decision, result, model, results, *, emit_result=True):
        if emit_result:
            await publish(call, result)
        results.append(result.content)

    if current:
        stub = SimpleNamespace(
            _tool_dedup=ToolCallDeduplicator(),
            _execute_single_tool=execute,
            _publish_tool_result=publish,
            _finish_tool_result=finish,
        )
        results = await ToolExecutionMixin._execute_tools_parallel(stub, calls, [], "probe")
    else:
        outcomes = await asyncio.gather(*(execute(call) for call in calls))
        results = []
        for call, result in zip(calls, outcomes):
            await publish(call, result)
            results.append(result.content)
    assert results == ["slow", "fast"]
    return visible["fast"], 1000 * (time.perf_counter() - started)


async def main():
    samples = {"former_gather_barrier": [], "current_completion_publication": []}
    for _ in range(20):
        for name, current in zip(samples, (False, True)):
            samples[name].append(await trial(current))
    print(
        json.dumps(
            {
                name: {
                    "samples": len(values),
                    "fast_visible_median_ms": round(statistics.median(v[0] for v in values), 3),
                    "batch_finished_median_ms": round(statistics.median(v[1] for v in values), 3),
                }
                for name, values in samples.items()
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
