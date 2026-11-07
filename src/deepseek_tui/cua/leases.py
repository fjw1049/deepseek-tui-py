"""System-wide CUA admission. Each live ticket is locked by its requesting process."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
import uuid
from pathlib import Path

from deepseek_tui.tools.registry import ToolError


def _open(path: Path, create: bool = False) -> int:
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | (os.O_CREAT if create else 0), 0o600)
    if os.fstat(fd).st_uid != os.getuid():
        os.close(fd)
        raise ToolError("Desktop lock belongs to another account")
    return fd


def _write(fd, value):
    data = json.dumps(value).encode()
    os.pwrite(fd, data, 0)
    os.ftruncate(fd, len(data))


class DesktopLease:
    def __init__(self, path: Path):
        self.path = path
        self.directory = path.with_suffix(".queue")
        self.fd: int | None = None
        self.owner: str | None = None
        self.app: str | None = None
        self._released_stop = False
        self.can_stop = False
        self.contended = False
        self.ticket: Path | None = None
        self.ticket_fd: int | None = None
        self.info: dict = {}

    @contextlib.contextmanager
    def guard(self):
        import fcntl

        self.directory.mkdir(mode=0o700, exist_ok=True)
        stat = self.directory.lstat()
        if stat.st_uid != os.getuid() or stat.st_mode & 0o077 or self.directory.is_symlink():
            raise ToolError("Unsafe desktop queue directory")
        fd = _open(self.directory / "guard", True)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def _records(self):
        import fcntl

        records = []
        for path in sorted(self.directory.glob("*.json")):
            fd = _open(path)
            try:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    records.append(json.loads(os.pread(fd, 8192, 0)))
                else:
                    self._remove_ticket(path)  # The process lost its OS lock.
            finally:
                os.close(fd)
        return records

    def records(self):
        """Include an older runtime while it owns the original exclusive flock."""
        with self.guard():
            records = self._records()
            if not any(not row["waiting"] for row in records):
                holder = self._legacy_holder()
                if holder:
                    records.insert(
                        0,
                        dict(
                            holder, app=None, pid=None, can_stop=False, key="legacy", waiting=False
                        ),
                    )
            return records

    def signal(self, key, action):
        # Never resolve a button by app name: a new owner gets a different ticket.
        if action not in {"stop", "cancel", "raised"}:
            return False
        with self.guard():
            for record in self._records():
                if record["key"] != key:
                    continue
                if action == "stop" and not record["can_stop"]:
                    return False
                if (action == "cancel") != record["waiting"] and action != "stop":
                    return False
                (self.directory / (key + "." + action)).touch(mode=0o600)
                return True
        return False

    def stop_requested(self):
        return self._released_stop or (
            self.ticket is not None and self.ticket.with_suffix(".stop").exists()
        )

    def take_stop(self):
        if not self.stop_requested():
            return False
        with self.guard():
            self._released_stop = False
            if self.ticket is not None:
                self.ticket.with_suffix(".stop").unlink(missing_ok=True)
            return True

    def _request_preview(self, key):
        """Return a descriptor for this ticket's response, even if its path is later unlinked."""
        with self.guard():
            if not any(row["key"] == key and row.get("preview") and row["owner"] == "assistant"
                       and not row["waiting"]
                       for row in self._records()):
                return None
            path = self.directory / (key + ".preview")
            if not path.exists():
                # Concurrent readers share a request. A later request gets a fresh inode.
                frame = path.with_suffix(".frame")
                frame.unlink(missing_ok=True)
                os.close(_open(frame, True))
                path.touch(mode=0o600)
            return _open(path.with_suffix(".frame"))

    def remote_preview(self, key):
        fd = self._request_preview(key)
        if fd is None:
            return None
        try:
            deadline = time.monotonic() + 6
            while time.monotonic() < deadline:
                # The writer unlinks its response after the complete image is on this inode.
                if not os.fstat(fd).st_nlink:
                    if any(row["key"] == key for row in self.records()):
                        return os.pread(fd, os.fstat(fd).st_size, 0)
                    return None
                time.sleep(0.1)
        finally:
            os.close(fd)

    def answer_preview(self, key, data):
        with self.guard():
            if self.ticket is None or self.ticket.stem != key:
                return
            request = self.ticket.with_suffix(".preview")
            if not request.exists():
                return
            frame = request.with_suffix(".frame")
            fd = _open(frame)
        try:
            with os.fdopen(fd, "wb") as stream:
                if data:
                    stream.write(data)
        finally:
            with self.guard():
                request.unlink(missing_ok=True)
                frame.unlink(missing_ok=True)

    def consume_raised(self):
        if not self.ticket:
            return False
        try:
            self.ticket.with_suffix(".raised").unlink()
        except FileNotFoundError:
            return False
        return True

    @staticmethod
    def _remove_ticket(path):
        for suffix in (".preview", ".frame", ".stop", ".raised", ".cancel", ".json"):
            path.with_suffix(suffix).unlink(missing_ok=True)

    @contextlib.asynccontextmanager
    async def input_dispatch(self, serialize):
        # Native Unicode typing can use the shared clipboard. Keep individual input
        # batches apart while allowing other apps to observe and reason concurrently.
        if not serialize:
            yield
            return
        import fcntl

        fd = _open(self.directory / "input", True)
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    await asyncio.sleep(0.025)
            yield
        finally:
            os.close(fd)

    def note_surface(self, surface=None, *, preview=False):
        if self.ticket_fd is not None:
            with self.guard():
                if surface is not None:
                    self.info["surface"] = surface
                if preview:
                    self.info["preview"] = True
                self.info["revision"] = self.info.get("revision", 0) + 1
                _write(self.ticket_fd, self.info)

    async def acquire(self, timeout=None, *, give_up=None, app=None):
        import fcntl

        self.contended = False
        if self.fd is not None and self.app == app:
            return
        self.release()
        start = time.monotonic()
        granted = False
        try:
            with self.guard():
                key = f"{time.monotonic_ns():020}-{uuid.uuid4().hex}"
                self.ticket = self.directory / (key + ".json")
                self.ticket_fd = _open(self.ticket, True)
                fcntl.flock(self.ticket_fd, fcntl.LOCK_EX)
                self.info = dict(
                    key=key,
                    app=app,
                    thread_id=self.owner,
                    pid=os.getpid(),
                    since=time.time(),
                    owner="assistant",
                    can_stop=self.can_stop,
                    waiting=True,
                )
                _write(self.ticket_fd, self.info)
            while not (give_up and give_up()):
                with self.guard():
                    if self.ticket is None or self.ticket.stem != key:
                        raise ToolError("The computer-use session closed while waiting.")
                    if self.ticket.with_suffix(".cancel").exists():
                        raise ToolError(
                            "The user cancelled this desktop wait. Nothing was executed. "
                            "Do not retry unless asked."
                        )
                    records = self._records()
                    active = [r for r in records if not r["waiting"]]
                    ahead = [r for r in records if r["waiting"] and r["key"] < key]
                    # Earlier waiters for a busy app don't consume free places.
                    eligible = [r for r in ahead if not any(a["app"] == r["app"] for a in active)]
                    blocked = (
                        len(active) >= 3
                        or any(not app or not r["app"] or r["app"] == app for r in active + ahead)
                        or len({r["app"] for r in eligible}) >= 3 - len(active)
                    )
                    if self.stop_requested():
                        raise ToolError("The user stopped this computer-use task.")
                    if not blocked:
                        fd = _open(self.path, True)
                        try:
                            # Old Workbench versions use an exclusive lock on this inode.
                            mode = fcntl.LOCK_SH if app else fcntl.LOCK_EX
                            fcntl.flock(fd, mode | fcntl.LOCK_NB)
                        except BlockingIOError:
                            os.close(fd)
                        except BaseException:
                            os.close(fd)
                            raise
                        else:
                            self.app = app
                            self.fd = fd
                            self.info.update(waiting=False, since=time.time())
                            _write(self.ticket_fd, self.info)
                            if not app:
                                _write(fd, self.info)
                            granted = True
                            return
                self.contended = True
                if timeout is not None and time.monotonic() - start >= timeout:
                    holder = self.holder() or {}
                    who = (
                        "the user" if holder.get("owner") == "user" else "another computer-use task"
                    )
                    seconds = int(time.time() - holder.get("since", time.time()))
                    raise ToolError(
                        f"The desktop is in use, held by {who} for {seconds}s; waited "
                        f"{int(timeout)}s and nothing was executed. "
                        "How long it will take is unknown. Do other work and retry, or end "
                        "the turn and say the desktop step is still to do."
                    )
                await asyncio.sleep(0.1)
        finally:
            if not granted:
                self.release()

    def describe(self, owner, thread_id):
        if self.fd is not None:
            with self.guard():
                self.info.update(owner=owner, thread_id=thread_id, since=time.time())
                _write(self.ticket_fd, self.info)
                if not self.app:
                    _write(self.fd, self.info)

    def holder(self):
        with self.guard():
            for record in self._records():
                if not record["waiting"] and (not self.app or record["app"] in (None, self.app)):
                    return record
            return self._legacy_holder()

    def _legacy_holder(self):
        import fcntl

        if not self.path.exists():
            return None
        fd = _open(self.path)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                try:
                    return json.loads(os.pread(fd, 8192, 0))
                except ValueError:
                    return {"owner": "assistant", "thread_id": None}
        finally:
            os.close(fd)
        return None

    def release(self):
        if self.ticket is None:
            return
        with self.guard():
            self._released_stop = self.stop_requested()
            self._remove_ticket(self.ticket)
            self.ticket = None
            for fd in (self.fd, self.ticket_fd):
                if fd is not None:
                    os.close(fd)
            self.ticket_fd = None
            self.fd = None
            self.app = None
