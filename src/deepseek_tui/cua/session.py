"""One persistent LCU connection and a cross-process desktop lease per owner."""

from __future__ import annotations

import asyncio
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

from deepseek_tui.tools.registry import ToolError

ApprovalCallback = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
MAX_FRAME = 48 * 1024 * 1024
CONNECT_RETRY_SECONDS = 30
LEASE_WAIT_SECONDS = 30
LOCK_DIR = Path("/tmp")

# Per installation in this process: the last runtime catalog, so later sessions
# expose the runtime's own tools without starting it, and a shared retry window
# so every conversation and child does not wait on an unavailable runtime.
_RUNTIMES: dict[tuple[str, bool], dict[str, Any]] = {}


def _runtime_key(config: Any) -> tuple[str, bool]:
    return str(Path(config.installation).expanduser()), bool(config.chrome)


def reset_runtime_cache() -> None:
    _RUNTIMES.clear()


class DesktopLease:
    """Hold through observe/action/verify, not merely through individual clicks."""

    def __init__(self, path: Path | None = None):
        self.path = path or LOCK_DIR / f"deepseek-cua-{getattr(os, 'getuid', lambda: 0)()}.lock"
        self.fd: int | None = None
        self.owner: str | None = None

    async def acquire(self, timeout: float | None = None) -> None:
        import fcntl

        if self.fd is not None:
            return
        loop = asyncio.get_running_loop()
        deadline = None if timeout is None else loop.time() + timeout
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            if os.fstat(fd).st_uid != os.getuid():
                raise ToolError("Desktop lock belongs to another account")
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self.fd = fd
                    self.describe("assistant", self.owner)
                    return
                except BlockingIOError:
                    if deadline is not None and loop.time() >= deadline:
                        raise ToolError(
                            "The desktop is in use by another computer-use task (another "
                            "conversation or sub-agent). Nothing was executed. Wait for that "
                            "task to finish or ask the user to stop it, then retry."
                        ) from None
                    await asyncio.sleep(0.1)
        finally:
            if self.fd != fd:
                os.close(fd)

    def describe(self, owner: str, thread_id: str | None) -> None:
        if self.fd is not None:
            data = json.dumps({"owner": owner, "thread_id": thread_id}).encode()
            os.ftruncate(self.fd, 0)
            os.pwrite(self.fd, data, 0)

    def holder(self) -> dict[str, Any] | None:
        """Metadata is advisory only; flock is the authority."""
        import fcntl
        try:
            fd = os.open(self.path, os.O_RDWR | os.O_NOFOLLOW)
        except FileNotFoundError:
            return None
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return None
            except BlockingIOError:
                try:
                    return json.loads(os.pread(fd, 4096, 0))
                except (ValueError, UnicodeError):
                    return {"owner": "assistant", "thread_id": None}
        finally:
            os.close(fd)

    def release(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


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
        self.lease = DesktopLease()
        self.lease.owner = owner_id or session_id
        self.human_reserved = False
        self.human_ready = False
        self.human_reason: str | None = None
        self.human_request_id: str | None = None
        self.waiting = False
        self.last_surface: dict[str, str] | None = None
        self.last_activity = 0.0
        # Reset when the host turn ends: later turns that never call CUA are not CUA tasks.
        self.turn_used = False
        self.control_revision = 0
        self.control_lock = asyncio.Lock()
        self.unresolved: dict[str, Any] | None = None
        from deepseek_tui.config.paths import user_deepseek_dir
        self.receipt_path = user_deepseek_dir() / "state" / "cua" / (
            hashlib.sha256((owner_id or session_id).encode()).hexdigest() + ".json"
        )
        try:
            receipt = json.loads(self.receipt_path.read_text())
            if receipt.get("outcome") in {"unknown", "in_progress"}:
                self.unresolved = {**receipt, "outcome": "unknown"}
        except FileNotFoundError:
            pass
        self.lock = asyncio.Lock()
        self.broken = False
        self._operation: asyncio.Task | None = None
        self._interrupted_operation: asyncio.Task | None = None
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

    def invalidate_observation(self, reason: str) -> None:
        self.outside_change = reason
        self.observation_generation += 1

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
                await self.lease.acquire(timeout=LEASE_WAIT_SECONDS)
                acquired = True
                self.lease.describe("user", self.lease.owner)
            await self.close()
            self.human_ready = True
            self.control_revision += 1
        except BaseException:
            # A call still running holds self.lock and the lease; its own cleanup
            # releases the lease once it stops. Never free it underneath that call.
            if acquired or not self.lock.locked():
                self.release_human()
            else:
                self._clear_human()
            raise

    def _clear_human(self) -> None:
        self.human_reserved = False
        self.human_ready = False
        self.human_reason = None
        self.human_request_id = None
        self.control_revision += 1

    def release_human(self) -> None:
        self._clear_human()
        self.lease.release()

    async def record_outcome(self, turn_id: str, call_id: str, outcome: str) -> None:
        receipt = {"turn_id": turn_id, "call_id": call_id,
                   "outcome": outcome, "recorded_at": time.time()}
        if outcome == "unknown":
            self.unresolved = receipt
        # fsync must not stall every conversation; the caller still awaits the write.
        await asyncio.to_thread(self._write_receipt, receipt)
        self.unresolved = receipt if outcome == "unknown" else None
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
            if self._monitor is None or self._monitor.done():
                self._monitor = asyncio.create_task(self._watch(events)) if events else None
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

    async def _watch(self, events: list[asyncio.Event]) -> None:
        watchers = [asyncio.create_task(event.wait()) for event in events]
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
        self, name: str, arguments: dict[str, Any], turn_id: str, call_id: str
    ) -> dict[str, Any]:
        if name not in {"js", "js_reset", "observe"} or not turn_id or not call_id:
            raise ToolError("CUA requires a public tool and real host turn/call identities")
        async with self.lock:
            self.last_activity = time.time()
            self.turn_used = True
            if self.human_reserved:
                raise ToolError("The user controls the desktop. Wait for control to be returned.")
            if self.unresolved and name == "js":
                raise ToolError("A previous computer-use call has an unknown outcome. "
                                "Use cua_observe to inspect it, then ask the user to review "
                                "the uncertain operation in the operation panel; "
                                "do not repeat the action.")
            if name == "js" and (self.outside_change or self.reset_reason):
                raise ToolError("Not executed: " + (self.outside_change or self.reset_reason)
                                + " Use cua_observe to obtain a fresh observation before "
                                "further code execution. Old targets may be invalid.")
            # A cached catalog may predate this connection; report any change.
            known_instructions = self.instructions
            await self.connect()
            if name == "js" and self.reset_reason:
                raise ToolError(self.reset_reason)
            if self.turn_id is not None and self.turn_id != turn_id:
                raise ToolError("Previous CUA turn has not been cleaned up")
            self.waiting = self.lease.fd is None
            try:
                await self.lease.acquire(timeout=LEASE_WAIT_SECONDS)
            finally:
                self.waiting = False
            if self.human_reserved:
                raise ToolError("The user is taking control of the desktop. Nothing was executed.")
            if self.turn_id is None:
                # Sky remembers ended IDs even after reconnect. A resumed host turn
                # needs a fresh native segment, with the host identity preserved.
                self.runtime_turn_id = f"{turn_id}:cua:{uuid.uuid4().hex}"
            self.turn_id = turn_id
            observed_generation = self.observation_generation
            try:
                # Write before dispatch so a host crash cannot turn an uncertain
                # submission into an apparently safe retry. Store no code or pixels.
                if name == "js":
                    await self.record_outcome(turn_id, call_id, "in_progress")
                self._bound = True
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
                if name == "js":
                    await self.record_outcome(turn_id, call_id, "returned")
                if name == "observe" and not result.get("isError"):
                    if self.observation_generation != observed_generation:
                        result["isError"] = True
                        result.setdefault("content", []).append({"type": "text", "text":
                            "The app changed during observation. Use cua_observe again."})
                        result.pop("observation", None)
                    else:
                        # Observing another target switches work to it, so a target that
                        # quit or crashed cannot hold code execution blocked for good.
                        self.outside_change = ""
                        self.reset_reason = ""
                self._catalog(result)
                if self.instructions != known_instructions:
                    result.setdefault("content", []).append(
                        {"type": "text", "text": self.instructions}
                    )
                return result
            except BaseException:
                try:
                    if name == "js":
                        await self.record_outcome(turn_id, call_id, "unknown")
                finally:
                    # Even a receipt write failure must stop the native connection.
                    # Do not replay a possibly completed click or submission.
                    try:
                        with contextlib.suppress(Exception):
                            await asyncio.shield(self.end_turn(interrupted=True))
                    finally:
                        await self.close()
                raise

    async def end_turn(self, *, interrupted: bool = False) -> None:
        async with self._end_lock:
            await self._end_turn(interrupted=interrupted)

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
        monitor, self._monitor = self._monitor, None
        if monitor is not None and monitor is not asyncio.current_task():
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
        async with self._close_lock:
            await self._close()

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
            self.broken = False
            self._bound = False
            self.turn_id = None
            self.runtime_turn_id = None
            if not self.human_reserved:
                self.lease.release()
