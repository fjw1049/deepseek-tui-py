"""Regression matrix for shell source-write hard deny / allowlist."""

from __future__ import annotations

import pytest

from deepseek_tui.workspace.shell_write_guard import check_shell_write


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
