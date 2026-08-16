"""``deepseek serve --insecure`` must refuse non-loopback bind hosts."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from deepseek_tui.cli.app import _is_loopback_host, app


def test_is_loopback_host() -> None:
    assert _is_loopback_host("127.0.0.1")
    assert _is_loopback_host("127.0.1.5")
    assert _is_loopback_host("::1")
    assert _is_loopback_host("[::1]")
    assert _is_loopback_host("localhost")
    assert _is_loopback_host("LOCALHOST")
    assert not _is_loopback_host("0.0.0.0")
    assert not _is_loopback_host("::")
    assert not _is_loopback_host("192.168.1.10")
    assert not _is_loopback_host("example.com")


def test_serve_insecure_non_loopback_refused() -> None:
    result = CliRunner().invoke(app, ["serve", "--insecure", "--host", "0.0.0.0"])
    assert result.exit_code == 1
    output = result.output + (result.stderr or "")
    assert "loopback" in output


def test_serve_insecure_loopback_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    import deepseek_tui.server as server_mod

    captured: dict[str, object] = {}

    async def _fake_run_http(options: object, *, config: object = None) -> None:
        captured["options"] = options

    monkeypatch.setattr(server_mod, "run_http", _fake_run_http)

    result = CliRunner().invoke(app, ["serve", "--insecure", "--host", "127.0.0.1"])
    assert result.exit_code == 0, result.output
    options = captured["options"]
    assert options.insecure_no_auth is True  # type: ignore[attr-defined]
    assert options.host == "127.0.0.1"  # type: ignore[attr-defined]
