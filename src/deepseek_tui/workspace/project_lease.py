"""Cross-process advisory lease for publishing into a project working tree.

Holds an OS-backed exclusive lock on ``~/.deepseek/locks/{repo-slug}.lock``
so two DeepSeek runtimes cannot apply isolated copies at the same time. Other
frameworks (Claude Code, Cursor, a human editor) do not take this lock; they are
handled by three-way merge at the apply boundary, not by exclusion.
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import hashlib
import importlib
import os
import time
from collections.abc import AsyncIterator
from pathlib import Path
from types import TracebackType
from typing import IO, Protocol, cast

from deepseek_tui.config.paths import user_locks_dir
from deepseek_tui.workspace.managed_worktree import repo_slug


class _FcntlBackend(Protocol):
    LOCK_EX: int
    LOCK_NB: int
    LOCK_UN: int

    def flock(self, fd: int, operation: int) -> None: ...


class _MsvcrtBackend(Protocol):
    LK_LOCK: int
    LK_NBLCK: int
    LK_UNLCK: int

    def locking(self, fd: int, mode: int, nbytes: int) -> None: ...


def _optional_lock_backend(name: str) -> object | None:
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


fcntl = cast(_FcntlBackend | None, _optional_lock_backend("fcntl"))
msvcrt = cast(_MsvcrtBackend | None, _optional_lock_backend("msvcrt"))

_LOCK_RETRY_INTERVAL_SECONDS = 0.05


def _is_lock_contention(error: OSError) -> bool:
    return error.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}


class FileLease:
    """Exclusive process lease backed by one advisory-lock file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fh: IO[str] | None = None

    def acquire_blocking(self, *, nonblocking: bool = False) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = os.fdopen(os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600), "r+")
        try:
            if fcntl is not None:
                flags = fcntl.LOCK_EX
                if nonblocking:
                    flags |= fcntl.LOCK_NB
                fcntl.flock(fh.fileno(), flags)
            elif msvcrt is not None:
                # ``msvcrt.locking`` locks bytes from the current file position.
                # Keep byte zero present and use the same one-byte range for
                # acquire/release across every process.
                fh.seek(0, os.SEEK_END)
                if fh.tell() == 0:
                    fh.write("\0")
                    fh.flush()
                fh.seek(0)
                while True:
                    try:
                        # ``LK_LOCK`` only retries for a bounded period on
                        # Windows. Poll the non-blocking operation instead so
                        # the blocking API keeps its usual wait-until-acquired
                        # contract.
                        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError as error:
                        if nonblocking or not _is_lock_contention(error):
                            raise
                        time.sleep(_LOCK_RETRY_INTERVAL_SECONDS)
            else:  # pragma: no cover — supported platforms provide one backend
                raise RuntimeError("platform does not provide file locking")
        except OSError:
            fh.close()
            return False
        except Exception:
            fh.close()
            raise
        self._fh = fh
        try:
            fh.seek(0)
            fh.write(f"{os.getpid()}\n")
            fh.truncate()
            fh.flush()
        except OSError:
            pass
        return True

    def release(self) -> None:
        fh = self._fh
        self._fh = None
        if fh is None:
            return
        try:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            elif msvcrt is not None:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        try:
            fh.close()
        except OSError:
            pass

    async def acquire(self, *, nonblocking: bool = False) -> bool:
        async def try_once() -> bool:
            attempt = asyncio.create_task(
                asyncio.to_thread(self.acquire_blocking, nonblocking=True)
            )
            try:
                return await asyncio.shield(attempt)
            except asyncio.CancelledError:
                # ``to_thread`` cannot stop a worker that is already running.
                # Wait for this short non-blocking attempt and release the
                # lease if cancellation raced with a successful acquisition.
                acquired = await attempt
                if acquired:
                    self.release()
                raise

        while True:
            acquired = await try_once()
            if acquired or nonblocking:
                return acquired
            await asyncio.sleep(_LOCK_RETRY_INTERVAL_SECONDS)

    async def __aenter__(self) -> FileLease:
        ok = await self.acquire()
        if not ok:
            raise RuntimeError(f"could not acquire project lease: {self.path}")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()


class ProjectLease(FileLease):
    """Exclusive file lock for one git project root."""

    def __init__(self, project_root: Path) -> None:
        slug = repo_slug(project_root)
        super().__init__(user_locks_dir() / f"{slug}.lock")


class ThreadLease(FileLease):
    """Cross-process ownership of one thread and its managed worktree."""

    def __init__(self, thread_id: str) -> None:
        raw = (thread_id or "thread").strip()
        safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in raw)
        safe = safe.strip("-")[:64] or "thread"
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]
        super().__init__(user_locks_dir() / "threads" / f"{safe}-{digest}.lock")


@contextlib.asynccontextmanager
async def hold_project_lease(project_root: Path) -> AsyncIterator[ProjectLease]:
    lease = ProjectLease(project_root)
    if not await lease.acquire():
        raise RuntimeError(f"could not acquire project lease: {lease.path}")
    try:
        yield lease
    finally:
        lease.release()
