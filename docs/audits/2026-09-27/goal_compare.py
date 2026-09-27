"""Alternating control-tool scan-cost comparison using the real Engine entry."""

import asyncio
import json
import statistics
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

from deepseek_tui.config.models import Config
from deepseek_tui.engine import Engine
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.goal.workspace import workspace_digest
from deepseek_tui.protocol.responses import ToolCall


async def main():
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        for i in range(8):
            (root / f"{i}.txt").write_bytes(b"x" * (1024 * 1024))
        cfg = Config()
        for name in ("tasks", "subagents", "mcp", "automations", "plugins", "exec_policy"):
            setattr(cfg.features, name, False)
        with patch.dict(
            "os.environ",
            {"DEEPSEEK_HOME": str(root / "home"), "CLAUDE_PLUGINS_DIR": str(root / "plugins")},
        ):
            engine = await Engine.create(
                handle=EngineHandle(), client=AsyncMock(), config=cfg, working_directory=root
            )
            try:
                engine.goal_service.create("inspect status")
                tools = engine.tool_registry.to_api_tools()
                samples = {"previous_scan_model": [], "current_control_entry": []}
                for i in range(10):
                    for label in list(samples) if i % 2 == 0 else list(reversed(samples)):
                        start = time.perf_counter()
                        if label == "previous_scan_model":
                            await asyncio.to_thread(workspace_digest, root)
                        result = await engine._execute_single_tool(
                            ToolCall(id=f"{i}-{label}", name="GetGoal", arguments={}),
                            tools,
                            "deepseek-chat",
                        )
                        assert result.success
                        if label == "previous_scan_model":
                            await asyncio.to_thread(workspace_digest, root)
                        samples[label].append((time.perf_counter() - start) * 1000)
                print(
                    json.dumps(
                        {
                            key: {
                                "samples": len(values),
                                "median_ms": round(statistics.median(values), 3),
                            }
                            for key, values in samples.items()
                        },
                        indent=2,
                    )
                )
            finally:
                engine.handle.drain_events()
                await engine.shutdown_session()


if __name__ == "__main__":
    asyncio.run(main())
