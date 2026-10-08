"""Run Octop's installer in an owned process group with bounded status output."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from contextlib import suppress
from typing import Any


class BrowserInstaller:
    def __init__(self):
        self.task: asyncio.Task | None = None
        self.state: dict[str, Any] = {"status": "idle", "logs": [], "error": None}

    def start(self) -> dict[str, Any]:
        if self.task and not self.task.done():
            return self.state
        self.state = {"status": "running", "logs": [], "error": None}
        self.task = asyncio.create_task(self._run())
        return self.state

    async def close(self) -> None:
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.state["status"] = "stopped"

    async def _run(self) -> None:
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "deepseek_tui.browser_install",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=os.name != "nt",
            )

            async def consume() -> None:
                assert process.stdout
                success = False
                while line := await process.stdout.readline():
                    text = line.decode(errors="replace").strip()
                    try:
                        event = json.loads(text)
                    except ValueError:
                        event = {"log": text}
                    if not isinstance(event, dict):
                        continue
                    if event.get("log"):
                        self.state["logs"].append(str(event["log"])[-2000:])
                        self.state["logs"] = self.state["logs"][-40:]
                    if event.get("done"):
                        success = event.get("success") is True
                        self.state["error"] = event.get("error")
                code = await process.wait()
                if code != 0 or not success:
                    raise RuntimeError(self.state["error"] or "Browser installation failed")

            await asyncio.wait_for(consume(), timeout=900)
            self.state["status"] = "passed"
        except asyncio.CancelledError:
            self.state["status"] = "stopped"
            raise
        except Exception as exc:
            self.state.update(status="failed", error=str(exc) or type(exc).__name__)
        finally:
            if process:
                if os.name != "nt":
                    with suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                elif process.returncode is None:
                    killer = await asyncio.create_subprocess_exec(
                        "taskkill",
                        "/PID",
                        str(process.pid),
                        "/T",
                        "/F",
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    await killer.wait()
                await process.wait()


async def _worker() -> None:
    try:
        from octop_browser.install import install_chromium_stream

        async for event in install_chromium_stream():
            print(json.dumps(event), flush=True)
    except Exception as exc:
        print(json.dumps({"done": True, "success": False, "error": str(exc)}), flush=True)


if __name__ == "__main__":
    asyncio.run(_worker())
