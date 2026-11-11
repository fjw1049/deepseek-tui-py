"""One persistent LCU connection and a cross-process desktop lease per owner."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import math
import os
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from deepseek_tui.cua.app_scope import (
    binding_only,
    canonical_binding,
    discovery_only,
    js_scope,
    native_app,
)
from deepseek_tui.cua.leases import DesktopLease as _DesktopLease
from deepseek_tui.tools.registry import ToolError

ApprovalCallback = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
MAX_FRAME = 48 * 1024 * 1024
CONNECT_RETRY_SECONDS = 30
LEASE_WAIT_SECONDS = 30
# A tool call queues behind another task's turn. A holder keeps its app until its
# turn ends, so bound the wait instead of hanging a turn nobody may be watching.
ACTION_LEASE_WAIT_SECONDS = 300
LOCK_DIR = Path("/tmp")

# Per installation in this process: the last runtime catalog, so later sessions
# expose the runtime's own tools without starting it, and a shared retry window
# so every conversation and child does not wait on an unavailable runtime.
_RUNTIMES: dict[tuple[str, bool], dict[str, Any]] = {}


def _code_fingerprint(arguments: dict[str, Any]) -> str | None:
    """Record an exact-code digest for diagnostics, not an authorization decision."""
    code = str(arguments.get("code") or "")
    return hashlib.sha256(code.encode()).hexdigest()[:16] if code else None


def _runtime_key(config: Any) -> tuple[str, bool]:
    return str(Path(config.installation).expanduser()), bool(config.chrome)


def reset_runtime_cache() -> None:
    _RUNTIMES.clear()


class StaleTarget(ToolError):
    """Code was held until an app is looked at again; the host may look on the model's behalf."""

    def __init__(self, reason: str, app: str | None, target: str):
        super().__init__(f"{reason} Nothing was executed. Use cua_observe on {target}, "
                         "then act on the fresh state.")
        self.reason = reason
        self.app = app


class DesktopLease(_DesktopLease):
    def __init__(self, path: Path | None = None):
        uid = getattr(os, "getuid", lambda: 0)()
        super().__init__(path or LOCK_DIR / f"deepseek-cua-{uid}.lock")


class CuaSession:
    def __init__(
        self, config: Any, cwd: Path, session_id: str, on_approval: ApprovalCallback | None = None,
        owner_id: str | None = None,
    ):
        self.config = config
        self.cwd = cwd
        self.session_id = session_id
        self.on_approval = on_approval
        self.instructions = ""
        self.descriptors: list[dict[str, Any]] = []
        self.process: asyncio.subprocess.Process | None = None
        self.pending: dict[int, asyncio.Future] = {}
        self.approvals: dict[int, asyncio.Task] = {}
        self.reader: asyncio.Task | None = None
        self.stderr: asyncio.Task | None = None
        self.sequence = 0
        self.turn_id: str | None = None
        self.runtime_turn_id: str | None = None
        self.stop_task = None
        self._app_bindings: dict[str, str] = {}
        self._unrestricted_repl = False
        self.lease = DesktopLease()
        self.lease.owner = owner_id or session_id
        self.human_reserved = False
        self.human_ready = False
        self.human_reason: str | None = None
        self.human_request_id: str | None = None
        self.human_since: float | None = None
        self.waiting = False
        self.last_surface: dict[str, str] | None = None
        self.last_activity = 0.0
        # Reset when the host turn ends: later turns that never call CUA are not CUA tasks.
        self.turn_used = False
        self.control_revision = 0
        self.control_lock = asyncio.Lock()
        self._unresolved: list[dict[str, Any]] = []
        from deepseek_tui.config.paths import user_deepseek_dir
        self.receipt_path = user_deepseek_dir() / "state" / "cua" / (
            hashlib.sha256((owner_id or session_id).encode()).hexdigest() + ".json"
        )
        try:
            receipt = json.loads(self.receipt_path.read_text())
            pending = receipt.get("unresolved", [])
            if isinstance(pending, dict):
                pending = [pending]
            self._unresolved = pending
            if receipt.get("outcome") in {"unknown", "in_progress"}:
                current = {k: v for k, v in receipt.items() if k != "unresolved"}
                current["outcome"] = "unknown"
                if not any(r["call_id"] == current["call_id"] for r in self._unresolved):
                    self._unresolved.append(current)
        except FileNotFoundError:
            pass
        self.lock = asyncio.Lock()
        self.broken = False
        self._operation: asyncio.Task | None = None
        self._interrupted_operation: asyncio.Task | None = None
        self._preview_monitor: asyncio.Task | None = None
        self._human_monitor: asyncio.Task | None = None
        self._needs_observation: set[str | None] = set()
        self._monitor: asyncio.Task | None = None
        self._operation_lock = asyncio.Lock()
        self._close_lock = asyncio.Lock()
        self._end_lock = asyncio.Lock()
        self.reset_reason = ""
        # The user changed the bound app outside a takeover; the next call observes first.
        self.outside_change = ""
        self.observation_generation = 0
        # True once model code has run in this connection's REPL.
        self._bound = False
        # Large text blocks the runtime returned, newest last; outlives reconnects.
        self.large_texts: list[str] = []
        # Window counts already reported per app, so a multi-window note is not repeated.
        self.window_counts: dict[str, int] = {}

    @property
    def unresolved(self) -> dict[str, Any] | None:
        return self._unresolved[0] if self._unresolved else None

    def heal_target(self) -> dict[str, str] | None:
        """The app the host can observe on the model's behalf (macOS observes by app)."""
        surface = self.last_surface or {}
        if surface.get("kind") == "app" and surface.get("app_id") and sys.platform == "darwin":
            return {"app": surface["app_id"]}
        return None

    def invalidate_observation(self, reason: str) -> None:
        self.outside_change = reason
        self.observation_generation += 1

    def stop_waiting_on(self, app: str | None) -> None:
        """An app that cannot be observed must not hold code for good."""
        self.outside_change = ""
        self._needs_observation.discard(app)

    def control_state(self) -> dict[str, Any]:
        return {
            "owner": "user" if self.human_ready and self.lease.fd is not None else
                     "assistant" if self.lease.fd is not None else "idle",
            "transferring": self.human_reserved and not self.human_ready,
            "revision": self.control_revision,
            "waiting": self.waiting,
            "holder": self.lease.holder(),
            "human_reason": self.human_reason,
            "unresolved": self.unresolved,
            "surface": self.last_surface,
            "last_activity": self.last_activity,
            "connected": (
                self.process is not None and self.process.returncode is None and not self.broken
            ),
        }

    async def reserve_human(self, reason: str | None = None, request_id: str | None = None) -> None:
        # Keep the OS lock while the connection closes; there must be no gap in
        # which another process can send input during the user's manual step.
        self.human_reserved = True
        self.human_ready = False
        self.human_reason = reason
        self.human_request_id = request_id
        self.control_revision += 1
        acquired = False
        try:
            async with self.lock:
                self.lease.can_stop = self.stop_task is not None
                await self.lease.acquire(timeout=LEASE_WAIT_SECONDS)
                acquired = True
                self.lease.describe("user", self.lease.owner)
            await self.close()
            if await self._deliver_panel_stop():
                raise ToolError("The user stopped this computer-use task.")
            self.human_ready = True
            if self.stop_task:
                self._human_monitor = asyncio.create_task(self._watch_human_stop(self.lease.ticket))
            self.human_since = time.time()
            self.control_revision += 1
        except BaseException:
            # A call still running holds self.lock and the lease; its own cleanup
            # releases the lease once it stops. Never free it underneath that call.
            if acquired or not self.lock.locked():
                self.release_human()
            else:
                self._clear_human()
            await self._deliver_panel_stop()
            raise

    def _clear_human(self) -> None:
        self.human_reserved = False
        self.human_ready = False
        self.human_reason = None
        self.human_request_id = None
        self.human_since = None
        self.control_revision += 1

    def release_human(self) -> None:
        self._clear_human()
        self.lease.release()

    async def _watch_human_stop(self, ticket):
        try:
            while self.human_ready and self.lease.ticket == ticket:
                if await self._deliver_panel_stop():
                    if self.lease.ticket == ticket:
                        self.release_human()
                    return
                await asyncio.sleep(0.1)
            if self.lease.ticket is None:
                await self._deliver_panel_stop()
        finally:
            if self._human_monitor is asyncio.current_task():
                self._human_monitor = None

    async def record_outcome(
        self, turn_id: str, call_id: str, outcome: str, *, code: str | None = None,
        settle: bool = False,
    ) -> None:
        receipt: dict[str, Any] = {"turn_id": turn_id, "call_id": call_id,
                                   "outcome": outcome, "recorded_at": time.time()}
        if code:
            receipt["code"] = code
        pending = [r for r in self._unresolved if r["call_id"] != call_id]
        if outcome == "unknown":
            pending.append(receipt.copy())
        elif outcome != "reviewed":
            pending = [] if settle else list(self._unresolved)
        receipt["unresolved"] = pending
        if outcome == "unknown":
            self._unresolved = pending
        # fsync must not stall every conversation; the caller still awaits the write.
        await asyncio.to_thread(self._write_receipt, receipt)
        self._unresolved = pending
        self.control_revision += 1

    def _write_receipt(self, receipt: dict[str, Any]) -> None:
        self.receipt_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.receipt_path.with_suffix("." + uuid.uuid4().hex + ".tmp")
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as stream:
                json.dump(receipt, stream)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.receipt_path)
        finally:
            temporary.unlink(missing_ok=True)

    async def acknowledge(self, call_id: str) -> None:
        if not self.unresolved or self.unresolved["call_id"] != call_id:
            raise ToolError("The uncertain operation changed. Refresh before confirming.")
        await self.record_outcome(self.unresolved["turn_id"], call_id, "reviewed")
        self.reset_reason = "The user reviewed the uncertain operation. Observe before continuing."

    def use_cached_catalog(self) -> bool:
        """Adopt a catalog this process already received, without starting the runtime."""
        if not self.descriptors:
            cached = _RUNTIMES.get(_runtime_key(self.config), {}).get("catalog")
            if cached:
                self.instructions, self.descriptors = cached
        return bool(self.descriptors)

    async def run(self, operation, events: list[asyncio.Event]):
        """Watch the whole session, including idle gaps, not only tool calls."""
        async with self._operation_lock:
            if any(event.is_set() for event in events):
                await self.close()
                raise ToolError("CUA stopped for cancellation or human takeover")
            if (events or self.stop_task) and (self._monitor is None or self._monitor.done()):
                self._monitor = asyncio.create_task(self._watch(events))
            task = asyncio.create_task(operation())
            self._operation = task
            try:
                return await task
            except asyncio.CancelledError:
                await self.close()
                if self._interrupted_operation is not task:
                    raise
                raise ToolError(
                    "CUA interrupted; action outcome may be unknown. "
                    "The session was reset; rediscover and observe before continuing."
                ) from None
            finally:
                self._operation = None
                self._interrupted_operation = None

    async def _wait_for_panel_stop(self):
        while not self.lease.stop_requested():  # noqa: ASYNC110 - cross-process signal
            if self.lease.consume_raised():
                self.invalidate_observation("The user raised the app; observe its current state.")
            await asyncio.sleep(0.25)
        await self._deliver_panel_stop()

    async def _deliver_panel_stop(self):
        if self.stop_task and self.lease.take_stop():
            await self.stop_task()
            return True
        return False

    async def _watch(self, events: list[asyncio.Event]) -> None:
        watchers = [asyncio.create_task(event.wait()) for event in events]
        if self.stop_task:
            watchers.append(asyncio.create_task(self._wait_for_panel_stop()))
        try:
            await asyncio.wait(watchers, return_when=asyncio.FIRST_COMPLETED)
            if self._bound:
                self.reset_reason = "Human takeover or cancellation reset the CUA session."
            if self._operation is not None and not self._operation.done():
                self._interrupted_operation = self._operation
                self._operation.cancel()
            else:
                async with self._operation_lock:
                    try:
                        await self.end_turn(interrupted=True)
                    except Exception:
                        pass  # end_turn closes failed connections.
                    finally:
                        await self.close()
        finally:
            for watcher in watchers:
                watcher.cancel()
            await asyncio.gather(*watchers, return_exceptions=True)

    @staticmethod
    def _paths(installation: Path):
        if sys.platform not in {"darwin", "linux"}:
            raise ToolError("LCU computer use currently supports Apple Silicon macOS and X11 Linux")
        root = installation.expanduser().resolve()
        try:
            node = (root / "node-path").read_text().strip()
        except OSError as exc:
            raise ToolError(f"LCU is not installed at {root}; follow docs/CUA.md") from exc
        client_path = root / "adapters/client.mjs"
        executable = root / "bin/lcu"
        if (
            not Path(node).is_absolute()
            or not Path(node).is_file()
            or not client_path.is_file()
            or not executable.is_file()
        ):
            raise ToolError("LCU installation is incomplete; reinstall a verified release")
        return node, client_path, executable

    async def connect(self) -> None:
        if self.process is not None:
            if self.process.returncode is None and not self.broken:
                return
            # The bridge exited while idle: no action is in flight, so reconnecting
            # cannot replay one, but code that already ran has lost its bindings.
            bound = self._bound
            async with self._close_lock:
                await self._close()
            if not self.human_reserved:
                await self._deliver_panel_stop()
            if bound:
                self.reset_reason = (
                    "The CUA connection ended between calls; its JavaScript bindings are gone. "
                    "Use cua_observe before acting."
                )
        state = _RUNTIMES.setdefault(_runtime_key(self.config), {})
        wait = state.get("retry_after", 0) - time.monotonic()
        if wait > 0:
            raise ToolError(f"{state['error']} (computer use retries in {math.ceil(wait)}s)")
        try:
            node, client_path, executable = await asyncio.to_thread(
                self._paths, self.config.installation
            )
            command = [str(executable)] + (["--chrome"] if self.config.chrome else [])
            self.process = await asyncio.create_subprocess_exec(
                node,
                str(Path(__file__).with_name("bridge.mjs")),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.cwd,
                limit=MAX_FRAME,
            )
            self.reader = asyncio.create_task(self._read(), name="cua-reader")
            self.stderr = asyncio.create_task(self._drain_stderr(), name="cua-stderr")
            result = await self._request(
                "connect",
                timeout=120,
                command=command,
                clientPath=str(client_path),
                cwd=str(self.cwd),
            )
            self._catalog(result)
        except Exception as exc:
            # A stop or takeover (BaseException) is not a runtime failure.
            state.update(
                retry_after=time.monotonic() + CONNECT_RETRY_SECONDS,
                error=str(exc) or type(exc).__name__,
            )
            state.pop("catalog", None)
            self.instructions, self.descriptors = "", []
            await self.close()
            raise
        except BaseException:
            await self.close()
            raise
        state.pop("retry_after", None)

    def _catalog(self, result: dict[str, Any]) -> None:
        tools = result.get("tools")
        if not isinstance(result.get("instructions"), str) or not isinstance(tools, list):
            raise ToolError("LCU did not supply its instructions and tool catalog")
        if {t.get("name") for t in tools} != {"js", "js_reset"}:
            raise ToolError("LCU public tool contract changed; adapter update required")
        self.instructions = result["instructions"]
        self.descriptors = tools
        _RUNTIMES.setdefault(_runtime_key(self.config), {})["catalog"] = (
            self.instructions,
            self.descriptors,
        )

    async def _write(self, value: dict[str, Any]) -> None:
        if (
            self.process is None
            or self.process.stdin is None
            or self.process.returncode is not None
        ):
            raise ToolError("CUA bridge is not running")
        self.process.stdin.write((json.dumps(value, ensure_ascii=False) + "\n").encode())
        await self.process.stdin.drain()

    async def _request(self, kind: str, *, timeout: float = 120, **values: Any) -> dict[str, Any]:
        self.sequence += 1
        request_id = self.sequence
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        try:
            await self._write({"id": request_id, "type": kind, **values})
            remaining = timeout
            while not future.done():
                start = asyncio.get_running_loop().time()
                approving = bool(self.approvals)
                await asyncio.wait({future}, timeout=min(0.25, remaining))
                # Human waits suspend action deadlines, never shutdown/interrupt deadlines.
                if (kind not in {"connect", "call", "observe"}
                        or (not approving and not self.approvals)):
                    remaining -= asyncio.get_running_loop().time() - start
                if remaining <= 0 and not future.done():
                    raise ToolError(f"CUA {kind} timed out; action outcome may be unknown")
            return future.result()
        finally:
            self.pending.pop(request_id, None)
            if not future.done():
                future.cancel()

    async def _approve(self, request: dict[str, Any]) -> None:
        request_id = request["id"]
        try:
            result = {"action": "cancel"}
            if self.on_approval is not None:
                result = await self.on_approval(request["params"])
            await self._write({"type": "elicitationResponse", "id": request_id, "response": result})
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await self._write(
                    {
                        "type": "elicitationResponse",
                        "id": request_id,
                        "response": {"action": "cancel"},
                    }
                )
            raise
        except Exception:
            with contextlib.suppress(Exception):
                await self._write(
                    {
                        "type": "elicitationResponse",
                        "id": request_id,
                        "response": {"action": "cancel"},
                    }
                )
        finally:
            self.approvals.pop(request_id, None)

    async def _read(self) -> None:
        try:
            assert self.process is not None and self.process.stdout is not None
            while line := await self.process.stdout.readline():
                message = json.loads(line)
                if message.get("type") == "elicitation":
                    task = asyncio.create_task(self._approve(message))
                    self.approvals[message["id"]] = task
                elif message.get("type") == "elicitationCancelled":
                    task = self.approvals.get(message["id"])
                    if task:
                        task.cancel()
                else:
                    future = self.pending.get(message.get("id"))
                    if future is not None and not future.done():
                        if message.get("ok"):
                            future.set_result(message["result"])
                        else:
                            future.set_exception(ToolError(message.get("error", "CUA failed")))
        except asyncio.CancelledError:
            raise
        except Exception:
            self.broken = True
        finally:
            self.broken = True
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(
                        ToolError("CUA connection closed; observe before retrying actions")
                    )
            for task in list(self.approvals.values()):
                task.cancel()

    async def _drain_stderr(self) -> None:
        assert self.process is not None and self.process.stderr is not None
        while await self.process.stderr.read(8192):
            pass  # Runtime logs can contain desktop data; never echo them into the chat.

    async def call(
        self, name: str, arguments: dict[str, Any], turn_id: str, call_id: str,
        *, scope: str | None = None,
    ) -> dict[str, Any]:
        """Run one public tool. ``scope`` names the one app host-written code touches."""
        if name not in {"js", "js_reset", "observe"} or not turn_id or not call_id:
            raise ToolError("CUA requires a public tool and real host turn/call identities")
        async with self.lock:
            self.last_activity = time.time()
            self.turn_used = True
            if self.human_reserved:
                raise ToolError("The user controls the desktop. Wait for control to be returned.")
            if self.lease.consume_raised():
                self.invalidate_observation("The user raised the app; observe its current state.")
            code = _code_fingerprint(arguments) if name == "js" else None
            if name == "js" and self.outside_change:
                raise ToolError("Not executed: " + self.outside_change
                                + " Use cua_observe to obtain a fresh observation before "
                                "further code execution. Old targets may be invalid.")
            # A cached catalog may predate this connection; report any change.
            known_instructions = self.instructions
            await self.connect()
            if self.turn_id is not None and self.turn_id != turn_id:
                raise ToolError("Previous CUA turn has not been cleaned up")
            app = None
            binding = None
            summary = name == "js" and set(arguments) == {"completion_summary"}
            if sys.platform == "darwin" and not self._unrestricted_repl:
                if name == "observe" and isinstance(arguments.get("app"), str):
                    app = await asyncio.to_thread(native_app, arguments["app"])
                    if app:
                        arguments = {**arguments, "app": app}
                elif summary or name == "js_reset":
                    app = self.lease.app
                elif name == "js" and scope:
                    app = scope
                elif name == "js":
                    app, binding = await asyncio.to_thread(
                        js_scope, arguments.get("code") or "", self._app_bindings)
                    if app and (binding or binding_only(arguments["code"])):
                        arguments = {**arguments, "code": canonical_binding(arguments["code"], app)}
            reacquiring = self.lease.fd is None
            switching = self.lease.fd is not None and self.lease.app != app
            if switching and await self.end_turn():
                raise ToolError("The user stopped this computer-use task.")
            if await self._deliver_panel_stop():
                await self.end_turn(interrupted=True)
                raise ToolError("The user stopped this computer-use task.")
            self.lease.can_stop = self.stop_task is not None
            self.waiting = self.lease.fd is None or switching
            waited = time.monotonic()
            try:
                await self.lease.acquire(timeout=ACTION_LEASE_WAIT_SECONDS, app=app,
                                         give_up=lambda: self.human_reserved)
            except BaseException:
                await self._deliver_panel_stop()
                raise
            finally:
                self.waiting = False
            lease_wait_ms = round((time.monotonic() - waited) * 1000)
            if self.human_reserved:
                raise ToolError("The user is taking control of the desktop. Nothing was executed.")
            if self.turn_id is None:
                # Sky remembers ended IDs even after reconnect. A resumed host turn
                # needs a fresh native segment, with the host identity preserved.
                self.runtime_turn_id = f"{turn_id}:cua:{uuid.uuid4().hex}"
            self.turn_id = turn_id
            old_binding = app and (switching or reacquiring) and app in self._app_bindings.values()
            if name == "js" and (self.lease.contended or old_binding):
                self._needs_observation.add(app)
            if (name == "js" and not summary and not binding_only(arguments.get("code", ""))
                    and (app in self._needs_observation or (not app and self._needs_observation))):
                # Unscoped code may touch any app still awaiting observation: name them.
                pending = sorted(a for a in ({app} if app else self._needs_observation) if a)
                target = ", ".join(pending) or "the intended app"
                raise StaleTarget(
                    f"{target} was released or used by another task since you last looked at it.",
                    pending[0] if len(pending) == 1 else None, target)
            observed_generation = self.observation_generation
            try:
                # Write before dispatch so a host crash cannot turn an uncertain
                # submission into an apparently safe retry. Store no code or pixels.
                if name == "js":
                    await self.record_outcome(turn_id, call_id, "in_progress", code=code)
                self._bound = True
                started = time.monotonic()
                program = arguments.get("code") or ""
                clipboard_input = bool(app and name == "js" and
                                       (".typeText(" in program or ".paste(" in program))
                async with self.lease.input_dispatch(clipboard_input):
                    result = await self._request(
                        "observe" if name == "observe" else "call",
                        name=name,
                        arguments=arguments,
                        context={
                            "sessionId": self.session_id,
                            "turnId": self.runtime_turn_id,
                            "toolCallId": call_id,
                            "metadata": {"deepseek/host-turn-id": turn_id},
                        },
                        timeout=max(150, float(arguments.get("timeout_ms", 0)) / 1000 + 60),
                    )
                # Runtime time includes any permission prompt answered during the call.
                result["stats"] = {"lease_wait_ms": lease_wait_ms,
                                   "runtime_ms": round((time.monotonic() - started) * 1000)}
                if name == "js":
                    # Once this result tells the model about earlier unknown outcomes,
                    # checking them is its job: they no longer wait on anyone.
                    told = self._annotate(result)
                    await self.record_outcome(turn_id, call_id, "returned", settle=told)
                if name == "observe" and not result.get("isError"):
                    if self.observation_generation != observed_generation:
                        result["isError"] = True
                        result.setdefault("content", []).append({"type": "text", "text":
                            "The app changed during observation. Use cua_observe again."})
                        result.pop("observation", None)
                    else:
                        # Observing another target switches work to it, so a target that
                        # quit or crashed cannot hold code execution blocked for good.
                        # A wait for exclusive desktop access had no known target.
                        self._needs_observation.discard(None)
                        self._needs_observation.discard(app)
                        self.outside_change = ""
                        self.reset_reason = ""
                        if self._unresolved and not arguments.get("poll"):
                            # The state shown is what the model checks an unknown outcome
                            # against, so telling it here settles it as a code result would.
                            result.setdefault("content", []).append(
                                {"type": "text", "text": self._unknown_note()})
                            last = self._unresolved[-1]
                            await self.record_outcome(
                                last["turn_id"], last["call_id"], "returned", settle=True)
                if binding:
                    self._app_bindings.pop(binding[0], None)
                    if not result.get("isError"):
                        self._app_bindings[binding[0]] = binding[1]
                if (name == "js" and app and not result.get("isError")
                        and binding_only(arguments.get("code") or "")):
                    # Binding prints the app's current state: the model has looked at it.
                    self._needs_observation.discard(app)
                if name == "js" and not app and not summary and not discovery_only(
                    arguments.get("code") or ""
                ):
                    self._unrestricted_repl = True
                elif name == "js_reset" and not result.get("isError"):
                    self._app_bindings.clear()
                    self._needs_observation.clear()
                    self._unrestricted_repl = False
                if (not summary and not result.get("isError") and (name == "observe"
                        or (name == "js" and (app or result.get("_meta"))))):
                    self.lease.note_surface(preview=True)
                    if self._preview_monitor is None or self._preview_monitor.done():
                        self._preview_monitor = asyncio.create_task(self._serve_previews())
                if summary and not result.get("isError"):
                    await self.end_turn()
                self._catalog(result)
                if self.instructions != known_instructions:
                    result.setdefault("content", []).append(
                        {"type": "text", "text": self.instructions}
                    )
                return result
            except BaseException:
                try:
                    # Arbitrary JavaScript may have sent input before the interruption.
                    if name == "js":
                        await self.record_outcome(turn_id, call_id, "unknown", code=code)
                finally:
                    # Even a receipt write failure must stop the native connection.
                    # Do not replay a possibly completed click or submission.
                    try:
                        with contextlib.suppress(Exception):
                            await asyncio.shield(self.end_turn(interrupted=True))
                    finally:
                        await self.close()
                raise

    def _annotate(self, result: dict[str, Any]) -> bool:
        """Tell the model what the host knows that its code result does not show.

        Returns whether it was told about earlier calls with unknown outcomes.
        """
        notes = []
        if self.reset_reason:
            notes.append(f"[Host: {self.reset_reason} Variables and element indices from "
                         "before are gone; bind the app again from a documented entry point "
                         "and act on the state it shows.]")
            actions = (result.get("trace") or {}).get("actions") or []
            if not result.get("isError") and any(
                    a.get("observe") and a.get("ok") for a in actions):
                self.reset_reason = ""
        if self._unresolved:
            notes.append(self._unknown_note())
        if notes:
            result.setdefault("content", []).append({"type": "text", "text": "\n".join(notes)})
        return bool(self._unresolved)

    def _unknown_note(self) -> str:
        pending_ids = tuple(r["call_id"] for r in self._unresolved)
        return ("[Host: an earlier computer-use call has an unknown outcome and may "
                "already have taken effect. Check the app before repeating that "
                f"effect. Pending call IDs: {pending_ids}.]")

    async def _serve_previews(self):
        while self.lease.ticket is not None:
            ticket = self.lease.ticket
            if ticket.with_suffix(".preview").exists() and not self.lock.locked():
                image = await self.preview_frame()
                data = base64.b64decode(image["data"]) if image else None
                await asyncio.to_thread(self.lease.answer_preview, ticket.stem, data)
            await asyncio.sleep(0.1)

    def _stop_preview_monitor(self):
        if self._preview_monitor is not None:
            self._preview_monitor.cancel()
            self._preview_monitor = None

    async def preview_frame(self) -> dict[str, Any] | None:
        """The operated target as it is now, for the panel only; skipped while a call runs."""
        if (self.lock.locked() or self.human_reserved or self.turn_id is None or not self._bound
                or self.process is None or self.broken):
            return None
        async with self.lock:
            try:
                result = await self._request("preview", timeout=5, context={
                    "sessionId": self.session_id,
                    "turnId": self.runtime_turn_id,
                    "toolCallId": "preview-" + uuid.uuid4().hex,
                })
            except ToolError:
                return None
        return result.get("image")

    async def end_turn(self, *, interrupted: bool = False) -> bool:
        async with self._end_lock:
            self._stop_preview_monitor()
            await self._end_turn(interrupted=interrupted)
            return await self._deliver_panel_stop()

    async def _end_turn(self, *, interrupted: bool = False) -> None:
        if self.turn_id is None:
            return
        try:
            if interrupted:
                await self._request("interrupt", timeout=5)
            await self._request(
                "endTurn",
                timeout=15,
                context={
                    "sessionId": self.session_id,
                    "turnId": self.runtime_turn_id,
                    "event": "Interrupt" if interrupted else "Stop",
                },
            )
        except BaseException:
            await self.close()
            raise
        finally:
            self.turn_id = None
            self.runtime_turn_id = None
            if not self.human_reserved:
                self.lease.release()

    async def handoff(self) -> bool:
        if self.turn_id is None:
            return False
        await self.end_turn()
        await self.close()
        return True

    async def close(self) -> None:
        self._stop_preview_monitor()
        monitor, self._monitor = self._monitor, None
        if monitor is not None and monitor is not asyncio.current_task():
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
        async with self._close_lock:
            await self._close()
            if not self.human_reserved:
                await self._deliver_panel_stop()

    async def _close(self) -> None:
        if self.process is not None and self._bound:
            self.reset_reason = "The CUA connection was closed; its JavaScript bindings are gone."
        try:
            if self.process is not None:
                if self.process.returncode is None:
                    with contextlib.suppress(Exception):
                        await self._request("close", timeout=5)
                    if self.process.stdin:
                        self.process.stdin.close()
                    try:
                        await asyncio.wait_for(self.process.wait(), 5)
                    except asyncio.TimeoutError:
                        self.process.kill()
                        await self.process.wait()
                for task in [self.reader, self.stderr, *self.approvals.values()]:
                    if task:
                        task.cancel()
                await asyncio.gather(
                    *(t for t in [self.reader, self.stderr, *self.approvals.values()] if t),
                    return_exceptions=True,
                )
        finally:
            self.process = None
            self._app_bindings.clear()
            self._needs_observation.clear()
            self._unrestricted_repl = False
            self.broken = False
            self._bound = False
            self.turn_id = None
            self.runtime_turn_id = None
            if not self.human_reserved:
                self.lease.release()
