from types import SimpleNamespace

import pytest

from deepseek_tui.workspace.execution import (
    ENV_LOCAL,
    ENV_WORKTREE,
    WorktreePendingError,
    execution_root,
    normalize_env_mode,
    project_root,
    workspace_state,
)


def test_normalize_env_mode_defaults_local() -> None:
    assert normalize_env_mode(None) == ENV_LOCAL
    assert normalize_env_mode("WORKTREE") == ENV_WORKTREE
    with pytest.raises(ValueError, match="env_mode"):
        normalize_env_mode("sandbox")


def test_execution_root_local(tmp_path) -> None:
    thread = SimpleNamespace(workspace=str(tmp_path), env_mode="local", worktree_path=None)
    assert project_root(thread) == tmp_path.resolve()
    assert execution_root(thread) == tmp_path.resolve()
    assert workspace_state(thread) == ENV_LOCAL


def test_execution_root_worktree(tmp_path) -> None:
    tree = tmp_path / "wt"
    tree.mkdir()
    thread = SimpleNamespace(
        workspace=str(tmp_path / "proj"),
        env_mode="worktree",
        worktree_path=str(tree),
    )
    (tmp_path / "proj").mkdir()
    assert execution_root(thread) == tree.resolve()
    assert workspace_state(thread) == ENV_WORKTREE


def test_execution_root_pending() -> None:
    thread = SimpleNamespace(
        workspace="/tmp/proj", env_mode="worktree", worktree_path=None
    )
    with pytest.raises(WorktreePendingError):
        execution_root(thread)
    assert workspace_state(thread) == "worktree-pending"
