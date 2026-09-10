"""Single source of truth for a thread's project root vs execution root.

``workspace`` on the thread record is the project identity (the user's repo).
File/shell/git tools, checkpoints, and restore write to ``execution_root``:
the project itself in local mode, or a managed git worktree.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

ENV_LOCAL = "local"
ENV_WORKTREE = "worktree"
ENV_MODES = frozenset({ENV_LOCAL, ENV_WORKTREE})


class WorktreePendingError(ValueError):
    """``env_mode`` is worktree but the directory is not on disk yet."""

    error_code = "worktree_pending"

    def __init__(self) -> None:
        super().__init__("worktree has not been created yet")


def normalize_env_mode(raw: str | None) -> str:
    mode = (raw or ENV_LOCAL).strip().lower() or ENV_LOCAL
    if mode not in ENV_MODES:
        raise ValueError(f"env_mode must be local or worktree, got {raw!r}")
    return mode


def project_root(thread: Any) -> Path:
    raw = getattr(thread, "workspace", "") or ""
    return Path(str(raw)).expanduser().resolve()


def execution_root(thread: Any) -> Path:
    """Directory tools and restore must use. Raises if worktree is pending."""
    if normalize_env_mode(getattr(thread, "env_mode", None)) != ENV_WORKTREE:
        return project_root(thread)
    raw = getattr(thread, "worktree_path", None) or ""
    if not raw:
        raise WorktreePendingError()
    path = Path(raw).expanduser()
    if not path.is_dir():
        raise WorktreePendingError()
    return path.resolve()


def workspace_state(thread: Any) -> str:
    """``local`` | ``worktree`` | ``worktree-pending``."""
    if normalize_env_mode(getattr(thread, "env_mode", None)) != ENV_WORKTREE:
        return ENV_LOCAL
    try:
        execution_root(thread)
    except WorktreePendingError:
        return "worktree-pending"
    return ENV_WORKTREE


def is_scratch_workspace(root: Path) -> bool:
    """True when ``root`` is already a Claw sandbox or managed worktree."""
    from deepseek_tui.config.paths import user_deepseek_dir, user_worktrees_dir

    resolved = root.expanduser().resolve()
    bases = (user_deepseek_dir() / "claw", user_worktrees_dir())
    for base in bases:
        try:
            resolved.relative_to(base.expanduser().resolve())
            return True
        except ValueError:
            continue
    return False
