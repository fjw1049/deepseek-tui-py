"""Security tests for ``McpStdioServer`` ``resources/read`` path containment.

``file://`` URIs must stay inside the served workspace and ``session://``
stems must stay inside the sessions directory — otherwise the MCP server
hands out arbitrary filesystem reads.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deepseek_tui.mcp.server import McpStdioServer


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def server(workspace: Path) -> McpStdioServer:
    return McpStdioServer(workspace=workspace)


@pytest.fixture
def sessions_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    monkeypatch.setattr(
        "deepseek_tui.config.paths.user_sessions_dir",
        lambda: sessions,
    )
    return sessions


# --- file:// containment -----------------------------------------------------


def test_file_read_inside_workspace(server: McpStdioServer, workspace: Path) -> None:
    target = workspace / "hello.txt"
    target.write_text("hello", encoding="utf-8")
    result = server._resources_read({"uri": f"file://{target}"})
    assert result["contents"][0]["text"] == "hello"


def test_file_read_outside_workspace_rejected(
    server: McpStdioServer, tmp_path: Path
) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret", encoding="utf-8")
    with pytest.raises(ValueError, match="outside workspace"):
        server._resources_read({"uri": f"file://{secret}"})


def test_file_read_traversal_rejected(
    server: McpStdioServer, workspace: Path, tmp_path: Path
) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret", encoding="utf-8")
    with pytest.raises(ValueError, match="outside workspace"):
        server._resources_read({"uri": f"file://{workspace}/../secret.txt"})


def test_file_read_system_path_rejected(server: McpStdioServer) -> None:
    with pytest.raises(ValueError, match="outside workspace"):
        server._resources_read({"uri": "file:///etc/passwd"})


# --- session:// containment ---------------------------------------------------


def test_session_read_valid_stem(
    server: McpStdioServer, sessions_dir: Path
) -> None:
    (sessions_dir / "abc123.json").write_text(
        json.dumps({"id": "abc123"}), encoding="utf-8"
    )
    result = server._resources_read({"uri": "session://abc123"})
    assert json.loads(result["contents"][0]["text"]) == {"id": "abc123"}


def test_session_read_escape_rejected(
    server: McpStdioServer, sessions_dir: Path, tmp_path: Path
) -> None:
    # A file outside sessions_dir that a `../` stem would reach.
    escaped = tmp_path / "escaped.json"
    escaped.write_text(json.dumps({"stolen": True}), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid session id"):
        server._resources_read({"uri": "session://../escaped"})


def test_session_read_deep_escape_rejected(
    server: McpStdioServer, sessions_dir: Path
) -> None:
    with pytest.raises(ValueError, match="Invalid session id"):
        server._resources_read({"uri": "session://../../../../etc/passwd"})
