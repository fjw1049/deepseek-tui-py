"""Cross-process advisory lease for publishing into a project working tree.

Holds an exclusive flock on ``~/.deepseek/locks/{repo-slug}.lock`` so two
DeepSeek runtimes cannot apply isolated copies at the same time. Other
frameworks (Claude Code, Cursor, a human editor) do not take this lock;
they are handled by three-way merge at the apply boundary, not by exclusion.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import AsyncIterator
from pathlib import Path
from types import TracebackType

from deepseek_tui.config.paths import user_locks_dir
from deepseek_tui.workspace.managed_worktree import repo_slug

try:
    import fcntl
except ImportError:  # pragma: no cover — Windows
    fcntl = None  # type: ignore[assignment]


class ProjectLease:
    """Exclusive file lock for one git project root."""

    def __init__(self, project_root: Path) -> None:
        slug = repo_slug(project_root)
        self.path = user_locks_dir() / f"{slug}.lock"
        self._fh: object | None = None

    def acquire_blocking(self, *, nonblocking: bool = False) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+")
        if fcntl is None:
            self._fh = fh
            return True
        flags = fcntl.LOCK_EX
        if nonblocking:
            flags |= fcntl.LOCK_NB
        try:
            fcntl.flock(fh.fileno(), flags)
        except OSError:
            fh.close()
            return False
        self._fh = fh
        try:
            fh.seek(0)
            fh.truncate()
            fh.write(f"{os.getpid()}\n")
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
        except OSError:
            pass
        try:
            fh.close()
        except OSError:
            pass

    async def acquire(self, *, nonblocking: bool = False) -> bool:
        return await asyncio.to_thread(self.acquire_blocking, nonblocking=nonblocking)

    async def __aenter__(self) -> ProjectLease:
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


@contextlib.asynccontextmanager
async def hold_project_lease(project_root: Path) -> AsyncIterator[ProjectLease]:
    lease = ProjectLease(project_root)
    await lease.acquire()
    try:
        yield lease
    finally:
        lease.release()
