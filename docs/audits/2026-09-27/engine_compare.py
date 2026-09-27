"""Compare real parallel batch result publication with a completion-time prototype.

Fake read-only jobs, no external I/O. Input-order return values remain identical.
The prototype omits production post-processing; it is not a drop-in replacement.
"""

import asyncio
import json
import statistics
import time
from types import SimpleNamespace

from deepseek_tui.engine.orchestrator.tooling import ToolExecutionMixin
from deepseek_tui.engine.tool_dedup import ToolCallDeduplicator
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.tools.registry import ToolResult


async def trial(prototype):
    started = time.perf_counter()
    notifications = []
    calls = [
        ToolCall(id="slow", name="read_file", arguments={"path": "slow"}),
        ToolCall(id="fast", name="read_file", arguments={"path": "fast"}),
    ]

    async def execute(call, *args):
        await asyncio.sleep(0.04 if call.id == "slow" else 0.003)
        return ToolResult(content=call.id, success=True)

    async def finish(call, decision, result, model, results):
        notifications.append((call.id, 1000 * (time.perf_counter() - started)))
        results.append(result.content)

    if prototype:

        async def worker(call):
            result = await execute(call)
            notifications.append((call.id, 1000 * (time.perf_counter() - started)))
            return result.content

        results = await asyncio.gather(*(worker(call) for call in calls))
    else:
        stub = SimpleNamespace(
            _tool_dedup=ToolCallDeduplicator(),
            _execute_single_tool=execute,
            _finish_tool_result=finish,
        )
        results = await ToolExecutionMixin._execute_tools_parallel(stub, calls, [], "probe")
    assert results == ["slow", "fast"]
    return dict(notifications)["fast"], 1000 * (time.perf_counter() - started)


async def main():
    samples = {"current_gather_then_publish": [], "prototype_publish_on_completion": []}
    for _ in range(20):
        for name, prototype in zip(samples, (False, True)):
            samples[name].append(await trial(prototype))
    print(
        json.dumps(
            {
                name: {
                    "samples": len(values),
                    "fast_result_visible_median_ms": round(
                        statistics.median(v[0] for v in values), 3
                    ),
                    "batch_finished_median_ms": round(statistics.median(v[1] for v in values), 3),
                }
                for name, values in samples.items()
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
