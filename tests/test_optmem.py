"""OptMem wake helper unit tests."""

from __future__ import annotations

from pathlib import Path

from deepseek_tui.engine.optmem import (
    format_optmem_wake_reminder,
    optmem_available,
    run_memo_wake,
)


def test_format_optmem_wake_reminder_wraps_body() -> None:
    text = format_optmem_wake_reminder("#0 hello\nYou are awake.")
    assert "[OptMem]" in text
    assert "#0 hello" in text
    assert "You are awake." in text


def test_run_memo_wake_missing_tool(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPTMEM_MEMO", str(tmp_path / "missing-memo"))
    monkeypatch.setenv("MEMORY_DIR", str(tmp_path / "memory"))
    (tmp_path / "memory").mkdir()
    assert run_memo_wake() is None
    assert optmem_available() is False


def test_run_memo_wake_follows_parts(tmp_path: Path, monkeypatch) -> None:
    memo = tmp_path / "memo"
    memory = tmp_path / "memory"
    memory.mkdir()
    script = tmp_path / "memo.py"
    # Fake memo: first wake asks for part 2; second prints awake.
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "args = sys.argv[1:]\n"
        "if args == ['wake']:\n"
        "    print('part one')\n"
        f"    print('Not awake yet. Run: {memo} wake 2 1')\n"
        "elif args == ['wake', '2', '1']:\n"
        "    print('part two')\n"
        "    print('You are awake.')\n"
        "else:\n"
        "    sys.exit(2)\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    memo.symlink_to(script)
    monkeypatch.setenv("OPTMEM_MEMO", str(memo))
    monkeypatch.setenv("MEMORY_DIR", str(memory))
    assert optmem_available()
    out = run_memo_wake()
    assert out is not None
    assert "part one" in out
    assert "part two" in out
    assert "You are awake." in out
