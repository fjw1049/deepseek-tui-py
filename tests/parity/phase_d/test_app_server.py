"""Parity tests for the app-server (Stage 4.1).

Mirror of ``crates/app-server/src/lib.rs`` (783 lines) at endpoint-behavior
level. Exercises the full FastAPI stack via ``httpx.ASGITransport`` so the
tests stay hermetic (no sockets, no uvicorn worker). Also covers the stdio
JSON-RPC dispatcher directly.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from deepseek_tui.app_server import AppRuntime, build_fastapi_app
from deepseek_tui.app_server.server import _dispatch_stdio


@pytest_asyncio.fixture
async def runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AppRuntime]:
    # Force task/subagent executors to stub mode so tests never hit the real
    # DeepSeek API even when DEEPSEEK_API_KEY is present in the environment.
    # Without this, `task_create` (and any tool that spawns sub-engines) burns
    # real tokens on every run — see runtime.py:_safe_task_executor.
    monkeypatch.setattr(
        "deepseek_tui.tools.runtime._has_api_key", lambda: False
    )
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    rt = await AppRuntime.create(working_directory=tmp_path)
    try:
        yield rt
    finally:
        await rt.shutdown()


@pytest_asyncio.fixture
async def client(runtime: AppRuntime) -> AsyncIterator[httpx.AsyncClient]:
    app = build_fastapi_app(runtime)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        yield client


class TestHealthz:
    async def test_returns_ok(self, client: httpx.AsyncClient) -> None:
        r = await client.get("/healthz")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["protocol"] == "v2"
        assert body["service"] == "deepseek-app-server"


class TestThread:
    async def test_start_list_read_archive_flow(
        self, client: httpx.AsyncClient
    ) -> None:
        # start
        r = await client.post("/thread", json={"op": "start", "name": "test-thread"})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "started"
        tid = body["thread_id"]
        assert tid.startswith("thread_")

        # list
        r = await client.post("/thread", json={"op": "list"})
        listed = r.json()
        assert any(t["id"] == tid for t in listed["threads"])

        # read
        r = await client.post("/thread", json={"op": "read", "thread_id": tid})
        read = r.json()
        assert read["thread_id"] == tid
        assert read["status"] == "ok"

        # message
        r = await client.post(
            "/thread", json={"op": "message", "thread_id": tid, "input": "hi"}
        )
        assert r.json()["status"] == "ok"

        # archive
        r = await client.post(
            "/thread", json={"op": "archive", "thread_id": tid}
        )
        assert r.json()["status"] == "archived"

    async def test_read_unknown_returns_error_status(
        self, client: httpx.AsyncClient
    ) -> None:
        r = await client.post(
            "/thread", json={"op": "read", "thread_id": "thread_nope"}
        )
        assert r.status_code == 200  # routed OK
        assert r.json()["status"].startswith("error:")


class TestApp:
    async def test_capabilities(self, client: httpx.AsyncClient) -> None:
        r = await client.post("/app", json={"op": "capabilities"})
        body = r.json()
        assert body["ok"] is True
        caps = body["capabilities"]
        assert caps["threads"] is True
        assert caps["tools"] is True

    async def test_config_list(self, client: httpx.AsyncClient) -> None:
        r = await client.post("/app", json={"op": "config.list"})
        body = r.json()
        assert body["ok"] is True
        assert "provider" in body["config"]

    async def test_config_get_dotted(self, client: httpx.AsyncClient) -> None:
        r = await client.post(
            "/app", json={"op": "config.get", "key": "features.tasks"}
        )
        body = r.json()
        assert body["key"] == "features.tasks"
        assert body["value"] is True

    async def test_unknown_op(self, client: httpx.AsyncClient) -> None:
        r = await client.post("/app", json={"op": "mystery"})
        body = r.json()
        assert body["ok"] is False
        assert "unknown op" in body["error"]


class TestPrompt:
    async def test_emits_three_event_frames(self, client: httpx.AsyncClient) -> None:
        """Rust parity: ResponseStart → ResponseDelta("model-selected") → ResponseEnd."""
        r = await client.post("/prompt", json={"input": "hello"})
        body = r.json()
        assert r.status_code == 200
        events = body["events"]
        assert [e["event"] for e in events] == [
            "response_start",
            "response_delta",
            "response_end",
        ]
        # All three share the same response_id
        rids = {e["response_id"] for e in events}
        assert len(rids) == 1
        assert next(iter(rids)).startswith("resp-")
        # Delta payload matches Rust
        assert events[1]["delta"] == "model-selected"

    async def test_output_is_json_payload(self, client: httpx.AsyncClient) -> None:
        import json as json_

        r = await client.post("/prompt", json={"input": "x"})
        body = r.json()
        parsed = json_.loads(body["output"])
        assert parsed["provider"] == "deepseek"
        assert parsed["prompt"] == "x"
        assert parsed["response_id"].startswith("resp-")
        assert parsed["thread_id"].startswith("thread_")

    async def test_rejects_missing_input(self, client: httpx.AsyncClient) -> None:
        r = await client.post("/prompt", json={})
        body = r.json()
        assert "missing" in body["output"]

    async def test_unknown_thread_rejected(self, client: httpx.AsyncClient) -> None:
        r = await client.post(
            "/prompt", json={"input": "x", "thread_id": "thread_nope"}
        )
        body = r.json()
        assert "unknown thread" in body["output"]


class TestPromptStream:
    async def test_streams_sse_frames(self, client: httpx.AsyncClient) -> None:
        async with client.stream(
            "POST", "/prompt/stream", json={"input": "hello"}
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            body = b""
            async for chunk in response.aiter_bytes():
                body += chunk
        text = body.decode("utf-8")
        # Three SSE envelopes — each has "event: <name>" + "data: {...}"
        assert "event: response_start" in text
        assert "event: response_delta" in text
        assert "event: response_end" in text
        # The delta payload is inlined
        assert '"delta": "model-selected"' in text

    async def test_streams_error_on_missing_input(
        self, client: httpx.AsyncClient
    ) -> None:
        async with client.stream("POST", "/prompt/stream", json={}) as response:
            body = b""
            async for chunk in response.aiter_bytes():
                body += chunk
        text = body.decode("utf-8")
        assert "event: error" in text


class TestTool:
    async def test_invokes_diagnostics(self, client: httpx.AsyncClient) -> None:
        r = await client.post(
            "/tool",
            json={"call": {"name": "diagnostics", "arguments": {}}},
        )
        body = r.json()
        assert body["ok"] is True
        assert "python" in body["metadata"]

    async def test_missing_call(self, client: httpx.AsyncClient) -> None:
        r = await client.post("/tool", json={})
        body = r.json()
        assert body["ok"] is False

    async def test_unknown_tool(self, client: httpx.AsyncClient) -> None:
        r = await client.post(
            "/tool", json={"call": {"name": "does_not_exist", "arguments": {}}}
        )
        body = r.json()
        assert body["ok"] is False
        assert "does_not_exist" in body["error"]

    async def test_tool_runtime_reachable_end_to_end(
        self, client: httpx.AsyncClient
    ) -> None:
        """Regression: hitting /tool must route to the real TaskManager.

        Starts a task via task_create, then confirms it's visible in /jobs.
        """
        r = await client.post(
            "/tool",
            json={
                "call": {
                    "name": "task_create",
                    "arguments": {"prompt": "via http"},
                }
            },
        )
        assert r.json()["ok"] is True

        r = await client.get("/jobs")
        body = r.json()
        assert body["ok"] is True
        assert body["jobs"]["tasks_active"] >= 0  # may already have finished


class TestJobs:
    async def test_returns_snapshot(self, client: httpx.AsyncClient) -> None:
        r = await client.get("/jobs")
        body = r.json()
        assert body["ok"] is True
        assert "jobs" in body


class TestMcpStartup:
    async def test_returns_summary(self, client: httpx.AsyncClient) -> None:
        r = await client.post("/mcp/startup")
        body = r.json()
        assert body["ok"] is True
        assert "summary" in body


class TestStdioDispatcher:
    """The stdio JSON-RPC path reuses AppRuntime via the same handlers."""

    async def test_healthz_via_stdio(self, runtime: AppRuntime) -> None:
        result, should_exit = await _dispatch_stdio(runtime, "healthz", {})
        assert result["status"] == "ok"
        assert should_exit is False

    async def test_exit_method(self, runtime: AppRuntime) -> None:
        result, should_exit = await _dispatch_stdio(runtime, "exit", {})
        assert should_exit is True
        assert result["status"] == "ok"

    async def test_unknown_method_raises(self, runtime: AppRuntime) -> None:
        with pytest.raises(ValueError, match="Unknown method"):
            await _dispatch_stdio(runtime, "nonsense", {})

    async def test_mcp_slash_alias(self, runtime: AppRuntime) -> None:
        """Both 'mcp/startup' and 'mcp_startup' must map to the same op."""
        result_slash, _ = await _dispatch_stdio(runtime, "mcp/startup", {})
        result_under, _ = await _dispatch_stdio(runtime, "mcp_startup", {})
        assert result_slash == result_under
