"""Synthetic on-disk task history benchmark; never reads user task records.

Run: PYTHONPATH=src .venv/bin/python scripts/benchmark-task-catalog.py --records 1000
"""

import argparse
import asyncio
import json
import statistics
import tempfile
import time
from pathlib import Path

from deepseek_tui.tools.task import NewTaskRequest, TaskManager, TaskManagerConfig
from deepseek_tui.tools.task.store import _task_record_to_dict


async def main(count: int) -> None:
    with tempfile.TemporaryDirectory(prefix="task-catalog-benchmark-") as directory:
        root = Path(directory)
        manager = TaskManager(TaskManagerConfig(data_dir=root, default_workspace=root))
        try:
            seed = await manager.add_task(NewTaskRequest(prompt="synthetic history"))
            await manager.cancel_task(seed.id)
            sample = _task_record_to_dict(seed)
            for index in range(count):
                sample["id"] = f"task_benchmark{index:06d}"
                (root / "tasks" / f"{sample['id']}.json").write_text(json.dumps(sample))
            await manager.start()
            results = {}
            for label, kwargs in (
                ("all", {"limit": 20}),
                ("active", {"active_only": True}),
                ("ten_ids", {"task_ids": [f"task_benchmark{i:06d}" for i in range(10)]}),
            ):
                elapsed = []
                for _ in range(6):
                    started = time.perf_counter()
                    await manager.list_tasks(**kwargs)
                    elapsed.append((time.perf_counter() - started) * 1000)
                results[label] = {
                    "first_ms": round(elapsed[0], 3),
                    "warm_median_ms": round(statistics.median(elapsed[1:]), 3),
                }
            print(json.dumps({"records": count + 1, "results": results}, indent=2))
        finally:
            await manager.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=int, default=1000)
    args = parser.parse_args()
    asyncio.run(main(max(10, args.records)))
