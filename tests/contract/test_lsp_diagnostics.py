"""The post-edit diagnostics path, which had no test coverage at all.

That mattered more than it looks: the feature ships disabled, so nothing
exercised it, and three defects sat in it that between them made turning it
on either slow or pointless. These tests pin the fixed behaviour so the
default can be flipped on evidence rather than hope.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from deepseek_tui.integrations.lsp import (
    Diagnostic,
    Language,
    LspClient,
    LspConfig,
    LspManager,
    LspTransport,
    Severity,
    detect_language,
    render_blocks,
)


class _FakeTransport(LspTransport):
    """A server that answers ``initialize`` and publishes on every sync."""

    def __init__(self, *, diagnostics_by_uri: dict[str, list[dict[str, Any]]] | None = None,
                 publish: bool = True) -> None:
        self.sent: list[dict[str, Any]] = []
        self._inbox: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._diagnostics_by_uri = diagnostics_by_uri or {}
        self._publish = publish

    async def start(self) -> None:
        return None

    async def send(self, message: dict[str, Any]) -> None:
        self.sent.append(message)
        method = message.get("method")
        if "id" in message:
            await self._inbox.put({"jsonrpc": "2.0", "id": message["id"], "result": {}})
        if method in ("textDocument/didOpen", "textDocument/didChange") and self._publish:
            uri = message["params"]["textDocument"]["uri"]
            await self._inbox.put(
                {
                    "jsonrpc": "2.0",
                    "method": "textDocument/publishDiagnostics",
                    "params": {
                        "uri": uri,
                        "diagnostics": self._diagnostics_by_uri.get(uri, []),
                    },
                }
            )

    async def receive(self) -> dict[str, Any] | None:
        return await self._inbox.get()

    async def close(self) -> None:
        await self._inbox.put(None)

    def methods(self) -> list[str]:
        return [m["method"] for m in self.sent if "method" in m]


def _error(message: str) -> dict[str, Any]:
    return {
        "severity": 1,
        "range": {"start": {"line": 4, "character": 2}},
        "message": message,
        "source": "pyright",
    }


async def _client(transport: _FakeTransport) -> LspClient:
    client = LspClient(transport, Language.PYTHON)
    await client.start()
    return client


# --- document lifecycle ----------------------------------------------------


@pytest.mark.asyncio
async def test_a_file_is_opened_before_it_is_changed() -> None:
    """The bug this replaces keyed didOpen on the conversation's turn number,
    so any file first edited after turn 1 only ever got didChange — which a
    server drops, silently yielding no diagnostics for most of a session."""
    transport = _FakeTransport()
    client = await _client(transport)

    await client.sync_and_await_diagnostics(Path("/ws/late.py"), "x = 1", 1.0)

    assert "textDocument/didOpen" in transport.methods()
    assert "textDocument/didChange" not in transport.methods()


@pytest.mark.asyncio
async def test_the_second_edit_of_a_file_is_a_change() -> None:
    transport = _FakeTransport()
    client = await _client(transport)
    path = Path("/ws/a.py")

    await client.sync_and_await_diagnostics(path, "x = 1", 1.0)
    await client.sync_and_await_diagnostics(path, "x = 2", 1.0)

    assert transport.methods().count("textDocument/didOpen") == 1
    assert transport.methods().count("textDocument/didChange") == 1


@pytest.mark.asyncio
async def test_versions_increase_per_document_not_per_turn() -> None:
    """Two edits inside one turn must not reuse a version number."""
    transport = _FakeTransport()
    client = await _client(transport)
    path = Path("/ws/a.py")

    for _ in range(3):
        await client.sync_and_await_diagnostics(path, "x", 1.0)

    versions = [
        m["params"]["textDocument"]["version"]
        for m in transport.sent
        if m.get("method", "").startswith("textDocument/did")
    ]
    assert versions == sorted(set(versions))


@pytest.mark.asyncio
async def test_each_file_gets_its_own_open() -> None:
    transport = _FakeTransport()
    client = await _client(transport)

    await client.sync_and_await_diagnostics(Path("/ws/a.py"), "x", 1.0)
    await client.sync_and_await_diagnostics(Path("/ws/b.py"), "y", 1.0)

    assert transport.methods().count("textDocument/didOpen") == 2


# --- waiting for the verdict ----------------------------------------------


@pytest.mark.asyncio
async def test_it_returns_as_soon_as_the_server_publishes() -> None:
    """The old code slept a flat 5s per edit, clean file or not."""
    uri = "file:///ws/a.py"
    transport = _FakeTransport(diagnostics_by_uri={uri: [_error("undefined name")]})
    client = await _client(transport)

    loop = asyncio.get_running_loop()
    started = loop.time()
    found = await client.sync_and_await_diagnostics(Path("/ws/a.py"), "x", 5.0)

    assert loop.time() - started < 1.0, "must not wait out the timeout"
    assert [d.message for d in found] == ["undefined name"]


@pytest.mark.asyncio
async def test_a_clean_file_also_returns_immediately() -> None:
    """Servers publish an empty list for a clean file; that is an answer."""
    transport = _FakeTransport(diagnostics_by_uri={})
    client = await _client(transport)

    loop = asyncio.get_running_loop()
    started = loop.time()
    assert await client.sync_and_await_diagnostics(Path("/ws/a.py"), "x", 5.0) == []
    assert loop.time() - started < 1.0


@pytest.mark.asyncio
async def test_a_silent_server_is_bounded_by_the_timeout() -> None:
    transport = _FakeTransport(publish=False)
    client = await _client(transport)

    assert await client.sync_and_await_diagnostics(Path("/ws/a.py"), "x", 0.05) == []


@pytest.mark.asyncio
async def test_a_stale_publication_does_not_answer_the_next_edit() -> None:
    """The event is cleared before the sync, so the wait is for this edit."""
    transport = _FakeTransport(publish=False)
    client = await _client(transport)
    path = Path("/ws/a.py")

    client._handle_diagnostics(  # noqa: SLF001 — simulating an earlier publish
        {"uri": "file:///ws/a.py", "diagnostics": [_error("old")]}
    )
    loop = asyncio.get_running_loop()
    started = loop.time()
    assert await client.sync_and_await_diagnostics(path, "x", 0.05) == []
    assert loop.time() - started >= 0.05


# --- manager-level behaviour ----------------------------------------------


class _StubManager(LspManager):
    def __init__(self, config: LspConfig, client: LspClient | None) -> None:
        super().__init__(config)
        self._stub_client = client
        self.spawn_attempts = 0

    async def _get_or_spawn_client(self, lang: Language) -> LspClient | None:
        self.spawn_attempts += 1
        return self._stub_client


@pytest.mark.asyncio
async def test_disabled_manager_does_no_work() -> None:
    manager = _StubManager(LspConfig(enabled=False), None)
    assert await manager.diagnostics_for(Path("/ws/a.py"), "x") == []
    assert manager.spawn_attempts == 0


@pytest.mark.asyncio
async def test_an_unknown_language_is_skipped() -> None:
    manager = _StubManager(LspConfig(enabled=True), None)
    assert await manager.diagnostics_for(Path("/ws/notes.txt"), "x") == []
    assert manager.spawn_attempts == 0


@pytest.mark.asyncio
async def test_warnings_are_dropped_unless_asked_for() -> None:
    uri = "file:///ws/a.py"
    transport = _FakeTransport(
        diagnostics_by_uri={
            uri: [
                _error("real problem"),
                {
                    "severity": 2,
                    "range": {"start": {"line": 0, "character": 0}},
                    "message": "unused import",
                },
            ]
        }
    )
    client = await _client(transport)

    quiet = _StubManager(LspConfig(enabled=True), client)
    (block,) = await quiet.diagnostics_for(Path("/ws/a.py"), "x")
    assert [d.message for d in block.diagnostics] == ["real problem"]


@pytest.mark.asyncio
async def test_a_missing_server_is_not_retried_every_edit() -> None:
    """Every edit used to re-fork a doomed subprocess for the whole session."""
    manager = LspManager(LspConfig(enabled=True, servers={"python": ["definitely-not-a-real-lsp"]}))

    for _ in range(3):
        assert await manager.diagnostics_for(Path("/ws/a.py"), "x") == []

    assert manager._unavailable == {Language.PYTHON}  # noqa: SLF001


def test_language_detection_drives_the_gate() -> None:
    assert detect_language(Path("a.py")) is Language.PYTHON
    assert detect_language(Path("notes.txt")) is Language.OTHER
    assert detect_language(Path("Makefile")) is Language.OTHER


# --- rendering -------------------------------------------------------------


def test_blocks_render_with_location_and_source() -> None:
    rendered = render_blocks(
        [
            type(
                "B",
                (),
                {
                    "path": "src/a.py",
                    "diagnostics": [Diagnostic(Severity.ERROR, 5, 3, "boom", "pyright")],
                },
            )()
        ]
    )
    assert "**src/a.py**" in rendered
    assert "5:3 error [pyright]: boom" in rendered


def test_no_blocks_render_to_nothing() -> None:
    assert render_blocks([]) == ""
