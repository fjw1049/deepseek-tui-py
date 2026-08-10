"""Sensitive-file filtering for read-side tools.

``read_file`` refuses credential files outright; ``grep_files`` and
``file_search`` silently skip them during traversal. Templates
(.env.example et al.) and public keys (id_*.pub) stay accessible.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_tui.tools.file import ReadFileTool
from deepseek_tui.tools.registry import ToolContext, ToolError
from deepseek_tui.tools.search import FileSearchTool, GrepFilesTool
from deepseek_tui.tools.utils.sensitive import is_sensitive_path


async def test_read_file_refuses_env(tmp_path: Path):
    (tmp_path / ".env").write_text("SECRET=1\n", encoding="utf-8")
    with pytest.raises(ToolError, match="refusing to read sensitive file"):
        await ReadFileTool().execute(
            {"path": ".env"}, ToolContext(working_directory=tmp_path)
        )


async def test_read_file_refuses_env_variant_and_private_key(tmp_path: Path):
    for name in (".env.production", "id_rsa", "server.pem", ".netrc"):
        (tmp_path / name).write_text("secret\n", encoding="utf-8")
        with pytest.raises(ToolError, match="refusing to read sensitive file"):
            await ReadFileTool().execute(
                {"path": name}, ToolContext(working_directory=tmp_path)
            )


async def test_read_file_allows_env_example(tmp_path: Path):
    (tmp_path / ".env.example").write_text("SECRET=\n", encoding="utf-8")
    result = await ReadFileTool().execute(
        {"path": ".env.example"}, ToolContext(working_directory=tmp_path)
    )
    assert result.success
    assert "SECRET=" in result.content


async def test_read_file_allows_public_key(tmp_path: Path):
    (tmp_path / "id_rsa.pub").write_text("ssh-rsa AAAA...\n", encoding="utf-8")
    result = await ReadFileTool().execute(
        {"path": "id_rsa.pub"}, ToolContext(working_directory=tmp_path)
    )
    assert result.success
    assert "ssh-rsa" in result.content


async def test_grep_skips_sensitive_files(tmp_path: Path):
    (tmp_path / "config.py").write_text("needle\n", encoding="utf-8")
    (tmp_path / ".env").write_text("needle=secret\n", encoding="utf-8")
    result = await GrepFilesTool().execute(
        {"pattern": "needle", "path": "."}, ToolContext(working_directory=tmp_path)
    )
    assert "config.py" in result.content
    assert ".env" not in result.content
    assert result.metadata["count"] == 1


async def test_grep_skips_sensitive_files_in_files_mode(tmp_path: Path):
    (tmp_path / "config.py").write_text("needle\n", encoding="utf-8")
    (tmp_path / "credentials").write_text("needle=secret\n", encoding="utf-8")
    result = await GrepFilesTool().execute(
        {"pattern": "needle", "path": ".", "output_mode": "files_with_matches"},
        ToolContext(working_directory=tmp_path),
    )
    assert "config.py" in result.content
    assert "credentials" not in result.content


async def test_file_search_excludes_sensitive_files(tmp_path: Path):
    (tmp_path / "app.py").write_text("", encoding="utf-8")
    (tmp_path / ".env.local").write_text("SECRET=1\n", encoding="utf-8")
    (tmp_path / "id_ed25519").write_text("secret\n", encoding="utf-8")
    (tmp_path / "id_ed25519.pub").write_text("ssh-ed25519 AAAA\n", encoding="utf-8")
    result = await FileSearchTool().execute(
        {"pattern": ".env", "path": "."}, ToolContext(working_directory=tmp_path)
    )
    assert ".env.local" not in result.content
    result = await FileSearchTool().execute(
        {"pattern": "id_ed25519", "path": "."}, ToolContext(working_directory=tmp_path)
    )
    assert "id_ed25519.pub" in result.content
    assert any(line.endswith("id_ed25519") for line in result.content.splitlines()) is False


def test_is_sensitive_path_matrix():
    assert is_sensitive_path(Path(".env"))
    assert is_sensitive_path(Path(".env.production"))
    assert not is_sensitive_path(Path(".env.example"))
    assert not is_sensitive_path(Path(".env.sample"))
    assert not is_sensitive_path(Path(".env.template"))
    assert is_sensitive_path(Path("id_rsa"))
    assert is_sensitive_path(Path("id_ed25519"))
    assert not is_sensitive_path(Path("id_rsa.pub"))
    assert is_sensitive_path(Path("server.pem"))
    assert is_sensitive_path(Path("tls.key"))
    assert is_sensitive_path(Path("credentials"))
    assert is_sensitive_path(Path(".netrc"))
    assert is_sensitive_path(Path(".npmrc"))
    assert is_sensitive_path(Path(".pypirc"))
    assert not is_sensitive_path(Path("main.py"))
    assert not is_sensitive_path(Path("environment.py"))
