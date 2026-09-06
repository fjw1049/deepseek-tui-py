"""One experiment per process: imports the current product code afresh."""

import asyncio
import json
import signal
import sys
from pathlib import Path

from evals.runner import RunOptions, run_evaluations


async def main(path: Path) -> None:
    data = json.loads(await asyncio.to_thread(path.read_text))
    data["output_dir"] = Path(data["output_dir"])
    data["case_ids"] = tuple(data["case_ids"])
    task = asyncio.create_task(run_evaluations(RunOptions(**data)))
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, task.cancel)
    await task


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1])))
