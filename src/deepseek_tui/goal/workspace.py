"""Content identity for goal verification, excluding generated/runtime directories."""

from __future__ import annotations

import hashlib
import os
import stat
import logging
import time
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_GENERATED = {
    ".git",
    ".deepseek",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}


def workspace_digest(root: Path) -> str | None:
    """Fail closed if a stable snapshot cannot be read; never execute repository code.

    Git workspaces include tracked and nonignored untracked files. Other workspaces
    include all files except the runtime/cache directories above. Symlinks are hashed
    as links, not followed outside the workspace.
    """
    root = Path(root)
    started = time.perf_counter()
    files_read = bytes_read = 0
    try:
        listing = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "."],
            cwd=root,
            capture_output=True,
            timeout=10,
            check=False,
        )
        if listing.returncode == 0:
            paths = [Path(os.fsdecode(raw)) for raw in listing.stdout.split(b"\0") if raw]
        else:
            paths = []
            for directory, dirs, files in os.walk(root):
                dirs[:] = [name for name in dirs if name not in _GENERATED]
                paths.extend((Path(directory) / name).relative_to(root) for name in files)
        digest = hashlib.sha256()
        for relative in sorted(set(paths)):
            if any(part in _GENERATED for part in relative.parts):
                continue
            path = root / relative
            digest.update(os.fsencode(relative) + b"\0")
            if path.is_symlink():
                digest.update(b"link\0" + os.fsencode(os.readlink(path)))
                continue
            if not path.exists():
                digest.update(b"deleted\0")
                continue
            if not path.is_file():
                # e.g. a Git submodule: no claim that its contents were verified.
                return None
            before = path.stat()
            digest.update(str(stat.S_IFMT(before.st_mode) | (before.st_mode & 0o111)).encode() + b"\0")
            files_read += 1
            with path.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    bytes_read += len(chunk)
                    digest.update(chunk)
            after = path.stat()
            if (before.st_mtime_ns, before.st_ctime_ns, before.st_size, before.st_mode, before.st_ino) != (after.st_mtime_ns, after.st_ctime_ns, after.st_size, after.st_mode, after.st_ino):
                return None
            digest.update(b"\0")
        return digest.hexdigest()
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        logger.debug("goal_workspace_scan files=%d bytes=%d elapsed_ms=%.3f",
                     files_read, bytes_read, (time.perf_counter() - started) * 1000)
