"""``resolve_runtime_auth`` must fall back to ``~/.deepseek/runtime.token``.

Counterpart to the Electron-side ``resolveEffectiveRuntimeToken`` so spawn /
HTTP / SSE all converge on the same secret without explicit plumbing. The
priority order matters: explicit CLI / env beats the cached file, and the
file beats fresh generation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_tui.app_server.runtime_api.auth import (
    resolve_runtime_auth,
    write_runtime_token_file,
)


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("DEEPSEEK_HOME", str(home))
    return home


def test_resolve_prefers_cli_over_file(isolated_home: Path) -> None:
    write_runtime_token_file("from-file")
    auth = resolve_runtime_auth("from-cli", None)
    assert auth.token == "from-cli"
    assert not auth.generated


def test_resolve_prefers_env_over_file(isolated_home: Path) -> None:
    write_runtime_token_file("from-file")
    auth = resolve_runtime_auth(None, "from-env")
    assert auth.token == "from-env"
    assert not auth.generated


def test_resolve_reads_token_file_when_no_explicit(isolated_home: Path) -> None:
    write_runtime_token_file("from-file")
    auth = resolve_runtime_auth(None, None)
    assert auth.token == "from-file"
    assert not auth.generated


def test_resolve_generates_when_no_source(isolated_home: Path) -> None:
    auth = resolve_runtime_auth(None, None)
    assert auth.token is not None
    assert auth.generated


def test_resolve_insecure_returns_none_when_no_source(isolated_home: Path) -> None:
    auth = resolve_runtime_auth(None, None, insecure_no_auth=True)
    assert auth.token is None
    assert not auth.generated
