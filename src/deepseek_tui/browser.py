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
import sys
import tempfile
import uuid
import zipfile
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
        "select",
        "set_checked",
        "press",
        "scroll",
        "screenshot",
        "check_text",
        "record_start",
        "record_stop",
        "video_start",
        "video_stop",
    ]
    url: str = Field(default="", max_length=4096)
    ref: str | None = Field(default=None, max_length=200)
    selector: str | None = Field(default=None, max_length=1000)
    text: str = Field(default="", max_length=8000)
    checked: bool | None = None
    key: str = Field(default="Enter", max_length=50)
    x: int | None = Field(default=None, ge=0, lt=1200)
    y: int | None = Field(default=None, ge=0, lt=760)
    direction: Literal["up", "down", "left", "right"] = "down"
    amount: int = Field(default=300, ge=1, le=1200)
    timeout_ms: int = Field(default=0, ge=0, le=10000)

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
        if self.action in {"fill", "select"} and not (self.ref or self.selector):
            raise ValueError("fill requires ref or selector")
        if self.action == "set_checked" and (not self.selector or self.checked is None):
            raise ValueError("set_checked requires selector and checked")
        if self.action == "check_text" and not self.text.strip():
            raise ValueError("check_text requires non-empty text")
        return self


@dataclass
class BrowserRun:
    thread_id: str
    directory: Path
    session: Any = None
    settings: Any = None
    profiles: Any = None
    recorder: Any = None
    activity: str = "demo"
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
    demo_step: int = 0
    demo_total: int = 9
    error: str | None = None
    url: str = ""
    video: Any = None
    video_error: str | None = None


class BrowserService:
    def __init__(self, artifact_root: Path):
        from deepseek_tui.browser_install import BrowserInstaller

        self.artifact_root = artifact_root
        self.installer = BrowserInstaller()
        self.runs: dict[str, BrowserRun] = {}

    def preferences(self, thread_id: str) -> dict[str, bool]:
        path = self.artifact_root / thread_id / "preferences.json"
        return json.loads(path.read_text()) if path.exists() else {"persistent": False}

    def configure(self, thread_id: str, persistent: bool) -> dict[str, bool]:
        from deepseek_tui.utils import write_text_atomic

        if thread_id in self.runs:
            raise ValueError("End the browser session before changing storage settings")
        path = self.artifact_root / thread_id / "preferences.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(path, json.dumps({"persistent": persistent}))
        return self.preferences(thread_id)

    def environment(self) -> dict[str, Any]:
        import importlib.metadata

        result: dict[str, Any] = {
            "python": sys.version.split()[0],
            "ready": False,
            "video_ready": bool(shutil.which("ffmpeg")),
        }
        try:
            from octop_browser.cdp.launcher import find_chrome

            result["octop"] = importlib.metadata.version("octop-browser")
            result["browser"] = find_chrome()
            result["ready"] = bool(result["browser"])
            result["message"] = "Ready" if result["ready"] else "Install Chrome or Chromium"
        except ImportError:
            result["message"] = "Use Python 3.11+ and uv sync --extra browser"
        return result

    async def recover(self, thread_id: str) -> dict[str, Any]:
        try:
            await self.close(thread_id)
        except (RuntimeError, TimeoutError, ConnectionError):
            pass
        await self.ensure(thread_id)
        return await self.control(thread_id, "user")

    def clear_profile(self, thread_id: str) -> None:
        if thread_id in self.runs:
            raise ValueError("End the browser session before clearing saved login data")
        shutil.rmtree(self.artifact_root / thread_id / "profile", ignore_errors=True)

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
                profile_dir = run.directory
                if self.preferences(thread_id)["persistent"]:
                    profile_dir = self.artifact_root / thread_id / "profile"
                    profile_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
                cfg = OctopSettings(
                    profiles_dir=profile_dir,
                    cdp_port_start=port,
                    cdp_ws_url=None,
                    cdp_host="localhost",
                    viewport_width=1200,
                    viewport_height=760,
                )
                # websockets >= 15 inherits OS proxy settings. CDP must stay local.
                bypass = ",".join(
                    dict.fromkeys(
                        filter(
                            None,
                            (
                                os.environ.get("no_proxy", "")
                                + ","
                                + os.environ.get("NO_PROXY", "")
                                + ",localhost,127.0.0.1,::1"
                            ).split(","),
                        )
                    )
                )
                os.environ["no_proxy"] = os.environ["NO_PROXY"] = bypass
                profiles = ProfileManager(base_dir=profile_dir, settings=cfg)
                profiles.get_or_create("workbench").cdp_port = port
                run.settings, run.profiles = cfg, profiles
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
            "url": run.url,
            "video_recording": run.video is not None,
            "video_error": run.video_error,
            "owner": run.owner,
            "recording": run.recording,
            "log": run.log[-80:],
            "artifacts": run.artifacts[-12:],
            "demo_status": run.demo_status,
            "activity": run.activity,
            "workflow_recording": run.recorder is not None,
            "demo_step": run.demo_step,
            "demo_total": run.demo_total,
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
                    "activity": run.activity,
                    "demo_step": run.demo_step,
                    "demo_total": run.demo_total,
                    "error": run.error,
                    "url": run.url,
                    "video_error": run.video_error,
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
            tree = await run.session._internal.client.send("Page.getFrameTree")
            run.url = tree.get("frameTree", {}).get("frame", {}).get("url", run.url)
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
        if (
            Path(name).name != name
            or path.suffix not in {".jpg", ".gif", ".webm"}
            or path.is_symlink()
            or not path.is_file()
        ):
            raise ValueError("Artifact not found")
        return path

    async def start_video(self, run: BrowserRun) -> None:
        from deepseek_tui.browser_video import BrowserVideo

        if run.video:
            raise ValueError("Video is already recording")
        directory = self.artifact_root / run.thread_id
        directory.mkdir(parents=True, exist_ok=True)
        video = BrowserVideo(directory / (uuid.uuid4().hex + ".webm"), lambda: self._capture(run))
        await video.start()
        run.video, run.video_error = video, None

    async def stop_video(self, run: BrowserRun) -> dict[str, str] | None:
        video = run.video
        if not video:
            return None
        await video.stop()
        run.video = None
        run.video_error = video.error
        if (
            video.frames
            and video.process.returncode == 0
            and video.path.is_file()
            and video.path.stat().st_size
        ):
            artifact = {"id": video.path.name, "path": str(video.path), "label": "连续视频"}
            run.artifacts.append(artifact)
            self._persist(run)
            return artifact
        video.path.unlink(missing_ok=True)
        self._persist(run)
        return None

    def export_evidence(self, thread_id: str) -> Path:
        state = self.state(thread_id)
        if state.get("video_recording") or state.get("demo_status") == "running":
            raise ValueError("Stop recording and finish the current run before exporting")
        if not state["artifacts"] and not state["log"]:
            raise ValueError("No browser evidence to export")
        directory = self.artifact_root / thread_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / ("evidence-" + uuid.uuid4().hex + ".zip")
        report = {
            key: state.get(key)
            for key in (
                "url",
                "activity",
                "demo_status",
                "demo_step",
                "demo_total",
                "error",
                "video_error",
            )
        }
        checks = [entry for entry in state["log"] if entry["action"] == "check_text"]
        report["assertions"] = checks
        report["verification"] = (
            "failed"
            if any(not check["success"] for check in checks)
            else "passed"
            if checks
            else "not_checked"
        )
        report["steps"] = state["log"]
        report["artifacts"] = [
            {"id": item["id"], "label": item["label"]} for item in state["artifacts"]
        ]
        try:
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("report.json", json.dumps(report, ensure_ascii=False, indent=2))
                archive.writestr(
                    "README.txt",
                    (
                        "Browser acceptance evidence\n"
                        "report.json: execution outcomes and explicit text assertions.\n"
                        "verification=not_checked means no business text assertion was executed.\n"
                        "Includes the latest 80 steps and 12 artifacts retained by this session.\n"
                        "Video: 5 fps, maximum 180 seconds; GIF: post-action snapshots.\n"
                        "Pages, assertions and images may contain private data.\n"
                        "Review before sharing.\n"
                    ),
                )
                for item in state["artifacts"]:
                    archive.write(self.artifact(thread_id, item["id"]), item["id"])
        except BaseException:
            path.unlink(missing_ok=True)
            raise
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
            try:
                return await asyncio.wait_for(self._action(run, action), timeout=35)
            except (Exception, asyncio.CancelledError) as exc:
                run.log.append({"action": action.action, "success": False})
                run.log[:] = run.log[-80:]
                run.error = (
                    "Action interrupted"
                    if isinstance(exc, asyncio.CancelledError)
                    else str(exc) or type(exc).__name__
                )
                self._persist(run)
                raise

    async def _action(self, run: BrowserRun, a: BrowserAction) -> dict[str, Any]:
        if a.action == "record_start" and run.recording:
            raise ValueError("Recording is already running; finish it before starting again")
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
        elif a.action == "select":
            result = await s.select(value=a.text, ref=a.ref, selector=a.selector)
        elif a.action == "set_checked":
            result = await s.eval_js(
                "(() => { const els = document.querySelectorAll("
                + json.dumps(a.selector)
                + "); return els.length === 1 ? els[0].checked ?? null : null; })()"
            )
            checked = json.loads(result.content) if result.success else None
            if not isinstance(checked, bool):
                raise ValueError("Checkbox selector must match one checkable element")
            if checked != a.checked:
                result = await s.click(selector=a.selector)
        elif a.action == "press":
            result = await s.press(a.key)
        elif a.action == "scroll":
            result = await s.scroll(direction=a.direction, amount=a.amount)
        elif a.action == "check_text":
            deadline = asyncio.get_running_loop().time() + a.timeout_ms / 1000
            while True:
                result = await s.eval_js("document.body.innerText")
                body = json.loads(result.content) if result.success else ""
                success = isinstance(body, str) and a.text in body
                remaining = deadline - asyncio.get_running_loop().time()
                if success or remaining <= 0 or not result.success:
                    break
                await asyncio.sleep(min(0.2, remaining))
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
        if a.action == "video_start":
            await self.start_video(run)
        if a.action == "video_stop":
            artifact = await self.stop_video(run)
            if run.video_error:
                success, content = False, run.video_error
        if a.action == "screenshot":
            artifact = self._save(run, await self._capture(run), ".jpg", "页面截图")
        if run.recording:
            run.frames.append(await self._capture(run))
            if len(run.frames) >= 40:
                artifact = self._finish_recording(run)
        if a.action == "record_stop":
            artifact = self._finish_recording(run) or artifact
        if not success:
            try:
                artifact = self._save(run, await self._capture(run), ".jpg", "失败现场")
            except Exception:
                pass  # Preserve the action failure even when the page cannot be captured.
        run.error = None if success else str(content)
        # Keep explicit assertions for review, but never log fill values or full DOM text.
        entry = {"action": a.action, "success": success}
        if a.action == "check_text":
            entry["expected"] = a.text
        run.log.append(entry)
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
        if run.recorder:
            raise ValueError("Finish recording the workflow before running a demo")
        run.activity = "demo"
        run.demo_total = 9
        run.demo_status, run.error = "running", None
        run.demo_step = 0
        run.log.clear()
        self._persist(run)
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
                if shutil.which("ffmpeg") and run.video is None:
                    await self.start_video(run)
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
            for index, step in enumerate(steps, 1):
                run.demo_step = index
                await asyncio.sleep(0.65)
                if step["action"] == "check_text":
                    step["timeout_ms"] = 3000
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
            await self.stop_video(run)
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
                try:
                    await self.stop_video(run)
                    if run.recorder:
                        from deepseek_tui.browser_workflows import finish_recording

                        await finish_recording(run)
                    if run.recording:
                        self._finish_recording(run)
                    self._persist(run)
                finally:
                    if run.session:
                        try:
                            await asyncio.wait_for(run.session.close(kill=True), timeout=10)
                        except Exception:
                            if run.profiles:
                                from octop_browser.cdp.launcher import terminate_browser

                                await terminate_browser(run.profiles.get_or_create("workbench"))
                            raise
            finally:
                shutil.rmtree(run.directory, ignore_errors=True)
                self.runs.pop(thread_id, None)

    async def close_all(self) -> None:
        await self.installer.close()
        await asyncio.gather(*(self.close(key) for key in list(self.runs)))
