"""Workbench browser sessions backed by octop-browser 1.0.0.

Session capture/control adapted from Octop's browser/harness.py and stream.py.
See THIRD_PARTY_NOTICES.md. The private CDP bridge is contained in this module.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import shutil
import socket
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BrowserAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal[
        "open",
        "observe",
        "click",
        "fill",
        "press",
        "scroll",
        "screenshot",
        "check_text",
        "record_start",
        "record_stop",
    ]
    url: str = Field(default="", max_length=4096)
    ref: str | None = Field(default=None, max_length=200)
    selector: str | None = Field(default=None, max_length=1000)
    text: str = Field(default="", max_length=8000)
    key: str = Field(default="Enter", max_length=50)
    x: int | None = Field(default=None, ge=0, lt=1200)
    y: int | None = Field(default=None, ge=0, lt=760)
    direction: Literal["up", "down", "left", "right"] = "down"
    amount: int = Field(default=300, ge=1, le=1200)

    @model_validator(mode="after")
    def validate_action(self) -> BrowserAction:
        if self.action == "open":
            parsed = urlsplit(self.url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("Only http/https pages can be opened")
            if parsed.username or parsed.password:
                raise ValueError("Credentials in URLs are not supported")
        if self.action == "click" and not (
            self.ref or self.selector or (self.x is not None and self.y is not None)
        ):
            raise ValueError("click requires ref, selector, or x and y")
        if self.action == "fill" and not (self.ref or self.selector):
            raise ValueError("fill requires ref or selector")
        if self.action == "check_text" and not self.text.strip():
            raise ValueError("check_text requires non-empty text")
        return self


@dataclass
class BrowserRun:
    thread_id: str
    directory: Path
    session: Any = None
    owner: str = "agent"
    generation: int = 0
    revision: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    log: list[dict[str, Any]] = field(default_factory=list)
    recording: bool = False
    frames: list[bytes] = field(default_factory=list)
    artifacts: list[dict[str, str]] = field(default_factory=list)
    demo_task: asyncio.Task[Any] | None = None
    demo_status: str = "idle"
    error: str | None = None


class BrowserService:
    def __init__(self, artifact_root: Path):
        self.artifact_root = artifact_root
        self.runs: dict[str, BrowserRun] = {}

    async def ensure(self, thread_id: str) -> BrowserRun:
        if thread_id not in self.runs:
            if len(self.runs) >= 8:
                raise ValueError("Close an existing browser session first (maximum 8)")
            self.runs[thread_id] = BrowserRun(
                thread_id, Path(tempfile.mkdtemp(prefix="deepseek-browser-"))
            )
            self.runs[thread_id].artifacts = self._saved_state(thread_id).get("artifacts", [])
        run = self.runs[thread_id]
        async with run.lock:
            if run.owner == "stopped":
                raise ValueError("Browser session has stopped")
            if run.session is None:
                try:
                    from octop_browser import BrowserSession, OctopSettings
                    from octop_browser.profile import ProfileManager
                except ImportError as exc:
                    shutil.rmtree(run.directory, ignore_errors=True)
                    self.runs.pop(thread_id, None)
                    raise ValueError(
                        "Browser requires Python 3.11+ and: uv sync --extra browser"
                    ) from exc
                # Each run owns a new profile and port; never attach to the user's 9222.
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1", 0))
                    port = sock.getsockname()[1]
                cfg = OctopSettings(
                    profiles_dir=run.directory,
                    cdp_port_start=port,
                    cdp_ws_url=None,
                    cdp_host="localhost",
                    viewport_width=1200,
                    viewport_height=760,
                )
                # websockets >= 15 inherits OS proxy settings. CDP must stay local.
                bypass = ",".join(
                    filter(
                        None,
                        [
                            os.environ.get("no_proxy"),
                            os.environ.get("NO_PROXY"),
                            "localhost,127.0.0.1,::1",
                        ],
                    )
                )
                os.environ["no_proxy"] = os.environ["NO_PROXY"] = bypass
                profiles = ProfileManager(base_dir=run.directory, settings=cfg)
                try:
                    run.session = await asyncio.wait_for(
                        BrowserSession.create(
                            profile="workbench",
                            mode="headless",
                            settings=cfg,
                            profile_manager=profiles,
                        ),
                        timeout=40,
                    )
                except BaseException:
                    from octop_browser.cdp.launcher import terminate_browser

                    await terminate_browser(
                        profiles.get_or_create("workbench"), cdp_host="localhost"
                    )
                    shutil.rmtree(run.directory, ignore_errors=True)
                    self.runs.pop(thread_id, None)
                    raise
        return run

    def state(self, thread_id: str) -> dict[str, Any]:
        run = self.runs.get(thread_id)
        if run is None:
            return {
                "active": False,
                "owner": "agent",
                "log": [],
                "artifacts": [],
                "recording": False,
                "demo_status": "idle",
                "error": None,
                **self._saved_state(thread_id),
            }
        return {
            "active": run.session is not None,
            "owner": run.owner,
            "recording": run.recording,
            "log": run.log[-80:],
            "artifacts": run.artifacts[-12:],
            "demo_status": run.demo_status,
            "error": run.error,
        }

    def _saved_state(self, thread_id: str) -> dict[str, Any]:
        path = self.artifact_root / thread_id / "result.json"
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            if saved.get("demo_status") == "running":
                saved["demo_status"] = "interrupted"
            return saved
        except (FileNotFoundError, ValueError):
            return {}

    def _persist(self, run: BrowserRun) -> None:
        from deepseek_tui.utils import write_text_atomic

        directory = self.artifact_root / run.thread_id
        directory.mkdir(parents=True, exist_ok=True)
        write_text_atomic(
            directory / "result.json",
            json.dumps(
                {
                    "log": run.log[-80:],
                    "artifacts": run.artifacts[-12:],
                    "demo_status": run.demo_status,
                    "error": run.error,
                },
                ensure_ascii=False,
            ),
        )

    def approval_scope(self, thread_id: str) -> str:
        run = self.runs.get(thread_id)
        return f"{run.directory.name}:{run.generation}:{run.revision}" if run else "new"

    async def _capture(self, run: BrowserRun) -> bytes:
        # Adapted from Octop stream._capture_jpeg; same CDP session as the actions.
        data = await asyncio.wait_for(
            run.session._internal.client.send(
                "Page.captureScreenshot", {"format": "jpeg", "quality": 75}
            ),
            timeout=4,
        )
        return base64.b64decode(data["data"], validate=True)

    async def frame(self, thread_id: str) -> str | None:
        run = self.runs.get(thread_id)
        if not run or not run.session or run.lock.locked():
            return None
        async with run.lock:
            return "data:image/jpeg;base64," + base64.b64encode(await self._capture(run)).decode()

    def _save(self, run: BrowserRun, data: bytes, suffix: str, label: str) -> dict[str, str]:
        directory = self.artifact_root / run.thread_id
        directory.mkdir(parents=True, exist_ok=True)
        name = uuid.uuid4().hex + suffix
        path = directory / name
        path.write_bytes(data)
        artifact = {"id": name, "path": str(path), "label": label}
        run.artifacts.append(artifact)
        return artifact

    def artifact(self, thread_id: str, name: str) -> Path:
        path = self.artifact_root / thread_id / name
        if Path(name).name != name or path.suffix not in {".jpg", ".gif"} or not path.is_file():
            raise ValueError("Artifact not found")
        return path

    def _finish_recording(self, run: BrowserRun) -> dict[str, str] | None:
        from PIL import Image

        run.recording = False
        frames, run.frames = run.frames, []
        if not frames:
            return None
        images = []
        for frame in frames:
            with Image.open(io.BytesIO(frame)) as image:
                image.thumbnail((960, 608))
                images.append(image.convert("RGB"))
        output = io.BytesIO()
        images[0].save(
            output, format="GIF", save_all=True, append_images=images[1:], duration=900, loop=0
        )
        return self._save(run, output.getvalue(), ".gif", "步骤动图")

    async def action(
        self, thread_id: str, action: BrowserAction, *, actor: str = "agent"
    ) -> dict[str, Any]:
        run = self.runs.get(thread_id)
        if run is None or run.session is None:
            if action.action != "open":
                raise ValueError("Open a browser page first")
            run = await self.ensure(thread_id)
        generation = run.generation
        async with run.lock:
            if run.owner != actor or run.generation != generation:
                raise ValueError("Browser control changed; queued action was discarded")
            if not run.session:
                raise ValueError("Browser session has closed")
            return await asyncio.wait_for(self._action(run, action), timeout=35)

    async def _action(self, run: BrowserRun, a: BrowserAction) -> dict[str, Any]:
        run.revision += 1
        s = run.session
        artifact = None
        success = True
        if a.action == "open":
            result = await s.navigate(a.url)
        elif a.action == "observe":
            result = await s.dom_tree(level="full")
        elif a.action == "click":
            result = await s.click(ref=a.ref, selector=a.selector, x=a.x, y=a.y)
        elif a.action == "fill":
            result = await s.fill(text=a.text, ref=a.ref, selector=a.selector)
        elif a.action == "press":
            result = await s.press(a.key)
        elif a.action == "scroll":
            result = await s.scroll(direction=a.direction, amount=a.amount)
        elif a.action == "check_text":
            result = await s.eval_js("document.body.innerText")
            body = json.loads(result.content) if isinstance(result.content, str) else ""
            success = result.success and a.text in body
            result = None
        else:
            result = None
        if result is not None:
            success = result.success
            content = result.content if success else result.error
        elif a.action == "check_text":
            content = ("PASS: " if success else "FAIL: ") + a.text
        else:
            content = a.action
        if a.action == "record_start":
            run.frames.clear()
            run.recording = True
        if a.action == "screenshot":
            artifact = self._save(run, await self._capture(run), ".jpg", "页面截图")
        if run.recording:
            run.frames.append(await self._capture(run))
            if len(run.frames) >= 40:
                artifact = self._finish_recording(run)
        if a.action == "record_stop":
            artifact = self._finish_recording(run)
        # Never log typed values or full DOM text; only action outcomes.
        run.log.append({"action": a.action, "success": success})
        run.log[:] = run.log[-80:]
        self._persist(run)
        return {"success": success, "content": content, "artifact": artifact}

    async def control(self, thread_id: str, owner: str) -> dict[str, Any]:
        if owner not in {"agent", "user", "stopped"}:
            raise ValueError("Invalid control owner")
        run = self.runs.get(thread_id)
        if not run:
            raise ValueError("Open a browser page first")
        run.owner = owner
        run.generation += 1
        if run.demo_task and not run.demo_task.done():
            run.demo_task.cancel()
            await asyncio.gather(run.demo_task, return_exceptions=True)
            run.demo_status = "stopped"
        # Wait for the current atomic action; pending actions fail the generation check.
        async with run.lock:
            pass
        if owner == "stopped":
            await self.close(thread_id)
        return self.state(thread_id)

    async def start_demo(self, thread_id: str) -> dict[str, Any]:
        run = await self.ensure(thread_id)
        if run.owner != "agent":
            raise ValueError("Return control to the agent before running the demo")
        if run.demo_task and not run.demo_task.done():
            raise ValueError("Demo is already running")
        run.demo_status, run.error = "running", None
        run.demo_task = asyncio.create_task(self._demo(run))
        return self.state(thread_id)

    async def _demo(self, run: BrowserRun) -> None:
        try:
            async with run.lock:
                result = await run.session.navigate(
                    (Path(__file__).parent / "browser_demo.html").as_uri()
                )
                if not result.success:
                    raise ValueError(result.error)
            steps = [
                {"action": "record_start"},
                {"action": "fill", "selector": "#name", "text": "Octop × Workbench"},
                {"action": "click", "selector": "#notifications"},
                {"action": "click", "selector": "#save"},
                {"action": "check_text", "text": "已保存：Octop × Workbench"},
                {"action": "click", "selector": "#details"},
                {"action": "check_text", "text": "通知已开启"},
                {"action": "screenshot"},
                {"action": "record_stop"},
            ]
            for step in steps:
                await asyncio.sleep(0.65)
                result = await self.action(run.thread_id, BrowserAction(**step))
                if not result["success"]:
                    raise ValueError(str(result["content"]))
            run.demo_status = "passed"
        except asyncio.CancelledError:
            run.demo_status = "stopped"
            raise
        except Exception as exc:
            run.demo_status, run.error = "failed", str(exc)
        finally:
            if run.recording:
                self._finish_recording(run)
            self._persist(run)

    async def close(self, thread_id: str) -> None:
        run = self.runs.get(thread_id)
        if not run:
            return
        run.owner = "stopped"
        run.generation += 1
        if run.demo_task and not run.demo_task.done():
            run.demo_task.cancel()
            await asyncio.gather(run.demo_task, return_exceptions=True)
        async with run.lock:
            try:
                if run.recording:
                    self._finish_recording(run)
                self._persist(run)
                if run.session:
                    await run.session.close(kill=True)
            finally:
                shutil.rmtree(run.directory, ignore_errors=True)
                self.runs.pop(thread_id, None)

    async def close_all(self) -> None:
        await asyncio.gather(*(self.close(key) for key in list(self.runs)))
