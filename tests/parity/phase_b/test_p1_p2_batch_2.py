"""Parity tests for the second P1/P2 batch (2026-05-10).

Covers:
- F1 cycle/seam manager wired into Engine (off by default; firing path)
- F2 TUI Rust-parity keybindings + picker action handlers
- F3 App Server ``/v1`` prefix + thread events SSE + resume + summary
- F4 ``_should_include_reasoning`` broadened to match Rust markers
- F5 Config sub-sections (notifications / network / skills / memory)
- F6 MCP server resources/list session URIs + deepseek meta-tool registration
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from deepseek_tui.client.base import LLMClient
from deepseek_tui.client.chat_messages import _should_include_reasoning
from deepseek_tui.config.models import (
    Config,
    MemoryConfig,
    NetworkPolicyConfig,
    NotificationsConfig,
    SkillsConfig,
)
from deepseek_tui.engine.cycle_manager import CycleConfig, should_advance_cycle
from deepseek_tui.engine.engine import Engine
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.protocol.requests import MessageRequest
from deepseek_tui.protocol.responses import StreamDone, StreamEvent

# --- F1 cycle/seam wiring -------------------------------------------------


class _NopClient(LLMClient):
    async def stream_chat_completion(
        self, request: MessageRequest
    ) -> AsyncIterator[StreamEvent]:
        yield StreamDone()


def test_engine_cycle_disabled_by_default() -> None:
    engine = Engine(handle=EngineHandle(), client=_NopClient())
    assert engine.cycle_config.enabled is False
    assert engine.seam_manager is None


@pytest.mark.asyncio
async def test_engine_create_picks_up_cycle_flag(
    tmp_path: Any,
) -> None:
    """``Engine.create`` reads ``Config.cycle_enabled`` / ``Config.seam_enabled``."""
    cfg = Config()
    cfg.cycle_enabled = True
    cfg.seam_enabled = True
    cfg.state.database_path = tmp_path / "state.db"
    engine = await Engine.create(
        EngineHandle(),
        _NopClient(),
        config=cfg,
        working_directory=tmp_path,
    )
    try:
        assert engine.cycle_config.enabled is True
        assert engine.seam_manager is not None
        assert engine._cycle_session_id  # populated to non-empty hex
    finally:
        await engine.shutdown()


def test_should_advance_cycle_threshold_logic() -> None:
    """Pure-logic helper used by Engine; mirrors Rust signature."""
    cfg = CycleConfig(enabled=True, threshold_tokens=100)
    assert should_advance_cycle(150, 0, "deepseek-chat", cfg, in_flight=False)
    assert not should_advance_cycle(50, 0, "deepseek-chat", cfg, in_flight=False)
    assert not should_advance_cycle(150, 0, "deepseek-chat", cfg, in_flight=True)
    cfg_off = CycleConfig(enabled=False, threshold_tokens=100)
    assert not should_advance_cycle(150, 0, "deepseek-chat", cfg_off, in_flight=False)


# --- F2 TUI keybindings ---------------------------------------------------


def test_deepseek_tui_has_rust_parity_bindings() -> None:
    from deepseek_tui.tui.app import DeepSeekTUI

    keys = {b.key for b in DeepSeekTUI.BINDINGS}
    for required in ("ctrl+r", "ctrl+m", "ctrl+p", "tab", "ctrl+l", "pageup", "pagedown"):
        assert required in keys, f"missing binding: {required}"


def test_deepseek_tui_action_methods_exist() -> None:
    from deepseek_tui.tui.app import DeepSeekTUI

    for action in (
        "action_open_session_picker",
        "action_open_model_picker",
        "action_open_file_picker",
        "action_cycle_mode",
        "action_clear_transcript",
        "action_transcript_page_up",
        "action_transcript_page_down",
        "action_toggle_thinking",
    ):
        assert callable(getattr(DeepSeekTUI, action)), f"missing action: {action}"


# --- F3 App Server /v1 + new routes ---------------------------------------


async def _build_test_app(tmp_path: Any) -> Any:
    """Build a FastAPI app with a real AppRuntime so routes don't 500."""
    from deepseek_tui.app_server.runtime import AppRuntime
    from deepseek_tui.app_server.server import build_fastapi_app

    cfg = Config()
    cfg.state.database_path = tmp_path / "state.db"
    runtime = await AppRuntime.create(config=cfg, working_directory=tmp_path)
    return build_fastapi_app(runtime), runtime


@pytest.mark.asyncio
async def test_v1_prefix_mirrors_root_routes(tmp_path: Any) -> None:
    import httpx

    app, runtime = await _build_test_app(tmp_path)
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            r1 = await client.get("/healthz")
            r2 = await client.get("/v1/healthz")
        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.json() == r2.json()
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_threads_summary_route_returns_ok_when_unwired(
    tmp_path: Any,
) -> None:
    """Route exists and gracefully reports the manager isn't configured."""
    import httpx

    app, runtime = await _build_test_app(tmp_path)
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            r = await client.get("/threads/summary")
        body = r.json()
        assert r.status_code == 200
        assert body["ok"] is False
        assert "thread manager" in body["error"]
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_thread_resume_route_exists(tmp_path: Any) -> None:
    import httpx

    app, runtime = await _build_test_app(tmp_path)
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            r = await client.post("/threads/some-id/resume")
        assert r.status_code == 200
        assert r.json()["ok"] is False
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_thread_events_stream_endpoint_responds_sse(tmp_path: Any) -> None:
    import httpx

    app, runtime = await _build_test_app(tmp_path)
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            r = await client.get("/threads/x/events/stream")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        assert "event:" in r.text
    finally:
        await runtime.shutdown()


# --- F4 reasoning model detection -----------------------------------------


@pytest.mark.parametrize(
    "model",
    [
        "deepseek-r1",
        "deepseek-r2-think",
        "deepseek-reasoner",
        "deepseek-v3.2",
        "deepseek-v4-pro",
        "deepseek-v4-flash-thinking",
    ],
)
def test_reasoning_models_match_rust_markers(model: str) -> None:
    assert _should_include_reasoning(model, None) is True


@pytest.mark.parametrize(
    "effort",
    ["off", "OFF", "disabled", "none", "false", "  off  "],
)
def test_reasoning_effort_off_disables(effort: str) -> None:
    assert _should_include_reasoning("deepseek-v4-pro", effort) is False


def test_non_deepseek_model_never_replays_reasoning() -> None:
    assert _should_include_reasoning("gpt-4o", None) is False


# --- F5 Config sub-sections -----------------------------------------------


def test_config_accepts_notifications_section() -> None:
    cfg = Config.model_validate(
        {"notifications": {"method": "osc9", "threshold_secs": 60.0, "enabled": True}}
    )
    assert isinstance(cfg.notifications, NotificationsConfig)
    assert cfg.notifications.method == "osc9"
    assert cfg.notifications.threshold_secs == 60.0


def test_config_accepts_network_section() -> None:
    cfg = Config.model_validate(
        {"network": {"enabled": True, "default_action": "allow", "rules": [{"host": "x"}]}}
    )
    assert isinstance(cfg.network, NetworkPolicyConfig)
    assert cfg.network.default_action == "allow"
    assert cfg.network.rules == [{"host": "x"}]


def test_config_accepts_skills_section() -> None:
    cfg = Config.model_validate(
        {"skills": {"enabled": True, "registry_url": "https://example/registry"}}
    )
    assert isinstance(cfg.skills, SkillsConfig)
    assert cfg.skills.registry_url == "https://example/registry"


def test_config_accepts_memory_section() -> None:
    cfg = Config.model_validate(
        {"memory": {"enabled": False, "mode": "auto", "max_entries": 1000}}
    )
    assert isinstance(cfg.memory, MemoryConfig)
    assert cfg.memory.mode == "auto"
    assert cfg.memory.max_entries == 1000


def test_config_accepts_tools_file() -> None:
    cfg = Config.model_validate({"tools_file": "/tmp/tools.toml"})
    assert cfg.tools_file is not None
    assert str(cfg.tools_file).endswith("tools.toml")


# --- F6 MCP server enrichments --------------------------------------------


@pytest.mark.asyncio
async def test_mcp_server_lists_deepseek_meta_tool(tmp_path: Any) -> None:
    """``deepseek`` meta-tool appears in tools/list output."""
    from deepseek_tui.mcp.server import McpStdioServer

    server = McpStdioServer(workspace=tmp_path)
    await server._ensure_runtime()
    try:
        result = server._tools_list()
        names = {t["name"] for t in result["tools"]}
        assert "deepseek" in names, f"deepseek meta-tool missing from {names}"
    finally:
        if server._runtime is not None:
            await server._runtime.shutdown()


@pytest.mark.asyncio
async def test_mcp_server_lists_session_resources(tmp_path: Any, monkeypatch) -> None:
    """``resources/list`` includes ``session://*`` for each saved session JSON."""
    fake_home = tmp_path / "home"
    sessions = fake_home / ".deepseek" / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    (sessions / "alpha.json").write_text("{}", encoding="utf-8")
    (sessions / "beta.json").write_text("{}", encoding="utf-8")

    def _fake_path() -> Any:
        return fake_home / ".deepseek" / "config.toml"

    monkeypatch.setattr(
        "deepseek_tui.config.paths.default_config_path", _fake_path
    )

    from deepseek_tui.mcp.server import McpStdioServer

    server = McpStdioServer(workspace=tmp_path)
    result = server._resources_list()
    uris = {r["uri"] for r in result["resources"]}
    assert "session://alpha" in uris
    assert "session://beta" in uris


@pytest.mark.asyncio
async def test_mcp_server_resources_read_session(tmp_path: Any, monkeypatch) -> None:
    fake_home = tmp_path / "home"
    sessions = fake_home / ".deepseek" / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    target = sessions / "demo.json"
    target.write_text('{"hello":"world"}', encoding="utf-8")
    monkeypatch.setattr(
        "deepseek_tui.config.paths.default_config_path",
        lambda: fake_home / ".deepseek" / "config.toml",
    )

    from deepseek_tui.mcp.server import McpStdioServer

    server = McpStdioServer(workspace=tmp_path)
    out = server._resources_read({"uri": "session://demo"})
    assert out["contents"][0]["text"] == '{"hello":"world"}'
