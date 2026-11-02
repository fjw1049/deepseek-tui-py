"""What shell commands may remove, and managed worktree git rules."""

from __future__ import annotations

import os
import subprocess
import time

import pytest

from deepseek_tui.config.paths import user_worktrees_dir
from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.tools.shell import check_command_policy
from deepseek_tui.workspace import shell_write_guard as guard
from deepseek_tui.workspace.shell_write_guard import (
    check_managed_worktree_git,
    existing_file_removals,
    existing_files,
    gone_files,
)


@pytest.mark.parametrize(
    "command",
    [
        "git commit -am done",
        "git switch -c build_0902",
        "git checkout -b feature/test",
        "git -C ../repo push origin main",
        "command git merge origin/main",
        "env GIT_EDITOR=true git rebase main",
        "bash -c 'git reset --hard HEAD^'",
        "pytest -q && /usr/bin/git branch temporary",
        "git stash push -m task",
        "git restore src/app.py",
        "git clean -fd",
        "git apply task.patch",
        "git add src/app.py",
        "git fetch origin",
        "git worktree add ../other HEAD",
        "git update-ref refs/heads/session HEAD",
        "git config user.name Agent",
        "git remote add backup ../backup.git",
        "git tag session-snapshot",
        "git custom-alias-that-might-mutate",
    ],
)
def test_managed_worktree_denies_git_state_changes(command: str) -> None:
    verdict = check_managed_worktree_git(command)
    assert not verdict.allowed, f"expected managed Git deny for: {command}"
    assert "project workspace" in verdict.reason


@pytest.mark.parametrize(
    "command",
    [
        "git status --short",
        "git diff HEAD -- src/foo.py",
        "git log -5 --oneline",
        "git show HEAD:README.md",
        "git branch --show-current",
        "git branch --list 'feature/*'",
        "git config --get user.name",
        "git remote -v",
        "git remote show origin",
        "git symbolic-ref --short HEAD",
        "git tag --list 'v*'",
        "echo git commit",
        "pytest -q && git rev-parse HEAD",
    ],
)
def test_managed_worktree_allows_git_reads(command: str) -> None:
    verdict = check_managed_worktree_git(command)
    assert verdict.allowed, f"expected managed Git read allow for: {command}"


def test_shell_policy_applies_managed_worktree_git_guard() -> None:
    context = ToolContext(
        working_directory=user_worktrees_dir() / "project-test" / "thread-test"
    )
    result = check_command_policy("git switch -c session-branch", context)
    assert result is not None
    assert result.success is False
    assert result.metadata["managed_worktree_git_denied"] is True


@pytest.fixture
def workspace(tmp_path):
    """Files on disk; each test dates the session start relative to them."""
    (tmp_path / "old.txt").write_text("the user's")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "old.md").write_text("the user's")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "out.bin").write_text("regenerable")
    (tmp_path / "made.txt").write_text("the agent's")
    return tmp_path


def removed(root, command, started):
    # Birth time cannot be set portably, so files are dated by moving the session start.
    return [os.path.relpath(p, root) for p in existing_file_removals(
        command, workspace=root, session_started_at=started)]


@pytest.mark.parametrize("command,expected", [
    ("rm old.txt", ["old.txt"]),
    ("rm -f old.txt", ["old.txt"]),
    ("unlink old.txt", ["old.txt"]),
    ("sudo rm old.txt", ["old.txt"]),
    ("rm docs/old.md", ["docs/old.md"]),
    ("rm -f old.txt && python3 add.py init", ["old.txt"]),
    ("ls; rm old.txt", ["old.txt"]),
    ("bash -c 'rm old.txt'", ["old.txt"]),
    ('sh -c "rm old.txt"', ["old.txt"]),
    ("rm -rf docs", ["docs"]),
    ("mv old.txt /nonexistent/elsewhere/old.txt", ["old.txt"]),
    ("cd docs && rm old.md", ["docs/old.md"]),
    ("cd docs && cd .. && rm old.txt", ["old.txt"]),
    ("cd docs && mv old.md /nonexistent/elsewhere/", ["docs/old.md"]),
    ('cd "docs"; rm -f old.md', ["docs/old.md"]),
    ('cd "$PWD" && rm -f old.txt', ["old.txt"]),
    ('cd "$(pwd)" && rm -f old.txt', ["old.txt"]),
    ("cd . && rm old.txt", ["old.txt"]),
])
def test_files_that_predate_the_session_are_reported(workspace, command, expected):
    assert removed(workspace, command, started=time.time() + 5) == expected


@pytest.mark.parametrize("command", [
    "rm build/out.bin",              # regenerable output
    "rm missing.txt",
    "rm $TARGET",                    # unknown until the shell expands it
    "rm /tmp/scratch-file",
    "mv old.txt _to_delete/old.txt",  # the way out of a refusal must stay open
    "mv old.txt docs/renamed.txt",
    "cd docs && mv old.md ../renamed.md",
    "cd $SOMEWHERE && rm old.txt",   # only the shell knows where that is
    "cp old.txt copy.txt",
    "sed -i 's/a/b/' old.txt",       # edits stay undoable through checkpoints
    "echo hi > old.txt",
    "python3 -c 'print(1)'",
])
def test_everything_else_is_left_alone(workspace, command):
    assert removed(workspace, command, started=time.time() + 5) == []


def test_files_the_session_created_are_its_to_remove(workspace):
    assert removed(workspace, "rm made.txt", started=0) == []


def test_a_wildcard_is_checked_file_by_file(workspace):
    assert sorted(removed(workspace, "rm *.txt", started=time.time() + 5)) == ["made.txt", "old.txt"]
    assert removed(workspace, "rm *.txt", started=0) == []


def test_watched_files_skip_generated_trees_and_stay_bounded(workspace, monkeypatch):
    (workspace / "node_modules").mkdir()
    (workspace / "node_modules" / "dep.js").write_text("x")
    found = existing_files(workspace, time.time() + 5)
    assert str(workspace.resolve() / "old.txt") in found
    assert not any("node_modules" in path for path in found)
    monkeypatch.setattr(guard, "_MAX_WATCHED_FILES", 2)
    assert len(existing_files(workspace, time.time() + 5)) == 2


def test_files_made_this_session_are_not_watched(workspace):
    assert existing_files(workspace, 0) == {}


def test_a_folder_holding_older_files_is_not_the_sessions_to_delete(workspace, monkeypatch):
    # The folder is new; what was moved into it is not.
    (workspace / "_to_delete").mkdir()
    (workspace / "_to_delete" / "kept.txt").write_text("the user's")
    (workspace / "made").mkdir()
    (workspace / "made" / "new.txt").write_text("the agent's")
    older = {workspace / "_to_delete" / "kept.txt"}
    monkeypatch.setattr(guard, "_predates", lambda path, _: path in older)
    assert removed(workspace, "rm -rf _to_delete", started=0) == ["_to_delete/kept.txt"]
    assert removed(workspace, "rm -rf made", started=0) == []
    assert removed(workspace, "mv _to_delete /elsewhere", started=0) == ["_to_delete/kept.txt"]


def run(root, command, watched, started):
    subprocess.run(command, shell=True, cwd=root, check=True, capture_output=True)
    return {os.path.relpath(p, root) for p in gone_files(watched, root, started)}


@pytest.fixture
def watched(workspace):
    return existing_files(workspace, time.time() + 5)


def test_a_moved_file_stays_watched_at_its_new_path(workspace, watched):
    assert run(workspace, "mkdir aside && mv old.txt aside/", watched, time.time() + 5) == set()
    assert str(workspace.resolve() / "aside" / "old.txt") in watched
    assert run(workspace, "rm -rf aside", watched, time.time() + 5) == {"aside/old.txt"}


def test_moving_a_folder_keeps_every_file_inside_it(workspace, watched):
    assert run(workspace, "mkdir aside && mv docs aside/", watched, time.time() + 5) == set()
    assert str(workspace.resolve() / "aside" / "docs" / "old.md") in watched


def test_deleting_through_an_allowlisted_folder_is_still_seen(workspace, watched):
    assert run(workspace, "mkdir scratch && mv old.txt scratch/", watched, time.time() + 5) == set()
    assert run(workspace, "rm scratch/old.txt", watched, time.time() + 5) == {"scratch/old.txt"}


def test_moving_and_deleting_in_one_command_is_seen(workspace, watched):
    command = "mkdir aside && mv old.txt aside/ && rm -rf aside"
    assert run(workspace, command, watched, time.time() + 5) == {"old.txt"}


def test_a_file_leaving_the_workspace_is_gone(workspace, watched, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    assert run(workspace, f"mv old.txt {outside}/", watched, time.time() + 5) == {"old.txt"}


def test_a_new_file_taking_a_freed_inode_is_not_the_old_file(workspace, watched):
    # Filesystems reuse inode numbers, so identity alone would call this a move.
    path = str(workspace.resolve() / "old.txt")
    watched[path] = (watched[path][0], (workspace / "made.txt").stat().st_ino)
    assert run(workspace, "rm old.txt", watched, 0) == {"old.txt"}
