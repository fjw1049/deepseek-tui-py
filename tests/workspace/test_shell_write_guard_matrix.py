"""Regression matrix for shell source-write hard deny / allowlist."""

from __future__ import annotations

import pytest

from deepseek_tui.config.paths import user_worktrees_dir
from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.tools.shell import check_command_policy
from deepseek_tui.workspace.shell_write_guard import (
    check_managed_worktree_git,
    check_shell_write,
)


@pytest.mark.parametrize(
    "command",
    [
        "sed -i 's/foo/bar/' src/main.py",
        "sed -i.bak 's/a/b/' packages/app/src/x.ts",
        "sed -i'' -e 's/a/b/' src/main.py",
        "perl -pi -e 's/a/b/' lib/foo.rb",
        "perl -i -pe 's/a/b/' src/a.py",
        "ruby -i -pe 'sub!' src/a.rb",
        "echo hi > src/foo.py",
        "echo hi >> src/foo.py",
        "printf 'x' 1> src/out.ts",
        "cat > src/foo.py <<'EOF'\nprint(1)\nEOF",
        "cat <<EOF > src/foo.py\nx\nEOF",
        "tee src/foo.py <<'EOF'\nx\nEOF",
        "python3 -c \"open('src/a.py','w').write('x')\"",
        'python3 -c \'Path("src/a.py").write_text("x")\'',
        "node -e \"require('fs').writeFileSync('src/a.js','x')\"",
        "cp scratch/x.py src/dest.py",
        "mv scratch/x.py src/dest.py",
        "mv src/a.py /tmp/out.py",
        "rm src/foo.py",
        "rm -f packages/workbench/src/a.ts",
        "bash -c \"sed -i 's/a/b/' src/main.py\"",
        "sh -c 'echo x > src/foo.py'",
        "bash -c \"python3 -c \\\"open('src/a.py','w').write('x')\\\"\"",
    ],
)
def test_denies_source_mutations(command: str) -> None:
    v = check_shell_write(command)
    assert not v.allowed, f"expected deny for: {command}"
    assert "edit_file" in v.reason or "apply_patch" in v.reason or "write_file" in v.reason


@pytest.mark.parametrize(
    "command",
    [
        "pytest tests/ -q",
        "python -m pytest",
        "npm test",
        "cat src/foo.py",
        "rg TODO src/",
        "ls src/",
        "git status",
        "git diff HEAD -- src/foo.py",
        "echo hi > scratch/demo.py",
        "cat > scratch/demo.py <<'EOF'\nprint(1)\nEOF",
        "echo x > /tmp/out.txt",
        "echo x > dist/bundle.js",
        "echo x > build/out.txt",
        "echo x > node_modules/.cache/x",
        "cp src/a.py scratch/copy.py",
        "mv scratch/a.py scratch/b.py",
        "rm scratch/tmp.py",
        "sed 's/a/b/' src/foo.py",  # no -i: stdout only
        "python3 -c \"print(open('src/a.py').read())\"",
        "bash -c 'pytest -q'",
    ],
)
def test_allows_reads_and_allowlisted_writes(command: str) -> None:
    v = check_shell_write(command)
    assert v.allowed, f"expected allow for: {command} reason={v.reason}"


def test_fail_closed_python_write_without_extractable_path() -> None:
    v = check_shell_write("python3 -c 'open(p,\"w\").write(\"x\")'")
    assert not v.allowed


def test_ruby_include_path_not_treated_as_inplace() -> None:
    v = check_shell_write("ruby -Ilib -e 'puts 1'")
    assert v.allowed


def test_path_write_text_denied() -> None:
    v = check_shell_write('python3 -c \'from pathlib import Path; Path("src/a.py").write_text("x")\'')
    assert not v.allowed


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
