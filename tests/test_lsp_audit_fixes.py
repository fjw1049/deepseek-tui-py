import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.integrations.lsp import Language, LspClient, LspConfig, LspManager


@pytest.mark.parametrize("stage", ["send", "response"])
async def test_cancel_cleans_pending(stage):
    entered = asyncio.Event()

    async def send(message):
        entered.set()
        if stage == "send":
            await asyncio.Event().wait()

    client = LspClient(SimpleNamespace(send=send), Language.PYTHON)
    task = asyncio.create_task(client._request("fixture", {}))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert client._pending == {}


async def test_send_deadline_is_bounded():
    async def send(message):
        await asyncio.Event().wait()

    client = LspClient(SimpleNamespace(send=send), Language.PYTHON, request_timeout=0.01)
    with pytest.raises(asyncio.TimeoutError):
        await client._request("fixture", {})
    assert not client._pending


async def test_initialize_timeout_closes_transport():
    transport = SimpleNamespace(
        start=AsyncMock(),
        send=AsyncMock(),
        receive=AsyncMock(side_effect=asyncio.Event().wait),
        close=AsyncMock(),
    )
    client = LspClient(transport, Language.PYTHON, request_timeout=0.01)
    with pytest.raises(asyncio.TimeoutError):
        await client.start()
    transport.close.assert_awaited_once()
    assert not client.is_running
    assert not client._pending


@pytest.fixture
def fake_client(monkeypatch):
    class Fake:
        instances = []
        gate = None

        def __init__(self, *args):
            self.is_running = False
            self.closed = False
            self.instances.append(self)

        async def start(self):
            if self.gate:
                await self.gate.wait()
            self.is_running = True

        async def close(self):
            self.closed = True
            self.is_running = False

    monkeypatch.setattr("deepseek_tui.integrations.lsp.LspClient", Fake)
    return Fake


async def test_same_language_shares_start_and_waiter_can_cancel(fake_client):
    fake_client.gate = asyncio.Event()
    mgr = LspManager(LspConfig())
    a = asyncio.create_task(mgr._get_or_spawn_client(Language.PYTHON))
    b = asyncio.create_task(mgr._get_or_spawn_client(Language.PYTHON))
    for _ in range(4):
        await asyncio.sleep(0)
    assert len(fake_client.instances) == 1
    a.cancel()
    with pytest.raises(asyncio.CancelledError):
        await a
    fake_client.gate.set()
    assert await b is fake_client.instances[0]
    await mgr.close_all()
    assert fake_client.instances[0].closed


async def test_different_languages_start_in_parallel_and_close_during_start(fake_client):
    fake_client.gate = asyncio.Event()
    mgr = LspManager(LspConfig())
    tasks = [
        asyncio.create_task(mgr._get_or_spawn_client(lang))
        for lang in (Language.PYTHON, Language.GO)
    ]
    for _ in range(4):
        await asyncio.sleep(0)
    assert len(fake_client.instances) == 2
    await mgr.close_all()
    assert all(c.closed for c in fake_client.instances)
    assert not mgr._clients
    assert not mgr._starting
    results = await asyncio.gather(*tasks, return_exceptions=True)
    assert all(isinstance(result, asyncio.CancelledError) for result in results)


async def test_dead_client_replaced(fake_client):
    mgr = LspManager(LspConfig())
    first = await mgr._get_or_spawn_client(Language.PYTHON)
    first.is_running = False
    second = await mgr._get_or_spawn_client(Language.PYTHON)
    assert first is not second and first.closed
    await mgr.close_all()


@pytest.mark.parametrize("filename", ["a b.py", "中文.py", "a#b%.py"])
def test_uri_roundtrip_and_version_filter(tmp_path, filename):
    client = LspClient(SimpleNamespace(), Language.PYTHON)
    path = tmp_path / filename
    key = path.as_posix()
    client._versions[key] = 2
    client._handle_diagnostics(
        {"uri": path.as_uri(), "version": 1, "diagnostics": [{"message": "old"}]}
    )
    assert client.get_diagnostics(path) == []
    assert not client._publication_event(key).is_set()
    client._handle_diagnostics(
        {"uri": path.as_uri(), "version": 2, "diagnostics": [{"message": "new"}]}
    )
    assert client.get_diagnostics(path)[0].message == "new"


async def test_document_sync_serializes_versions(tmp_path):
    client = None
    sent = []
    first_sent = asyncio.Event()

    async def send(message):
        sent.append(message)
        first_sent.set()

    client = LspClient(SimpleNamespace(send=send), Language.PYTHON)
    path = tmp_path / "a b.py"
    first = asyncio.create_task(client.sync_and_await_diagnostics(path, "one", 1))
    await first_sent.wait()
    second = asyncio.create_task(client.sync_and_await_diagnostics(path, "two", 1))
    await asyncio.sleep(0)
    assert len(sent) == 1
    client._handle_diagnostics(
        {"uri": path.as_uri(), "version": 1, "diagnostics": [{"message": "one"}]}
    )
    assert (await first)[0].message == "one"
    for _ in range(5):
        if len(sent) == 2:
            break
        await asyncio.sleep(0)
    assert sent[1]["params"]["textDocument"]["version"] == 2
    assert sent[1]["params"]["textDocument"]["uri"] == path.as_uri()
    client._handle_diagnostics(
        {"uri": path.as_uri(), "version": 1, "diagnostics": [{"message": "stale"}]}
    )
    assert not second.done()
    client._handle_diagnostics({"uri": path.as_uri(), "version": 2, "diagnostics": []})
    assert await second == []
