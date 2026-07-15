"""Git worktree isolation for workflow runs (opt-in MVP)."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from deepseek_tui.workflow.models import WorkflowValidationError
from deepseek_tui.workflow.store import workflow_runs_dir


class WorkflowWorktreeError(WorkflowValidationError):
    """Raised when worktree setup fails (including non-git cwd)."""


@dataclass(frozen=True, slots=True)
class WorktreeInfo:
    path: Path
    branch: str
    git_root: Path


def find_git_root(cwd: Path) -> Path | None:
    """Return the enclosing git work-tree root, or None if not a git repo."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    root = (proc.stdout or "").strip()
    if not root:
        return None
    return Path(root).resolve()


def worktree_path_for_run(run_id: str, *, workspace: Path | None = None) -> Path:
    return workflow_runs_dir(workspace) / run_id / "tree"


def worktree_branch_for_run(run_id: str) -> str:
    return f"deepseek-wf/{run_id}"


def _git(
    args: list[str],
    *,
    cwd: Path,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise WorkflowWorktreeError(
            f"git {' '.join(args)} timed out after {exc.timeout}s"
        ) from exc
    if check and proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        raise WorkflowWorktreeError(f"git {' '.join(args)} failed: {err}")
    return proc


def _is_worktree_checkout(path: Path) -> bool:
    if not path.is_dir():
        return False
    marker = path / ".git"
    return marker.exists()


def ensure_run_worktree(
    run_id: str,
    *,
    workspace: Path,
    existing_path: str | None = None,
    existing_branch: str | None = None,
) -> WorktreeInfo:
    """Create or reuse a managed worktree for ``run_id``.

    Path: ``.deepseek/workflow-runs/<run_id>/tree``
    Branch: ``deepseek-wf/<run_id>``

    Fail-closed when ``workspace`` is not inside a git repository.
    Does not delete the worktree on run completion (caller may cleanup later).
    """
    project = workspace.resolve()
    git_root = find_git_root(project)
    if git_root is None:
        raise WorkflowWorktreeError(
            "policy.worktree=on requires a git repository; "
            f"{project} is not inside one"
        )

    path = (
        Path(existing_path).resolve()
        if existing_path
        else worktree_path_for_run(run_id, workspace=project).resolve()
    )
    branch = existing_branch or worktree_branch_for_run(run_id)

    if _is_worktree_checkout(path):
        return WorktreeInfo(path=path, branch=branch, git_root=git_root)

    if path.exists():
        raise WorkflowWorktreeError(
            f"worktree path exists but is not a git checkout: {path}"
        )

    path.parent.mkdir(parents=True, exist_ok=True)

    # Clean up stale worktree registrations first: if `path` was deleted
    # out-of-band (e.g. by the user, or a crash before the checkout finished),
    # git still remembers it as checked out and `worktree add` below would
    # fail with "already checked out" even though nothing is actually there.
    _git(["worktree", "prune"], cwd=git_root, check=False)

    # If the branch already exists (resume after partial failure), attach it.
    show = _git(["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=git_root, check=False)
    if show.returncode == 0:
        _git(["worktree", "add", str(path), branch], cwd=git_root)
    else:
        _git(["worktree", "add", "-b", branch, str(path), "HEAD"], cwd=git_root)

    return WorktreeInfo(path=path, branch=branch, git_root=git_root)
