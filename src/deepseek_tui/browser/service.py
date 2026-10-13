"""Workbench browser sessions backed by octop-browser 1.0.0.

Session capture/control adapted from Octop's browser/harness.py and stream.py.
The private CDP bridge is contained in this module.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import os
import shutil
import socket
import sys
import tempfile
import time
import uuid
import zipfile
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from deepseek_tui.browser.input import BrowserInput
from deepseek_tui.browser.observation import (
    SCOPE_CONTEXT,
    VALUE_INPUTS,
    document_identity,
    evaluate,
    observe,
    root_context,
    target,
    target_state,
)

# Identity of the focused editable field and its record scope, without its contents.
FOCUSED_FIELD = (
    "(()=>{let e=document.activeElement;while(e?.shadowRoot?.activeElement)"
    "e=e.shadowRoot.activeElement;if(!e || !(e.isContentEditable || "
    "/^(INPUT|TEXTAREA|SELECT)$/.test(e.tagName)))return {};"
    "const ids=window.__deepseekFocusIds || (window.__deepseekFocusIds={map:new WeakMap(),next:0});"
    "if(!ids.map.has(e))ids.map.set(e,ids.next++);const s=(" + SCOPE_CONTEXT + ")(e);"
    "return {node:ids.map.get(e),scope:s?{tag:s.tag,id:s.id,keys:s.keys}:null}})()"
)
# At the session cap, a session unused this long may be closed for a new thread.
IDLE_RECLAIM_SECONDS = 600
TARGET_ACTIONS = {"click", "fill", "type", "select", "set_checked", "hover", "press", "scroll", "upload"}
OBSERVE_AFTER = TARGET_ACTIONS | {"open", "new_tab", "switch_tab", "close_tab", "back",
                                  "forward", "reload", "wait", "check_text", "screenshot"}


class BrowserActionError(RuntimeError):
    """A dispatched operation failed to settle; callers must inspect before retrying."""

    def __init__(self, response: dict[str, Any]):
        super().__init__(response["content"])
        self.response = response


class FrameLocator(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    selector: str = Field(min_length=1, max_length=1000)
    shadow_path: list[Annotated[str, Field(min_length=1, max_length=1000)]] = Field(
        default_factory=list, max_length=16, alias="shadowPath")


def browser_dependency_error(exc: ImportError) -> str:
    if sys.version_info < (3, 11):
        return (
            "Browser automation requires Python 3.11+; "
            f"runtime is Python {sys.version.split()[0]} ({sys.executable})"
        )
    return (
        f"Browser automation dependency could not be imported ({exc}). "
        f"Runtime: {sys.executable}. Run uv sync in the project, or install "
        "octop-browser==1.0.0 into this runtime's Python environment."
    )


class BrowserAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    _action_id: str | None = PrivateAttr(default=None)
    _deadline: float | None = PrivateAttr(default=None)
    _dispatched: bool = PrivateAttr(default=False)
    operation_id: str | None = Field(default=None, min_length=1, max_length=200)
    action: Literal[
        "status",
        "operation_status",
        "resolve_operation",
        "upload",
        "downloads",
        "handle_dialog",
        "recover",
        "close_session",
        "request_assistance",
        "tabs",
        "new_tab",
        "switch_tab",
        "close_tab",
        "back",
        "forward",
        "reload",
        "hover",
        "wait",
        "open",
        "observe",
        "describe",
        "click",
        "fill",
        "type",
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
    reason: str = Field(
        default="",
        max_length=1000,
        description=(
            "Required for request_assistance: explain in the user's language what currently "
            "blocks their task and the specific action, information or decision needed. "
            "Use observed evidence; never include passwords or one-time codes."
        ),
    )
    tab_id: str = Field(default="", max_length=200)
    frame_id: str = Field(default="", max_length=200)
    frame_selector: str | None = Field(default=None, min_length=1, max_length=1000)
    frame_path: list[Annotated[str, Field(min_length=1, max_length=1000)] | FrameLocator] = Field(
        default_factory=list, max_length=8)
    shadow_path: list[Annotated[str, Field(min_length=1, max_length=1000)]] = Field(
        default_factory=list, max_length=16
    )
    level: Literal["interactive", "full"] = "interactive"
    text_offset: int = Field(default=0, ge=0)
    element_offset: int = Field(default=0, ge=0)
    option_offset: int = Field(default=0, ge=0)
    frame_offset: int = Field(default=0, ge=0)
    generation: int | None = Field(default=None, ge=0)
    full_page: bool = False
    crop: tuple[int, int, int, int] | None = None
    url_contains: str = Field(default="", max_length=4096)
    url: str = Field(default="", max_length=4096)
    ref: str | None = Field(default=None, max_length=200)
    observation_id: str | None = Field(default=None, max_length=200)
    scope_ref: str | None = Field(default=None, max_length=200)
    option_ref: str | None = Field(default=None, max_length=200)
    detail_offset: int = Field(default=0, ge=0)
    operation_offset: int = Field(default=0, ge=0)
    outcome: Literal["executed", "not_executed"] | None = None
    files: list[Annotated[str, Field(min_length=1, max_length=4096)]] = Field(default_factory=list, max_length=10)
    chooser_id: str | None = Field(default=None, max_length=200)
    dialog_id: str | None = Field(default=None, max_length=200)
    accept: bool | None = None
    selector: str | None = Field(default=None, max_length=1000)
    text: str = Field(default="", max_length=8000)
    checked: bool | None = None
    key: str = Field(default="Enter", max_length=50)
    x: int | None = Field(default=None, ge=0, lt=2400)
    y: int | None = Field(default=None, ge=0, lt=1600)
    direction: Literal["up", "down", "left", "right"] = "down"
    amount: int = Field(default=300, ge=1, le=1200)
    timeout_ms: int = Field(default=0, ge=0, le=10000)
    wait_state: Literal["visible", "hidden"] = "visible"
    condition: Literal["url_contains", "text_contains", "selector_exists", "title_contains",
                       "input_value_equals", "checked_equals", "selected_equals"] | None = None

    @model_validator(mode="after")
    def validate_action(self) -> BrowserAction:
        if self.action == "upload" and not (self.ref or self.selector or self.chooser_id):
            raise ValueError("Upload requires an observed file input or the current chooser_id")
        if self.action == "handle_dialog" and not (self.dialog_id and self.accept is not None):
            raise ValueError("handle_dialog requires the current dialog_id and accept")
        if self.frame_path and (self.action not in {"observe", "wait", "check_text"} or self.frame_id or self.frame_selector):
            raise ValueError("Choose frame_path, frame_selector or frame_id for observe/wait/check_text")
        if self.frame_selector and (self.action not in {"observe", "wait", "check_text"} or self.frame_id):
            raise ValueError("frame_selector applies to observe/wait/check_text; choose it or frame_id")
        if self.shadow_path and self.action not in {"observe", "wait", "check_text"}:
            raise ValueError("shadow_path applies to observe; interact using its returned refs")
        if self.frame_id and self.action not in TARGET_ACTIONS | {
            "observe",
            "wait",
            "check_text",
            "screenshot",
        }:
            raise ValueError(
                "frame_id applies to observation and page interactions, not tab navigation"
            )
        if self.crop and (min(self.crop[:2]) < 0 or min(self.crop[2:]) <= 0):
            raise ValueError("crop requires nonnegative x/y and positive width/height")
        if self.full_page and self.crop:
            raise ValueError("Choose full_page or crop")
        if self.action == "request_assistance" and not self.reason.strip():
            raise ValueError("request_assistance requires a reason explaining the task blocker")
        if self.action == "press":
            from deepseek_tui.browser.input import key_event

            key_event(self.key)
        if self.action == "open" or (self.action == "new_tab" and self.url):
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
        if self.action == "set_checked" and (
            not (self.selector or self.ref) or self.checked is None
        ):
            raise ValueError("set_checked requires ref or selector and checked")
        if self.action == "check_text" and not self.text.strip():
            raise ValueError("check_text requires non-empty text")
        if self.action in {"switch_tab", "close_tab"} and not self.tab_id.strip():
            raise ValueError("switch_tab requires tab_id from tabs")
        if self.action == "hover" and not self.ref:
            raise ValueError("hover requires ref from observe")
        if self.action == "wait" and not (self.text.strip() or self.selector or self.url_contains):
            raise ValueError("wait requires text, selector, or url_contains")
        if self.action == "wait" and self.wait_state == "hidden" and not (
            self.text or self.selector
        ):
            raise ValueError("wait_state=hidden requires text or selector")
        if self.condition and self.action != "wait":
            raise ValueError("condition applies to wait")
        if self.condition in {"input_value_equals", "selected_equals", "checked_equals"} and not self.selector:
            raise ValueError("Field conditions require a unique selector")
        if self.condition == "checked_equals" and self.checked is None:
            raise ValueError("checked_equals requires checked")
        if self.scope_ref and self.action != "observe":
            raise ValueError("scope_ref applies to observe continuation")
        if self.option_ref and self.action != "select":
            raise ValueError("option_ref applies to select")
        if self.action == "describe" and not (self.ref and self.observation_id):
            raise ValueError("describe requires ref and its current observation_id")
        if self.action == "operation_status" and not self.operation_id:
            raise ValueError("operation_status requires the server action_id in operation_id")
        if self.action == "resolve_operation" and not (self.operation_id and self.outcome and self.reason.strip()):
            raise ValueError("resolve_operation requires operation_id, outcome and a human review reason")
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
    control_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
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
    width: int = 1200
    height: int = 760
    transferring: bool = False
    tabs: list[dict[str, Any]] = field(default_factory=list)
    assistance: dict[str, Any] | None = None
    latest_observation: dict[str, Any] | None = None
    handoff_baseline: dict[str, Any] | None = None
    healthy: bool = True
    observation_context: Any = None
    observation_root_context: Any = None
    target_binding_id: str | None = None
    operations: dict[str, dict[str, Any]] = field(default_factory=dict)
    unresolved: dict[str, dict[str, Any]] = field(default_factory=dict)
    requests: dict[str, tuple[str, str]] = field(default_factory=dict)
    scene: dict[str, Any] | None = None
    view_sequence: int = 0
    viewport_epoch: int = 0
    pressed_keys: dict[str, BrowserInput] = field(default_factory=dict)
    pressed_buttons: dict[str, BrowserInput] = field(default_factory=dict)
    action_deadline: float | None = None
    frame_catalog: list[tuple] = field(default_factory=list)
    native_events: Any = None
    pending_action: asyncio.Task | None = None
    pending_input: tuple[asyncio.Task, str] | None = None
    upload_root: Path | None = None
    replay_tabs: dict[str, str] = field(default_factory=dict)
    replay_upload_files: frozenset[str] = frozenset()
    metrics: list[dict[str, Any]] = field(default_factory=list)
    active_timings: dict[str, float] | None = None
    last_dispatch_id: str | None = None
    tab_cache_time: float = 0
    failures: dict[str, int] = field(default_factory=dict)
    consecutive_action_failures: int = 0
    focus_tokens: dict[str, str | None] = field(default_factory=dict)
    last_used: float = field(default_factory=time.monotonic)


class BrowserService:
    def __init__(self, artifact_root: Path):
        from deepseek_tui.browser.install import BrowserInstaller

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
        from deepseek_tui.browser.capabilities import browser_capabilities

        result["capabilities"] = browser_capabilities(video_ready=result["video_ready"])
        try:
            from octop_browser.cdp.launcher import find_chrome

            result["octop"] = importlib.metadata.version("octop-browser")
            result["browser"] = find_chrome()
            result["ready"] = bool(result["browser"])
            result["message"] = "Ready" if result["ready"] else "Install Chrome or Chromium"
        except ImportError as exc:
            result["message"] = browser_dependency_error(exc)
        return result

    async def recover(self, thread_id: str, *, actor: str = "user") -> dict[str, Any]:
        old = self.runs.get(thread_id)
        generation, url = (old.generation + 1, old.url) if old else (0, "")
        assistance, history = (old.assistance, list(old.log)) if old else (None, [])
        try:
            await self.close(thread_id)
        except Exception:
            pass
        run = await self.ensure(thread_id)
        run.generation, run.owner = max(generation, run.generation), actor
        run.assistance, run.log = assistance, history
        if old:
            run.operations, run.unresolved, run.requests = old.operations, old.unresolved, old.requests
        if assistance and actor == "user":
            assistance["status"] = "human"
        if urlsplit(url).scheme in {"http", "https"}:
            await self.action(thread_id, BrowserAction(action="open", url=url), actor=actor)
        self._persist(run)
        return self.state(thread_id)

    def clear_profile(self, thread_id: str) -> None:
        if thread_id in self.runs:
            raise ValueError("End the browser session before clearing saved login data")
        shutil.rmtree(self.artifact_root / thread_id / "profile", ignore_errors=True)

    async def ensure(self, thread_id: str) -> BrowserRun:
        existing = self.runs.get(thread_id)
        if existing and existing.session and not (existing.native_events and existing.native_events.dialog):
            try:
                await asyncio.wait_for(existing.session._internal.client.send(
                    "Runtime.evaluate", {"expression": "1", "returnByValue": True}), timeout=2)
                existing.healthy = True
            except Exception as exc:
                existing.healthy = False
                existing.latest_observation = None
                raise ValueError("Browser disconnected; recover the session before acting") from exc
        if thread_id not in self.runs:
            if len(self.runs) >= 8:
                await self._reclaim_idle_session()
            self.runs[thread_id] = BrowserRun(
                thread_id, Path(tempfile.mkdtemp(prefix="deepseek-browser-")),
                generation=self._saved_state(thread_id).get("generation", -1) + 1,
            )
            self.runs[thread_id].artifacts = self._saved_state(thread_id).get("artifacts", [])
            self.runs[thread_id].operations = self._saved_state(thread_id).get("operations", {})
            self.runs[thread_id].unresolved = self._saved_state(thread_id).get("unresolved", {})
            self.runs[thread_id].requests = self._saved_state(thread_id).get("requests", {})
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
                    raise ValueError(browser_dependency_error(exc)) from exc
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

    async def _reclaim_idle_session(self) -> None:
        """At the cap, close the least recently used session that nobody is using."""
        now = time.monotonic()
        idle = [
            run for run in self.runs.values()
            if now - run.last_used >= IDLE_RECLAIM_SECONDS and run.owner != "user"
            and run.assistance is None and not run.unresolved and not run.lock.locked()
            and not (run.recorder or run.recording or run.video)
            and not (run.demo_task and not run.demo_task.done())
        ]
        if not idle:
            raise ValueError("Close an existing browser session first (maximum 8)")
        await self.close(min(idle, key=lambda run: run.last_used).thread_id)

    def state(self, thread_id: str) -> dict[str, Any]:
        from deepseek_tui.browser.capabilities import browser_capabilities

        run = self.runs.get(thread_id)
        if run is None:
            saved = self._saved_state(thread_id)
            return {
                "active": False,
                "owner": "agent",
                "log": [],
                "artifacts": [],
                "recording": False,
                "demo_status": "idle",
                "error": None,
                "capabilities": browser_capabilities(video_ready=bool(shutil.which("ffmpeg"))),
                **saved,
                "unresolved": list(saved.get("unresolved", {}).values()),
            }
        return {
            "active": run.session is not None
            and run.healthy
            and getattr(
                getattr(getattr(run.session, "_internal", None), "client", None), "_ws", True
            )
            is not None,
            "healthy": run.healthy,
            "url": run.url,
            "video_recording": run.video is not None,
            "video_error": run.video_error,
            "owner": run.owner,
            "generation": run.generation,
            "transferring": run.transferring,
            "assistance": run.assistance,
            "viewport": {"width": run.width, "height": run.height},
            "tabs": run.tabs,
            "recording": run.recording,
            "log": run.log[-80:],
            "artifacts": run.artifacts[-12:],
            "demo_status": run.demo_status,
            "activity": run.activity,
            "workflow_recording": run.recorder is not None,
            "demo_step": run.demo_step,
            "demo_total": run.demo_total,
            "error": run.error,
            "unresolved": list(run.unresolved.values()),
            "scene": run.scene,
            "view_sequence": run.view_sequence,
            "capabilities": browser_capabilities(video_ready=bool(shutil.which("ffmpeg"))),
            "metrics": run.metrics[-40:],
            **(run.native_events.state() if run.native_events else {"dialog": None, "file_chooser": None, "downloads": []}),
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
                    "generation": run.generation,
                    "operations": run.operations,
                    "unresolved": run.unresolved,
                    "requests": run.requests,
                    "downloads": (run.native_events.state()["downloads"] if run.native_events else []),
                },
                ensure_ascii=False,
            ),
        )

    def approval_scope(self, thread_id: str) -> str:
        run = self.runs.get(thread_id)
        return f"{run.directory.name}:{run.generation}" if run else "new"

    def approval_fingerprint(self, thread_id, arguments, task_id):
        """Reuse only the same observation, task, exact node, scope and effect arguments."""
        result = {"arguments": deepcopy(arguments), "scope": self.approval_scope(thread_id)}
        run = self.runs.get(thread_id)
        observation = run.latest_observation if run else None
        if not task_id or not observation or arguments.get("observation_id") != observation["observation_id"]:
            return result
        candidates = [e for e in observation["elements"] if
            (arguments.get("ref") and e["ref"] == arguments["ref"]) or
            (arguments.get("selector") and e.get("selector") == arguments["selector"])]
        if len(candidates) != 1 or not candidates[0].get("target_id"):
            return result
        target = candidates[0]
        if target.get("name_truncated") or (target.get("scope") or {}).get("truncated"):
            return result
        effect_arguments = {k: v for k, v in arguments.items() if k not in {
            "ref", "selector", "generation", "operation_id", "x", "y"}}
        result["arguments"] = effect_arguments
        result["task_constraints"] = {
            "task_id": task_id, "expiry": "task_end_or_control_change",
            "document_id": observation["document_id"],
            "frame_id": observation.get("frame_id"),
            "frame_document_id": observation.get("frame_document_id"),
            "url": observation.get("url"), "href": target.get("href"),
            "target_id": target["target_id"], "name": target["name"],
            "role": target.get("role"), "type": target.get("type"), "scope": deepcopy(target.get("scope")),
        }
        return result

    def operation(self, thread_id: str, action_id: str) -> dict[str, Any]:
        run = self.runs.get(thread_id)
        operations = run.operations if run else self._saved_state(thread_id).get("operations", {})
        if action_id not in operations:
            raise ValueError("Browser operation was not found")
        return operations[action_id]

    def _remember_response(self, run, response, *, persist=True):
        receipt = response["receipt"]
        receipt.setdefault("observation", "available" if response.get("observation") else "unavailable")
        receipt.setdefault("evidence", "unavailable" if response.get("evidence_warning") else
                           "saved" if response.get("artifact") else "not_requested")
        action_id = receipt["action_id"]
        if action_id not in run.operations:
            if not response["success"]:
                run.consecutive_action_failures += 1
            elif receipt.get("action") not in {"observe", "describe", "screenshot", "tabs", "downloads"}:
                run.consecutive_action_failures = 0
            if run.consecutive_action_failures >= 3:
                receipt["consecutive_action_failures"] = run.consecutive_action_failures
                receipt["retry_kind"] = "change_route_or_assistance"
                response["content"] = str(response.get("content", "")) + (
                    "; repeated action failures across attempts. Inspect the blocker; "
                    "use a different supported route or request_user_input for help. "
                    "Taking another screenshot alone does not resolve the blocker."
                )
        saved = {"success": response["success"], "content": str(response.get("content", ""))[:2000],
                 "receipt": dict(receipt)}
        run.operations[action_id] = saved
        if receipt["execution"] == "unknown":
            run.unresolved[action_id] = dict(receipt)
        while len(run.operations) > 80:
            expired = next((key for key in run.operations if key not in run.unresolved), None)
            if expired is None:
                break
            run.operations.pop(expired)
        run.requests = {key: value for key, value in run.requests.items()
                        if value[1] in run.operations}
        try:
            if persist:
                self._persist(run)
        except OSError:
            response["evidence_warning"] = "Operation receipt is available in memory; persistence failed"
            receipt["evidence"] = "unavailable"
            saved["receipt"]["evidence"] = "unavailable"
        return response

    async def _capture(self, run: BrowserRun, *, full_page: bool = False,
                       crop: tuple[int, int, int, int] | None = None) -> bytes:
        # Adapted from Octop stream._capture_jpeg; same CDP session as the actions.
        params: dict[str, Any] = {"format": "jpeg", "quality": 75}
        if full_page or crop:
            metrics = await run.session._internal.client.send("Page.getLayoutMetrics")
            size = metrics["cssContentSize"]
            x, y, width, height = crop or (0, 0, size["width"], size["height"])
            if (
                x + width > size["width"]
                or y + height > size["height"]
                or width * height > 16_000_000
            ):
                raise ValueError(
                    "Screenshot region is outside page bounds or exceeds 16 megapixels"
                )
            params.update(captureBeyondViewport=True,
                          clip={"x": x, "y": y, "width": width, "height": height, "scale": 1})
        started = asyncio.get_running_loop().time()
        data = await asyncio.wait_for(
            run.session._internal.client.send(
                "Page.captureScreenshot", params
            ),
            timeout=4,
        )
        if run.active_timings is not None:
            run.active_timings["capture_ms"] = round(run.active_timings.get("capture_ms", 0) +
                (asyncio.get_running_loop().time() - started) * 1000, 2)
        return base64.b64decode(data["data"], validate=True)

    async def frame(self, thread_id: str) -> str | None:
        run = self.runs.get(thread_id)
        if not run or not run.session or run.lock.locked():
            return None
        async with run.lock:
            tree = await run.session._internal.client.send("Page.getFrameTree")
            run.url = tree.get("frameTree", {}).get("frame", {}).get("url", run.url)
            return "data:image/jpeg;base64," + base64.b64encode(await self._capture(run)).decode()

    async def view(self, thread_id: str) -> dict[str, Any]:
        """A coherent frame and tab snapshot; observing never takes control."""
        run = self.runs.get(thread_id)
        image = None
        if run:
            run.last_used = time.monotonic()  # A visible panel keeps its session.
        if run and run.native_events and run.native_events.dialog:
            run.view_sequence += 1
            return {**self.state(thread_id), "image": None}
        if run and run.session and not run.lock.locked() and not run.transferring:
            async with run.lock:
                try:
                    scene = await self._scene(run)
                    run.view_sequence += 1
                    await self.page_state(run)
                    await self._refresh_tabs(run)
                    image = (
                        "data:image/jpeg;base64,"
                        + base64.b64encode(await self._capture(run)).decode()
                    )
                    if scene != await self._scene(run):
                        image = None
                except Exception as exc:
                    if type(exc).__name__ == "CDPSessionError" or isinstance(exc, ConnectionError):
                        run.healthy = False
                    run.latest_observation = None
                    raise RuntimeError(
                        "Browser view unavailable; inspect status/recover: "
                        + (str(exc) or type(exc).__name__)
                    ) from exc
        return {**self.state(thread_id), "image": image}

    async def _release_inputs(self, run):
        if not run.pressed_keys and not run.pressed_buttons:
            return
        client = run.session._internal.client
        keys, buttons = list(run.pressed_keys.values()), list(run.pressed_buttons.values())
        run.pressed_keys.clear()
        run.pressed_buttons.clear()
        for key in keys:
            try:
                await client.send("Input.dispatchKeyEvent", {"type": "keyUp", "key": key.key,
                    "code": key.code, "windowsVirtualKeyCode": key.key_code, "modifiers": 0})
            except Exception:
                pass
        for button in buttons:
            try:
                await client.send("Input.dispatchMouseEvent", {"type": "mouseReleased",
                    "x": -1, "y": -1,
                    "button": button.button, "buttons": 0, "clickCount": 0})
            except Exception:
                pass

    async def _scene(self, run):
        for _ in range(2):
            try:
                return await self._read_scene(run)
            except Exception as exc:
                if not isinstance(exc, RuntimeError) and type(exc).__name__ != "CDPSessionError":
                    raise
                if getattr(run.session._internal.client, "_ws", True) is None:
                    raise
                run.observation_root_context = None
        raise ValueError("Browser document changed during scene read; wait for a fresh view")

    async def _read_scene(self, run):
        tree = await run.session._internal.client.send("Page.getFrameTree")
        frame = tree.get("frameTree", {}).get("frame", {})
        scene = {"tab_id": frame.get("id", ""), "document_id": frame.get("loaderId", ""),
                 "url": frame.get("url", ""), "generation": run.generation,
                 "viewport_epoch": run.viewport_epoch, "width": run.width, "height": run.height}
        from deepseek_tui.browser.frames import frame_entries

        scene["frame_documents"] = [(f.get("id"), f.get("loaderId")) for f in
                                    frame_entries(tree.get("frameTree", {}))]
        if run.native_events:
            keys = await evaluate(await root_context(run), "(()=>{const names=['data-record','data-record-id',"
                "'data-row-key','data-account-id'];const nodes=[...document.querySelectorAll(names.map(n=>'['+n+']').join(','))]"
                ".filter(e=>{const r=e.getBoundingClientRect();return r.right>0 && r.bottom>0 && r.x<innerWidth && r.y<innerHeight});"
                "if(nodes.length>200)return {error:true};const keys=nodes.map(e=>names.map(n=>e.getAttribute(n)));"
                "if(keys.flat().some(v=>v?.length>1024))return {error:true};return {count:nodes.length,keys}})()")
            if keys.get("error"):
                raise ValueError("Visible record scope is too large for direct viewport input; use scoped targets")
            focus = await evaluate(await root_context(run), FOCUSED_FIELD)
            if await document_identity(run.session._internal.client) != (frame.get("id", ""), frame.get("loaderId", "")):
                raise RuntimeError("Browser document changed during scene read")
            scene["business_scope"] = hashlib.sha256(json.dumps(keys, ensure_ascii=True).encode()).hexdigest()[:32]
        scene["scene_id"] = hashlib.sha256(json.dumps(scene, sort_keys=True).encode()).hexdigest()[:32]
        if run.native_events:
            run.focus_tokens[scene["scene_id"]] = hashlib.sha256(json.dumps(
                [scene["tab_id"], scene["document_id"], focus], sort_keys=True).encode()
            ).hexdigest() if focus else None
            while len(run.focus_tokens) > 32:
                run.focus_tokens.pop(next(iter(run.focus_tokens)))
        if run.scene and scene != run.scene:
            await self._release_inputs(run)
        run.scene = scene
        return dict(scene)

    async def input(self, thread_id: str, body: BrowserInput) -> dict[str, Any]:
        run = self.runs.get(thread_id)
        if not run or not run.session:
            raise ValueError("Open a browser page first")
        run.last_used = time.monotonic()
        async with run.lock:
            if run.owner != "user" or run.transferring or run.generation != body.generation:
                raise ValueError("Browser control changed; queued input was discarded")
            if body.kind == "release":
                await self._release_inputs(run)
                return {"success": True, "released": True}
            if run.native_events:
                await run.native_events.install(run.session._internal.client)
            if run.native_events and run.native_events.dialog:
                if body.event in {"keyUp", "mouseReleased"}:
                    return {"success": True, "cleanup": "after_dialog"}
                raise ValueError("Answer the current native dialog before sending page input")
            if run.unresolved and body.kind not in {"resize", "copy", "pick", "devtools"}:
                raise ValueError("An earlier input outcome is unknown; review its receipt before further changes")
            if body.scene_id is not None or run.scene is not None:
                scene = await self._scene(run)
                if body.scene_id != scene["scene_id"] and not self._same_focus(run, body, scene):
                    raise ValueError("Browser page changed; queued input was discarded")
            if run.recorder and run.recorder.frame_changed.is_set():
                await run.recorder._sync_frames()
                run.recorder.frame_changed.clear()
            run.revision += 1
            action_id = uuid.uuid4().hex
            if body.kind == "key" and body.event == "keyDown":
                run.pressed_keys[body.code or body.key] = body
            elif body.kind == "mouse" and body.event == "mousePressed":
                run.pressed_buttons[body.button] = body
            try:
                result = await asyncio.wait_for(self._execute_input(run, body, action_id), timeout=5)
            except (TimeoutError, RuntimeError, ConnectionError) as exc:
                response = self._remember_response(run, {"success": False,
                    "content": "Browser input outcome is unknown; inspect the page before retrying",
                    "receipt": {"action_id": action_id, "action": "input:" + body.kind,
                                "execution": "unknown", "effect": "unchecked"}})
                raise BrowserActionError(response) from exc
            if body.kind == "key":
                key_id = body.code or body.key
                if body.event == "keyDown":
                    run.pressed_keys[key_id] = body
                else:
                    run.pressed_keys.pop(key_id, None)
            elif body.kind == "mouse":
                if body.event == "mousePressed":
                    run.pressed_buttons[body.button] = body
                elif body.event == "mouseReleased":
                    run.pressed_buttons.pop(body.button, None)
            elif body.kind == "resize":
                run.viewport_epoch += 1
                if run.scene:
                    await self._scene(run)
            result["success"] = True
            result["receipt"] = {"action_id": action_id, "action": "input:" + body.kind,
                                 "execution": "executed", "effect": result.pop("effect", "unchecked")}
            if body.kind == "text" or (body.kind == "mouse" and body.event == "mouseReleased"):
                if run.recording:
                    try:
                        run.frames.append(await self._capture(run))
                        if len(run.frames) >= 40:
                            self._finish_recording(run)
                    except Exception as exc:
                        run.recording = False
                        result["evidence_warning"] = "Recording capture failed: " + str(exc)
                try:
                    self._persist(run)
                except OSError as exc:
                    result["evidence_warning"] = "Evidence could not be persisted: " + str(exc)
            return self._remember_response(run, result, persist=body.kind not in {"wheel"} and
                                           not (body.kind == "mouse" and body.event == "mouseMoved"))

    def _same_focus(self, run: BrowserRun, body: BrowserInput, scene: dict[str, Any]) -> bool:
        """Typing follows the focused field and its record, not URL or list churn elsewhere.

        Pointer input and keys without an editable focus (page shortcuts) keep the full
        scene binding, so they cannot act on records that changed after the frame was seen.
        """
        if body.kind not in {"text", "key"}:
            return False
        current = run.focus_tokens.get(scene["scene_id"])
        return current is not None and run.focus_tokens.get(body.scene_id) == current

    async def _execute_input(self, run, body, action_id):
        from deepseek_tui.browser.input import dispatch_input

        native = run.native_events
        if not native:
            return await dispatch_input(run, body)
        native.changed.clear()
        task = asyncio.create_task(dispatch_input(run, body))
        changed = asyncio.create_task(native.changed.wait())
        try:
            done, _ = await asyncio.wait({task, changed}, return_when=asyncio.FIRST_COMPLETED)
            if task in done:
                result = await task
                if native.dialog:
                    result["effect"] = "awaiting_dialog"
                return result
            run.pending_input = task, action_id
            return {"success": True, "effect": "awaiting_dialog", "dialog": native.state()["dialog"]}
        finally:
            changed.cancel()
            await asyncio.gather(changed, return_exceptions=True)
            if (not run.pending_input or run.pending_input[0] is not task) and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

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
        from deepseek_tui.browser.video import BrowserVideo

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
        checks = [entry for entry in state["log"] if entry["action"] in {"check_text", "verify"}]
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

    async def page_state(self, run: BrowserRun) -> dict[str, Any]:
        # Read from the controlled page, even when the preview panel is closed.
        tree = await asyncio.wait_for(
            run.session._internal.client.send("Page.getFrameTree"), timeout=4
        )
        run.url = tree.get("frameTree", {}).get("frame", {}).get("url", run.url)
        return {
            "active": True,
            "url": run.url,
            "owner": run.owner,
            "viewport": {"width": run.width, "height": run.height},
        }

    async def _reject_action(
        self, run: BrowserRun, action: BrowserAction, reason: str
    ) -> dict[str, Any]:
        old = run.latest_observation or {}
        selected = next((e for e in old.get("elements", []) if e.get("ref") == action.ref or
                         action.selector and e.get("selector") == action.selector), {})
        signature = {"action": action.action, "reason": reason, "document": old.get("document_id"),
                     "target": selected.get("target_id"), "name": selected.get("name"),
                     "scope": selected.get("scope"), "selector": action.selector}
        key = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()
        run.failures[key] = run.failures.get(key, 0) + 1
        if len(run.failures) > 64:
            run.failures.pop(next(iter(run.failures)))
        try:
            if run.native_events and run.native_events.dialog:
                raise ValueError("Native dialog pending")
            fresh = await asyncio.wait_for(observe(run), timeout=5)
        except Exception:
            run.latest_observation = None
            fresh = None
        receipt = {"action_id": action._action_id or uuid.uuid4().hex, "action": action.action,
            "execution": "not_executed", "effect": "unchecked", "reason": reason,
            "before_observation_id": action.observation_id,
            "after_observation_id": (fresh or {}).get("observation_id"), "phase": "preflight",
            "retry_kind": "inspect_unknown" if reason == "unresolved_operation" else
                          "change_route_or_assistance" if run.failures[key] >= 3 else "fresh_read_only_observation",
            "no_progress_count": run.failures[key]}
        run.active_timings = None
        run.log.append({"action": action.action, "success": False, **receipt})
        run.log[:] = run.log[-80:]
        guidance = {
            "target_obscured": "Inspect and dismiss the overlay using its own observed controls; do not click through it.",
            "screenshot_pixels_changed": "Pixels around the target point changed. Prefer an observed element ref/selector on dynamic pages; if none is available, inspect a fresh screenshot or request manual help.",
            "focus_not_active": "The page could not receive keyboard input. Inspect the active tab or request manual help.",
            "reload_would_resubmit_form": "This page came from a form submission; reloading would send the form again. Observe the current page, or open a specific URL for fresh content.",
        }
        content = reason + (": " + guidance[reason] if reason in guidance else "")
        if run.failures[key] >= 3:
            content += ": repeated without target or business progress; change route or request assistance"
        if reason == "screenshot_required":
            content += (
                ": action was not executed. Call screenshot, then use its observation_id "
                "for coordinate clicks. A diagnostic failure image is not an actionable screenshot."
            )
        return self._remember_response(run, {"success": False, "content": content, "artifact": None,
                "observation": fresh, "receipt": receipt})

    async def action(
        self,
        thread_id: str,
        action: BrowserAction,
        *,
        actor: str = "agent",
        check_assistance: bool = True,
        require_observation: bool = False,
    ) -> dict[str, Any]:
        run = self.runs.get(thread_id)
        if action.action == "operation_status":
            return self.operation(thread_id, action.operation_id)
        if action.action == "resolve_operation":
            if actor != "user":
                raise ValueError("Only human review can resolve an unknown browser mutation")
            if not run or action.operation_id not in run.unresolved:
                raise ValueError("Unknown operation was not found")
            async with run.lock:
                if run.transferring or (action.generation is not None and action.generation != run.generation):
                    raise ValueError("Browser control changed")
                saved = run.operations[action.operation_id]
                saved["receipt"].update(reconciliation={"source": "human_review", "outcome": action.outcome,
                    "reason": action.reason}, phase="reconciled")
                run.unresolved.pop(action.operation_id)
                self._persist(run)
                return {**saved, "success": True, "content": "Human review recorded", "reconciled": True}
        if action.action == "request_assistance":
            raise ValueError("Request assistance through the active agent task")
        if action.action in {"recover", "close_session"}:
            if actor == "agent" and run and run.assistance is not None:
                raise ValueError("Waiting for browser assistance; do not replace the session")
            if run and (run.owner != actor or run.transferring or
                        (action.generation is not None and action.generation != run.generation)):
                raise ValueError("Browser control changed; action was discarded")
            if action.action == "recover":
                state = await self.recover(thread_id, actor=actor)
            else:
                await self.close(thread_id)
                state = self.state(thread_id)
            unresolved = state.get("unresolved", [])
            state["unresolved_total"] = len(unresolved)
            state["unresolved"] = unresolved[action.operation_offset:action.operation_offset + 8]
            state["operation_offset"] = action.operation_offset
            state["next_operation_offset"] = action.operation_offset + 8 if len(unresolved) > action.operation_offset + 8 else None
            return {"success": True, "content": state, "artifact": None}
        if action.action == "status":
            if run and run.native_events and run.native_events.dialog:
                return {"success": True, "content": self.state(thread_id), "artifact": None}
            if run is None or run.session is None:
                state = self.state(thread_id)
            else:
                async with run.lock:
                    try:
                        state = await self.page_state(run)
                        if run.native_events:
                            state.update(run.native_events.state())
                        run.healthy = True
                    except Exception as exc:
                        run.healthy = False
                        run.latest_observation = None
                        return {"success": False, "content": "Browser disconnected; use recover: "
                                + (str(exc) or type(exc).__name__), "artifact": None,
                                "page": self.state(thread_id)}
                if run.assistance:
                    state["assistance"] = run.assistance
                state["unresolved_total"] = len(run.unresolved)
                state["unresolved"] = list(run.unresolved.values())[action.operation_offset:action.operation_offset + 8]
                state["next_operation_offset"] = action.operation_offset + 8 if len(run.unresolved) > action.operation_offset + 8 else None
            return {"success": True, "content": state, "artifact": None}
        if run is None or run.session is None:
            if action.action not in {"open", "new_tab"}:
                raise ValueError("Open a browser page first")
            run = await self.ensure(thread_id)
        if actor == "agent" and check_assistance and run.assistance is not None:
            raise ValueError("Waiting for browser assistance; do not repeat actions")
        run.last_used = time.monotonic()
        generation = run.generation
        queued_at = asyncio.get_running_loop().time()
        action._deadline = asyncio.get_running_loop().time() + 35
        async with run.lock:
            # Already user-owned when issued, rather than a takeover racing this action.
            if (actor == "agent" and run.owner == "user" and not run.transferring
                    and run.generation == generation):
                raise ValueError(
                    "The user controls this browser. Ask them to return control with "
                    "request_user_input(kind=action, surface=browser, reason=...), "
                    "or finish the task as blocked."
                )
            if run.owner != actor or run.transferring or run.generation != generation:
                raise ValueError("Browser control changed; queued action was discarded")
            if action.generation is not None and action.generation != run.generation:
                raise ValueError("Browser control changed; stale action was discarded")
            if actor == "agent" and check_assistance and run.assistance is not None:
                raise ValueError("Waiting for browser assistance; do not repeat actions")
            if not run.session:
                raise ValueError("Browser session has closed")
            action._action_id = uuid.uuid4().hex
            timings = {"queue_ms": round((asyncio.get_running_loop().time() - queued_at) * 1000, 2)}
            run.active_timings = timings
            run.action_deadline = action._deadline
            action = action.model_copy(update={"generation": generation})
            if run.native_events is None and hasattr(getattr(getattr(run.session, "_internal", None), "client", None), "on"):
                from deepseek_tui.browser.native import NativeBrowserEvents

                run.native_events = NativeBrowserEvents(run, self)
            if run.native_events:
                await run.native_events.install(run.session._internal.client)
                if run.native_events.dialog and action.action not in {"handle_dialog", "tabs", "downloads"}:
                    return await self._reject_action(run, action, "native_dialog_pending")
            if action.operation_id:
                fingerprint = hashlib.sha256(json.dumps(action.model_dump(exclude={"operation_id"}),
                    sort_keys=True, ensure_ascii=True).encode()).hexdigest()
                previous = run.requests.get(action.operation_id)
                saved = run.operations.get(previous[1]) if previous else None
                # An attempt that never dispatched (or never got a receipt) leaves the ID
                # free, so a retry with a fresh observation can actually run.
                if saved and saved["receipt"].get("execution") != "not_executed":
                    if previous[0] != fingerprint:
                        raise ValueError("Operation ID cannot be reused for different browser arguments")
                    return {**saved, "duplicate": True}
                run.requests[action.operation_id] = (fingerprint, action._action_id)
            if asyncio.get_running_loop().time() >= action._deadline:
                return await self._reject_action(run, action, "deadline_expired")
            if run.unresolved and action.action not in {"observe", "describe", "tabs", "downloads", "handle_dialog", "wait", "check_text", "screenshot", "open", "new_tab", "switch_tab"}:
                return await self._reject_action(run, action, "unresolved_operation")
            if len(run.unresolved) >= 8 and action.action in {"open", "new_tab", "switch_tab"}:
                return await self._reject_action(run, action, "unresolved_operation_limit")
            if action.action == "reload" and await self._form_submission_page(run):
                return await self._reject_action(run, action, "reload_would_resubmit_form")
            if action.action == "record_start" and run.recording:
                raise ValueError("Recording is already running; finish it before starting again")
            if action.action == "video_start" and run.video:
                raise ValueError("Video is already recording")
            if action.action in TARGET_ACTIONS and not (
                require_observation or action.observation_id
            ) and (action.ref or action.selector or action.action in {
                    "fill", "type", "select", "set_checked", "press"}):
                if action.ref:
                    raise ValueError("Element refs require their observation_id")
                # Internal/UI callers still need control-type checks before a click or key event.
                current = await observe(
                    run, selector=action.selector, full=True, frame_id=action.frame_id
                )
                action = action.model_copy(update={"observation_id": current["observation_id"]})
            if action.action in TARGET_ACTIONS and not action.chooser_id and (require_observation or action.observation_id):
                run.target_binding_id = None
                try:
                    resolved = await asyncio.wait_for(target(run, action), timeout=min(
                        5, max(0.001, action._deadline - asyncio.get_running_loop().time())))
                except Exception:  # validation failed before dispatch
                    resolved = {"error": "target_validation_unavailable"}
                if (resolved.get("error") == "focus_not_active" and action.action == "press"
                        and not action.ref and not action.selector):
                    # Focus only our validated page, then repeat all target checks.
                    if run.transferring or run.generation != generation:
                        raise ValueError("Browser control changed before focus recovery")
                    try:
                        await asyncio.wait_for(
                            run.session._internal.client.send("Page.bringToFront"), timeout=5
                        )
                        resolved = await asyncio.wait_for(target(run, action), timeout=5)
                    except Exception:
                        resolved = {"error": "focus_recovery_unavailable"}
                if resolved.get("error"):
                    return await self._reject_action(run, action, resolved["error"])
                if action.x is not None and not (action.ref or action.selector):
                    if action.x >= run.width or action.y is None or action.y >= run.height:
                        return await self._reject_action(run, action, "pointer_outside_viewport")
                    if not await self._point_unchanged(run, action.x, action.y):
                        return await self._reject_action(run, action, "screenshot_pixels_changed")
                if resolved.get("frame_id"):
                    action = action.model_copy(
                        update={
                            "frame_id": resolved["frame_id"],
                            "x": resolved.get("x"),
                            "y": resolved.get("y"),
                        }
                    )
                if resolved.get("bound"):
                    run.target_binding_id = action.observation_id
                    action = action.model_copy(update={"x": resolved["x"], "y": resolved["y"]})
                elif resolved.get("nested"):
                    return await self._reject_action(run, action, "target_resolution_unavailable")
                elif resolved.get("selector"):
                    action = action.model_copy(update={
                        "ref": None, "selector": resolved["selector"],
                        "x": resolved.get("x"), "y": resolved.get("y"),
                    })
            try:
                dispatch_started = asyncio.get_running_loop().time()
                if run.native_events and run.observation_context and run.observation_context.session_id:
                    await run.native_events.install(run.observation_context)
                result = await asyncio.wait_for(self._execute_action(run, action, actor), timeout=max(
                    0.001, action._deadline - asyncio.get_running_loop().time()))
            except (Exception, asyncio.CancelledError) as exc:
                read_only = action.action in {"observe", "describe", "tabs", "downloads", "wait", "check_text", "screenshot"}
                known = next((e for e in reversed(run.log)
                              if e.get("action_id") == action._action_id and
                              e.get("execution") == "executed"), None)
                dispatched = run.last_dispatch_id == action._action_id or action._dispatched
                receipt = {"action_id": action._action_id,
                           "action": action.action,
                           "execution": "failed" if read_only else "unknown" if dispatched else "not_executed",
                           "effect": "unchecked", "before_observation_id":
                           action.observation_id, "phase": "dispatch_or_verification",
                           "target_id": next((e.get("target_id") for e in (run.latest_observation or {}).get("elements", [])
                                              if e.get("ref") == action.ref), None)}
                if known:
                    receipt.update({k: v for k, v in known.items() if k not in {"success", "expected"}})
                run.latest_observation = None
                if type(exc).__name__ == "CDPSessionError" or isinstance(exc, ConnectionError):
                    run.healthy = False
                run.log.append({"action": action.action, "success": known["success"] if known else False, **receipt})
                run.log[:] = run.log[-80:]
                run.error = (
                    "Action interrupted"
                    if isinstance(exc, asyncio.CancelledError)
                    else str(exc) or type(exc).__name__
                )
                response = self._remember_response(run, {
                    "success": known["success"] if known else False, "artifact": None, "content": run.error +
                    ("; operation completed; later evidence unavailable." if known else
                     "; read failed. Inspect status/recover before acting." if read_only else
                     "; action was not dispatched." if not dispatched else
                     "; outcome unknown. Observe before retrying."),
                    "receipt": receipt, "observation": None,
                })
                if known:
                    response["evidence_warning"] = "Operation completed; later evidence was unavailable"
                    receipt["evidence"] = "unavailable"
                    run.operations[receipt["action_id"]]["receipt"]["evidence"] = "unavailable"
                run.active_timings = None
                if isinstance(exc, asyncio.CancelledError):
                    raise
                if known:
                    return response
                raise BrowserActionError(response) from exc
            timings["execute_and_observe_ms"] = round((asyncio.get_running_loop().time() - dispatch_started) * 1000, 2)
            timings["total_ms"] = round((asyncio.get_running_loop().time() - queued_at) * 1000, 2)
            run.metrics.append({"action_id": action._action_id, "action": action.action, **timings})
            run.metrics[:] = run.metrics[-200:]
            result["timings"] = timings
            run.active_timings = None
            return self._remember_response(run, result)

    async def _execute_action(self, run, action, actor):
        native = run.native_events
        if action.action == "handle_dialog":
            await native.handle_dialog(action)
            if run.pending_input:
                pending, original_id = run.pending_input
                run.pending_input = None
                try:
                    await asyncio.wait_for(pending, 5)
                    saved = run.operations.get(original_id)
                    if saved:
                        saved["receipt"].update(effect="unchecked", phase="dispatch_complete")
                except (Exception, asyncio.CancelledError):
                    pass
            await self._release_inputs(run)
            if run.pending_action:
                pending, run.pending_action = run.pending_action, None
                try:
                    original = await asyncio.wait_for(pending, 8)
                    self._remember_response(run, original)
                except (Exception, asyncio.CancelledError):
                    pass  # Preserve the original dispatched receipt; never dispatch it a second time.
            return {"success": True, "content": "Dialog answered", "receipt": {
                "action_id": action._action_id, "action": action.action,
                "execution": "executed", "effect": "unchecked"}}
        if action.action == "upload":
            if not action.chooser_id:
                await self._dispatch_guard(run, action)
            await native.upload(action, user_selected=actor == "user" or
                                bool(action.files) and set(action.files) <= run.replay_upload_files)
            return {"success": True, "content": "Files chosen; verify the application's upload result", "receipt": {
                "action_id": action._action_id, "action": action.action,
                "execution": "executed", "effect": "unchecked"}}
        if action.action == "downloads":
            return {"success": True, "content": native.state()["downloads"] if native else [], "receipt": {
                "action_id": action._action_id, "action": action.action,
                "execution": "executed", "effect": "unchecked"}}
        if not native:
            return await self._action(run, action)
        native.changed.clear()
        task = asyncio.create_task(self._action(run, action))
        changed = asyncio.create_task(native.changed.wait())
        try:
            done, _ = await asyncio.wait({task, changed}, return_when=asyncio.FIRST_COMPLETED)
            if task in done:
                return await task
            if native.dialog:
                run.pending_action = task
                return {"success": True, "content": "Action dispatched; answer the native dialog before continuing",
                    "dialog": native.state()["dialog"], "receipt": {
                    "action_id": action._action_id, "action": action.action, "execution": "executed",
                    "effect": "awaiting_dialog", "phase": "dialog_pending",
                    "before_observation_id": action.observation_id}}
            return await task
        finally:
            changed.cancel()
            await asyncio.gather(changed, return_exceptions=True)
            if run.pending_action is not task and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def _action(self, run: BrowserRun, a: BrowserAction) -> dict[str, Any]:
        run.revision += 1
        s = run.session
        input_client = run.observation_context if a.frame_id else s._internal.client
        if a.frame_id and a.action in {"wait", "check_text"}:
            await observe(run, frame_id=a.frame_id)
            input_client = run.observation_context
        artifact = None
        success = True
        observation = None
        observation_error = None
        evidence_warning = None
        settle_warning = None
        effect = "unchecked"
        action_id = a._action_id or uuid.uuid4().hex
        before_id = (run.latest_observation or {}).get("observation_id")
        before_tabs = await self._refresh_tabs(run) if a.action in OBSERVE_AFTER else run.tabs
        if a.action in {"open", "new_tab", "switch_tab", "close_tab", "back", "forward", "reload", "select", "set_checked", "press", "type", "scroll", "hover"}:
            run.last_dispatch_id = a._action_id
        if a.action == "open":
            existing = next((tab for tab in before_tabs if tab.get("url") == a.url), None)
            result = (None if existing.get("active") else await s.switch_tab(existing["tab_id"])) \
                if existing else await s.navigate(a.url)
        elif a.action == "observe":
            frame_id = a.frame_id
            if any((a.text_offset, a.element_offset, a.option_offset, a.frame_offset)) and not a.scope_ref:
                raise ValueError("Pagination requires scope_ref from the latest observation")
            if a.scope_ref:
                previous = run.latest_observation
                if not previous or previous["observation_id"] != a.scope_ref:
                    raise ValueError("Scope reference expired; start a fresh observation")
                if previous["control_generation"] != run.generation:
                    raise ValueError("Scope control changed; start a fresh observation")
                a = a.model_copy(update={"selector": previous.get("scope_selector"),
                    "shadow_path": previous.get("scope_shadow_path", []),
                    "frame_id": previous.get("frame_id", "")})
                frame_id = a.frame_id
            if a.frame_selector:
                from deepseek_tui.browser.frames import resolve_frame

                frame_id = await resolve_frame(s._internal.client, a.frame_selector)
            if a.frame_path:
                from deepseek_tui.browser.frames import resolve_frame_path

                path = [f if isinstance(f, str) else f.model_dump(by_alias=True) for f in a.frame_path]
                frame_id = await resolve_frame_path(s._internal.client, path)
            observation = await observe(run, selector=a.selector, full=a.level == "full",
                                        text_offset=a.text_offset, element_offset=a.element_offset,
                                        option_offset=a.option_offset,
                                        frame_id=frame_id, frame_offset=a.frame_offset,
                                        shadow_path=a.shadow_path, continuation_id=a.scope_ref)
            if a.frame_selector:
                observation["scope_frame_selector"] = a.frame_selector
            if a.frame_path:
                observation["scope_frame_path"] = path
            result = None
        elif a.action == "describe":
            from deepseek_tui.browser.observation import describe

            observation = await describe(run, a)
            result = None
        elif a.action == "tabs":
            result = await s.list_tabs()
        elif a.action == "new_tab":
            result = await s.new_tab(force_new=True)
            if result.success:
                if run.native_events:
                    await run.native_events.install(s._internal.client)
                if a.url:
                    result = await s.navigate(a.url)
        elif a.action == "switch_tab":
            result = await s.switch_tab(a.tab_id)
        elif a.action == "close_tab":
            tabs = await s.list_tabs()
            items = (tabs.metadata or {}).get("tabs", []) if tabs.success else []
            if not any(tab["tab_id"] == a.tab_id for tab in items):
                raise ValueError("Tab no longer exists")
            if any(tab["tab_id"] == a.tab_id and tab.get("active") for tab in items):
                other = next((tab for tab in items if tab["tab_id"] != a.tab_id), None)
                switched = (
                    await s.switch_tab(other["tab_id"])
                    if other
                    else await s.new_tab(force_new=True)
                )
                if not switched.success:
                    raise ValueError(switched.error or "Unable to switch tabs")
            result = await s.close_tab(a.tab_id)
        elif a.action == "back":
            result = await s.go_back()
        elif a.action == "forward":
            result = await s.go_forward()
        elif a.action == "reload":
            result = await s.reload()
        elif a.action == "hover":
            if a.selector or (a.observation_id and a.x is not None):
                await input_client.send("Input.dispatchMouseEvent", {
                    "type": "mouseMoved", "x": a.x, "y": a.y,
                })
                result = None
            else:
                result = await s.hover(ref=a.ref)
        elif a.action == "wait":
            from deepseek_tui.browser.conditions import check_condition

            deadline = min(a._deadline or float("inf"), asyncio.get_running_loop().time() +
                           (a.timeout_ms or 10000) / 1000)
            success = await check_condition(run, a, deadline)
            result = None
        elif a.action == "click":
            if a.x is not None and a.y is not None and (a.x >= run.width or a.y >= run.height):
                raise ValueError("Pointer is outside the current viewport")
            result = await self._click(run, a)
        elif a.action == "type":
            targeted = a.ref or a.selector or (a.frame_id and a.x is not None)
            result = await self._click(run, a) if targeted else None
            if result is None or result.success:
                if targeted:
                    await self._focus_ready(run, a)
                await input_client.send("Input.insertText", {"text": a.text})
                result = None
        elif a.action == "fill" and await target_state(
            run, a, f"e.tagName==='INPUT' && /^({VALUE_INPUTS})$/.test(e.type)"
        ) is True:
            # Picker inputs have no caret; set the HTML value and fire the events the
            # browser's own picker sends. The field-state check below confirms the value.
            run.last_dispatch_id = a._action_id
            await target_state(
                run,
                a,
                "(()=>{e.focus();e.value=" + json.dumps(a.text)
                + ";e.dispatchEvent(new Event('input',{bubbles:true}));"
                + "e.dispatchEvent(new Event('change',{bubbles:true}));return true})()",
            )
            result = None
        elif a.action == "fill":
            result = await self._click(run, a)
            if result.success:
                await self._focus_ready(run, a)
                # Octop 1.0 sends Ctrl+A/Meta+A without editing commands, which can
                # leave existing text selected incorrectly on macOS after takeover.
                from deepseek_tui.browser.input import press_key

                await press_key(run, "Meta+a" if sys.platform == "darwin" else "Ctrl+a",
                                client=input_client)
                await self._focus_ready(run, a)
                await press_key(run, "Backspace", client=input_client)
                await self._focus_ready(run, a)
                await input_client.send("Input.insertText", {"text": a.text})
                from deepseek_tui.tools.registry import ToolResult

                result = ToolResult(True, "Filled field")
        elif a.action == "select":
            if a.frame_id or (a.observation_id and a.observation_id == run.target_binding_id):
                await target_state(
                    run,
                    a,
                    "(()=>{e.value="
                    + ("window.__deepseekSelectedOption.value" if a.option_ref else json.dumps(a.text))
                    + ";e.dispatchEvent(new Event('input',{bubbles:true}));"
                    + "e.dispatchEvent(new Event('change',{bubbles:true}));return true})()",
                )
                result = None
            else:
                result = await s.select(value=a.text, ref=a.ref, selector=a.selector)
        elif a.action == "set_checked":
            if a.frame_id or (a.observation_id and a.observation_id == run.target_binding_id):
                checked = await target_state(run, a, "e.checked")
                result = None
            elif a.ref:
                node_id = s._internal.ref_cache.lookup(a.ref)
                obj = await s._internal.client.send("DOM.resolveNode", {"nodeId": node_id})
                object_id = obj["object"]["objectId"]
                try:
                    value = await s._internal.client.send("Runtime.callFunctionOn", {
                        "objectId": object_id, "returnByValue": True,
                        "functionDeclaration": "function(){return this.checked ?? null}",
                    })
                    checked = value.get("result", {}).get("value")
                finally:
                    await s._internal.client.send("Runtime.releaseObject", {"objectId": object_id})
                result = None
            else:
                result = await s.eval_js(
                    "(() => { const els = document.querySelectorAll("
                    + json.dumps(a.selector)
                    + "); return els.length === 1 ? els[0].checked ?? null : null; })()"
                )
                checked = json.loads(result.content) if result.success else None
            if not isinstance(checked, bool):
                raise ValueError("Checkbox selector must match one checkable element")
            if checked != a.checked:
                result = await self._click(run, a)
        elif a.action == "press":
            from deepseek_tui.browser.input import press_key

            targeted = a.ref or a.selector or (a.frame_id and a.x is not None)
            if targeted:
                await s._internal.client.send("Page.bringToFront")
                if a.frame_id:
                    await run.observation_context.focus_parent()
                await target_state(run, a, "(()=>{e.focus();return true})()")
            if targeted:
                await self._focus_ready(run, a)
            await press_key(run, a.key, client=input_client)
            result = None
        elif a.action == "scroll":
            await input_client.send("Input.dispatchMouseEvent", {
                "type": "mouseWheel", "x": a.x if a.x is not None else run.width / 2,
                "y": a.y if a.y is not None else run.height / 2,
                "deltaX": (a.amount if a.direction == "right" else -a.amount)
                if a.direction in {"left", "right"} else 0,
                "deltaY": (a.amount if a.direction == "down" else -a.amount)
                if a.direction in {"up", "down"} else 0,
            })
            result = None
        elif a.action == "check_text":
            from deepseek_tui.browser.conditions import check_condition

            deadline = min(a._deadline or float("inf"), asyncio.get_running_loop().time() +
                           (a.timeout_ms or 10000) / 1000)
            success = await check_condition(run, a, deadline)
            result = None
        else:
            result = None
        if run.native_events and a.action in {"open", "new_tab", "switch_tab", "close_tab"}:
            await run.native_events.install(s._internal.client)
        if a.action in {"fill", "select", "set_checked"} and (result is None or result.success):
            expected = json.dumps(a.checked if a.action == "set_checked" else a.text)
            state = (
                "e.checked"
                if a.action == "set_checked"
                else "(e.isContentEditable?e.innerText:e.value)"
            )
            try:
                settle_warning = await self._settle(run, frame_id=a.frame_id)
                expression = f"e.isConnected && {state} === {expected}"
                if a.action == "select" and a.option_ref:
                    expression = "e.isConnected && Array.from(e.selectedOptions).includes(window.__deepseekSelectedOption)"
                confirmed = await target_state(run, a, expression)
            except Exception:
                confirmed = False
            success = confirmed is True
            effect = "confirmed" if success else "not_confirmed"
            if not success:
                result = None
                content = "Requested field state was not reached; inspect before retrying"
        if (
            a.action in {"new_tab", "switch_tab", "close_tab"}
            and result is not None
            and result.success
        ):
            from deepseek_tui.browser.input import dispatch_input

            await dispatch_input(
                run,
                BrowserInput(
                    kind="resize", generation=run.generation, width=run.width, height=run.height
                ),
            )
        if result is not None:
            success = result.success
            content = result.content if success else result.error
        elif effect == "not_confirmed":
            content = "Requested field state was not reached; inspect before retrying"
        elif a.action == "check_text":
            content = ("PASS: " if success else "FAIL: ") + a.text
        elif a.action == "wait":
            content = "Wait condition satisfied" if success else "Wait condition timed out"
        elif a.action in {"observe", "describe"}:
            content = "Observation collected"
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
            try:
                observation = await observe(run, full=True, frame_id=a.frame_id)
            except Exception as exc:
                run.latest_observation = None
                observation_error = str(exc) or type(exc).__name__
            image = (await self._capture(run, full_page=a.full_page, crop=a.crop)
                     if a.full_page or a.crop else await self._capture(run))
            artifact = self._save(run, image, ".jpg", "页面截图")
            if observation:
                try:
                    same_page = await document_identity(s._internal.client) == (
                        observation["tab_id"], observation["document_id"])
                    # Unrelated DOM churn (clocks, feeds) must not void the capture;
                    # coordinate clicks re-check layout and pixels at the point.
                    same_layout = await evaluate(await root_context(run),
                        "window.__deepseekObservation?.id === "
                        + json.dumps(observation["observation_id"]))
                except Exception:
                    same_page, same_layout = False, False
                if same_page and same_layout is True and not (a.full_page or a.crop or a.frame_id):
                    observation["screenshot_artifact_id"] = artifact["id"]
                elif a.full_page or a.crop or a.frame_id:
                    observation["screenshot_scope"] = (
                        "full_page" if a.full_page else "crop" if a.crop else "parent_viewport"
                    )
                else:
                    observation_error = "Page changed during capture; read a fresh screenshot"
        if run.recording:
            try:
                run.frames.append(await self._capture(run))
                if len(run.frames) >= 40:
                    artifact = self._finish_recording(run)
            except Exception as exc:
                evidence_warning = "Recording capture failed: " + (str(exc) or type(exc).__name__)
                run.recording = False
        if a.action == "record_stop":
            artifact = self._finish_recording(run) or artifact
        if not success:
            try:
                artifact = self._save(run, await self._capture(run), ".jpg", "失败现场")
            except Exception:
                pass  # Preserve the action failure even when the page cannot be captured.
        run.error = None if success else str(content)
        # Keep explicit assertions for review, but never log fill values or full DOM text.
        if a.action in OBSERVE_AFTER and a.action != "screenshot":
            try:
                if a.action not in {"fill", "select", "set_checked"}:
                    settle_warning = await self._settle(run, frame_id=a.frame_id)
            except Exception as exc:
                settle_warning = "Page readiness unavailable: " + (str(exc) or type(exc).__name__)
            try:
                observation = await observe(run, full=True, frame_id=a.frame_id)
                if settle_warning:
                    observation.setdefault("warnings", []).append(settle_warning)
            except Exception as exc:
                run.latest_observation = None
                observation_error = str(exc) or type(exc).__name__
        receipt = {"action_id": action_id, "action": a.action,
                   "execution": "executed" if success or effect == "not_confirmed" else "failed",
                   "effect": ("confirmed" if success else "not_confirmed")
                   if a.action in {"check_text", "wait"} else effect,
                   "before_observation_id": before_id,
                   "after_observation_id": (observation or {}).get("observation_id")}
        if a.action in {"fill", "select", "set_checked", "wait", "check_text"}:
            from datetime import datetime, timezone

            receipt["verification"] = {"kind": a.condition or (
                "field_state" if a.action in {"fill", "select", "set_checked"} else "page_condition"),
                "verified_at": datetime.now(timezone.utc).isoformat(),
                "observation_id": (observation or {}).get("observation_id"),
                "frame_id": a.frame_id, "selector": a.selector}
        entry: dict[str, Any] = {"action": a.action, "success": success, **receipt}
        if a.action == "check_text":
            entry["expected"] = a.text
            if a.selector:
                entry["selector"] = a.selector
        run.log.append(entry)
        run.log[:] = run.log[-80:]
        page = {"active": True, "owner": run.owner, "url": run.url, "stale": True}
        try:
            page = await self.page_state(run)
        except Exception:
            pass  # A failed observation must not turn a completed submit into a retry.
        try:
            self._persist(run)
        except OSError as exc:
            evidence_warning = "Evidence could not be persisted: " + str(exc)
        response = {"success": success, "content": content, "artifact": artifact, "page": page}
        response.update(receipt=receipt, observation=observation)
        if artifact and artifact["path"].endswith(".jpg"):
            from datetime import datetime, timezone

            from PIL import Image

            with Image.open(artifact["path"]) as picture:
                width, height = picture.size
            scope = "full_page" if a.full_page else "crop" if a.crop else "parent_viewport" if a.frame_id else "viewport"
            transform = None if a.full_page or a.frame_id else {
                "scale_x": (a.crop[2] if a.crop else run.width) / width,
                "scale_y": (a.crop[3] if a.crop else run.height) / height,
                "offset_x": a.crop[0] if a.crop else 0, "offset_y": a.crop[1] if a.crop else 0,
            }
            response["image_manifest"] = {
                "kind": "browser", "action_id": action_id,
                "observation_id": (observation or {}).get("observation_id"),
                "tab_id": (observation or {}).get("tab_id"),
                "document_id": (observation or {}).get("document_id"),
                "frame_id": a.frame_id, "scope": scope,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "original_width": width, "original_height": height,
                "viewport": {"width": run.width, "height": run.height},
                "pixel_to_css": transform,
                "actionable": bool((observation or {}).get("screenshot_artifact_id")),
            }
        if observation_error:
            response["observation_error"] = observation_error
        if evidence_warning:
            response["evidence_warning"] = evidence_warning
        response["history"] = [{k: v for k, v in entry.items()
                                 if k in {"action", "execution", "effect", "reason", "success"}}
                               for entry in run.log[-10:]]
        if a.action == "tabs" and result is not None and result.success:
            run.tabs = (result.metadata or {}).get("tabs", [])
        elif a.action in OBSERVE_AFTER:
            await self._refresh_tabs(run, force=True)
        if a.action in OBSERVE_AFTER or a.action == "tabs":
            response["tabs"] = run.tabs
            before = {tab["tab_id"] for tab in before_tabs}
            after = {tab["tab_id"] for tab in run.tabs}
            response["tab_changes"] = {
                "opened": sorted(after - before),
                "closed": sorted(before - after),
            }
        return response

    async def _focus_ready(self, run: BrowserRun, action: BrowserAction | None = None) -> None:
        deadline = asyncio.get_running_loop().time() + 1
        deadline = min(deadline, run.action_deadline or float("inf"))
        while asyncio.get_running_loop().time() < deadline:
            if action and (run.transferring or action.generation != run.generation):
                raise ValueError("Browser control changed before keyboard input")
            parent_focused = True
            if run.observation_context:
                parent_focused = await run.observation_context.parent_focused()
            target_focused = await evaluate(run.observation_context or await root_context(run),
                "document.hasFocus() && "
                "window.__deepseekObservation?.focused()===window.__deepseekTarget")
            if parent_focused is True and target_focused is True:
                if action:
                    if await target_state(run, action, "e.isConnected") is not True:
                        raise ValueError("Observed target scope changed before keyboard input")
                    await self._dispatch_guard(run, action)
                return
            await asyncio.sleep(0.01)
        raise ValueError("Observed target did not gain focus; no keyboard input was sent")

    async def _click(self, run: BrowserRun, action: BrowserAction):
        await run.session._internal.client.send("Page.bringToFront")
        bound = action.observation_id and action.observation_id == run.target_binding_id
        if not action.frame_id and not bound:
            if action.observation_id:
                await self._dispatch_guard(run, action)
            run.last_dispatch_id = action._action_id
            if action.ref or action.selector:
                return await run.session.click(ref=action.ref, selector=action.selector)
            return await run.session.click(ref=None, selector=None, x=action.x, y=action.y)
        from deepseek_tui.tools.registry import ToolResult

        if action.frame_id:
            await run.observation_context.focus_parent()
        if bound:
            resolved = await self._dispatch_guard(run, action)
            action = action.model_copy(update={"x": resolved["x"], "y": resolved["y"]})
        client = run.observation_context if action.frame_id else run.session._internal.client
        try:
            run.last_dispatch_id = action._action_id
            await client.send("Input.dispatchMouseEvent", {
                "type": "mousePressed", "x": action.x, "y": action.y, "button": "left", "clickCount": 1})
            await client.send("Input.dispatchMouseEvent", {
                "type": "mouseReleased", "x": action.x, "y": action.y, "button": "left", "clickCount": 1})
        except BaseException:
            try:
                await asyncio.shield(asyncio.wait_for(client.send("Input.dispatchMouseEvent", {
                    "type": "mouseReleased", "x": -1, "y": -1, "button": "left", "clickCount": 0}), 1))
            except Exception:
                pass
            raise
        return ToolResult(True, "Clicked observed target")

    async def _form_submission_page(self, run: BrowserRun) -> bool:
        """CDP reload silently re-posts form results; Chrome's resubmit prompt is absent."""
        try:
            history = await run.session._internal.client.send("Page.getNavigationHistory")
        except Exception:
            return False  # A session that cannot read history cannot reload either.
        entries, index = history.get("entries") or [], history.get("currentIndex", -1)
        return 0 <= index < len(entries) and entries[index].get("transitionType") == "form_submit"

    async def _point_unchanged(self, run: BrowserRun, x: int, y: int) -> bool:
        """Compare pixels near the click point; unrelated animation elsewhere must not block it."""
        from PIL import Image, ImageChops

        artifact = (run.latest_observation or {}).get("screenshot_artifact_id")
        if not artifact:
            return False
        try:
            path = self.artifact(run.thread_id, artifact)
        except ValueError:
            return False
        current = await self._capture(run)
        box = (max(0, x - 32), max(0, y - 32), min(run.width, x + 32), min(run.height, y + 32))
        with Image.open(path) as before, Image.open(io.BytesIO(current)) as after:
            if before.size != after.size:
                return False
            diff = ImageChops.difference(
                before.convert("RGB").crop(box), after.convert("RGB").crop(box)
            ).convert("L")
        # Tolerates a caret or JPEG noise; an overlay or moved control changes far more.
        changed = sum(diff.histogram()[49:])
        return changed <= 0.02 * diff.width * diff.height

    async def _dispatch_guard(self, run, action):
        if run.transferring or run.generation != action.generation:
            raise ValueError("Browser control changed before dispatch")
        if action._deadline and asyncio.get_running_loop().time() >= action._deadline:
            raise ValueError("Browser action deadline expired before dispatch")
        resolved = await target(run, action)
        if run.transferring or run.generation != action.generation:
            raise ValueError("Browser control changed during target validation")
        if resolved.get("error"):
            raise ValueError("Observed target changed before dispatch: " + resolved["error"])
        return resolved

    async def _refresh_tabs(self, run: BrowserRun, *, force=False) -> list[dict[str, Any]]:
        if not hasattr(run.session, "list_tabs"):
            return run.tabs
        now = asyncio.get_running_loop().time()
        if not force and run.tabs and now - run.tab_cache_time < .5:
            return list(run.tabs)
        try:
            tabs = await asyncio.wait_for(run.session.list_tabs(), timeout=4)
            if tabs.success:
                run.tabs = (tabs.metadata or {}).get("tabs", [])
                run.tab_cache_time = now
        except Exception:
            pass  # Tab discovery must not discard a completed action receipt.
        return list(run.tabs)

    async def _settle(self, run: BrowserRun, *, frame_id: str = "") -> str | None:
        """Bounded DOM and network quiet period, rather than assuming CDP dispatch means
        SPA readiness. Requests the action started extend the wait from 1.5s to 3s."""
        loop = asyncio.get_running_loop()
        previous, started = None, loop.time()
        quiet_since = started
        soft = min(started + 1.5, run.action_deadline or float("inf"))
        hard = min(started + 3.0, run.action_deadline or float("inf"))
        client = run.observation_context if frame_id else await root_context(run)
        native, page = run.native_events, run.session._internal.client
        awaited_requests = False
        while (now := loop.time()) < hard:
            # Long-lived requests from before the action (polling, streams) are not its effect.
            busy = bool(native) and native.pending_requests(page, started - 2.0)
            awaited_requests = awaited_requests or busy
            # After awaited requests finish, let their DOM update settle within the hard bound.
            if now >= soft and not busy and not awaited_requests:
                break
            current = await evaluate(
                client,
                "[location.href,document.readyState,window.__deepseekPageRevision?.value || 0]",
            )
            if not isinstance(current, list):
                return
            now = loop.time()
            if current != previous or current[1] == "loading" or busy:
                quiet_since, previous = now, current
            elif now - quiet_since >= 0.15:
                return
            await asyncio.sleep(0.05)
        return (
            "Page did not settle (DOM or requests still busy); "
            "use a task-specific wait condition"
        )

    async def control(self, thread_id: str, owner: str) -> dict[str, Any]:
        if owner not in {"agent", "user", "stopped"}:
            raise ValueError("Invalid control owner")
        run = self.runs.get(thread_id)
        if not run:
            raise ValueError("Open a browser page first")
        if run.transferring:
            raise ValueError("Browser control is already changing")
        run.transferring = True
        run.owner = owner
        run.generation += 1
        if run.native_events:
            if run.native_events.dialog:
                run.native_events.dialog["generation"] = run.generation
            run.native_events.chooser = None
        run.latest_observation = None
        try:
            if run.demo_task and not run.demo_task.done():
                run.demo_task.cancel()
                await asyncio.gather(run.demo_task, return_exceptions=True)
                run.demo_status = "stopped"
            # Wait for the current atomic action; queued actions fail the generation check.
            async with run.lock:
                await self._release_inputs(run)
                if owner == "user":
                    # The live viewport remains available to the human, but an
                    # agent-started recording must not capture manual credentials.
                    if run.recording:
                        self._finish_recording(run)
                    if run.video:
                        await self.stop_video(run)
        finally:
            run.transferring = False
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
        if run.native_events and run.native_events.dialog:
            try:
                await asyncio.wait_for(run.native_events.dialog["client"].send(
                    "Page.handleJavaScriptDialog", {"accept": False}), 2)
            except Exception:
                pass
            run.native_events.dialog = None
        if run.pending_input:
            run.pending_input[0].cancel()
            await asyncio.gather(run.pending_input[0], return_exceptions=True)
            run.pending_input = None
        if run.pending_action:
            run.pending_action.cancel()
            await asyncio.gather(run.pending_action, return_exceptions=True)
            run.pending_action = None
        if run.demo_task and not run.demo_task.done():
            run.demo_task.cancel()
            await asyncio.gather(run.demo_task, return_exceptions=True)
        async with run.lock:
            try:
                await self._release_inputs(run)
                try:
                    await self.stop_video(run)
                    if run.recorder:
                        from deepseek_tui.browser.workflows import finish_recording

                        await finish_recording(run)
                    if run.recording:
                        self._finish_recording(run)
                    self._persist(run)
                finally:
                    if run.observation_context:
                        await run.observation_context.release_observation()
                        await run.observation_context.close()
                        run.observation_context = None
                    if run.observation_root_context:
                        await run.observation_root_context.close()
                        run.observation_root_context = None
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
