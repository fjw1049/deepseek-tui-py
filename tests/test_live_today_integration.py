"""Live integration suite for today's hooks + MCP work (2026-05-21).

Uses project ``.deepseek/config.toml`` and a **fetch-only** MCP config so we
never spawn slow ``npx`` servers from the full ``mcp.json``.

Run explicitly (network + ``uvx`` required):

    .venv/bin/python -m pytest tests/test_live_today_integration.py -m live -v

Budget: entire module should finish in **≤60s**. Individual tests use
``asyncio.wait_for`` caps; if the suite exceeds 60s something is likely stuck.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import time
from pathlib import Path

import pytest

from deepseek_tui.client.deepseek import DeepSeekClient
from deepseek_tui.config.loader import ConfigLoader
from deepseek_tui.config.models import Config, HooksConfig, LifecycleHookEntry
from deepseek_tui.engine.dispatch import is_mcp_tool
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.engine.handle import AutoApprovalHandler, EngineHandle
from deepseek_tui.policy.approval import ExecPolicyEngine
from deepseek_tui.integrations.hooks import build_hook_dispatcher
from deepseek_tui.mcp.config import McpServerConfig, load_mcp_config
from deepseek_tui.mcp.execute import normalize_mcp_bridge_tool_name
from deepseek_tui.mcp.manager import McpManager
from deepseek_tui.protocol.messages import Message
from deepseek_tui.protocol.messages import MessageRequest
from deepseek_tui.protocol.responses import StreamTextDelta, ToolCall
from deepseek_tui.tools.registry import build_default_registry

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_SERVER = Path(__file__).resolve().parent / "fixtures" / "minimal_mcp_server.py"
PRE_TOOL_DOC_HOOK = Path(__file__).resolve().parent / "fixtures" / "pre_tool_check_doc.sh"

# Per-test asyncio caps (seconds)
_TIMEOUT_API = 45
_TIMEOUT_MCP = 35
_TIMEOUT_ENGINE = 40
_TIMEOUT_HOOK = 10


def _has_api_key(cfg: Config) -> bool:
    pc = cfg.effective_provider_config()
    return bool(cfg.api_key or pc.api_key)


def _fetch_server_from_project() -> tuple[Path, object]:
    project_mcp = PROJECT_ROOT / ".deepseek" / "mcp.json"
    if not project_mcp.exists():
        pytest.skip(f"project mcp.json missing: {project_mcp}")
    servers = load_mcp_config(project_mcp)
    fetch = next((s for s in servers if s.name == "fetch" and s.enabled), None)
    if fetch is None:
        pytest.skip("fetch MCP server not configured in project mcp.json")
    if shutil.which("uvx") is None:
        pytest.skip("uvx not on PATH (required for fetch MCP server)")
    return project_mcp, fetch


@pytest.fixture(scope="module")
def project_config() -> Config:
    cfg = ConfigLoader().load(workspace=PROJECT_ROOT)
    if not _has_api_key(cfg):
        pytest.skip("no API key in .deepseek/config.toml")
    return cfg


@pytest.fixture(scope="module")
def fetch_only_mcp_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    _, fetch = _fetch_server_from_project()
    path = tmp_path_factory.mktemp("live_mcp") / "mcp.json"
    doc = {
        "mcpServers": {
            "fetch": {
                "command": fetch.command,
                "args": list(fetch.args),
                "env": dict(fetch.env),
                "enabled": True,
            }
        }
    }
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return path


@pytest.fixture(scope="module", autouse=True)
def _live_suite_deadline() -> None:
    started = time.monotonic()
    yield
    elapsed = time.monotonic() - started
    if elapsed > 60.0:
        pytest.fail(
            f"live core suite exceeded 60s budget ({elapsed:.1f}s) — check for hung MCP/API"
        )


@pytest.mark.live
class TestLiveTodayIntegration:
    async def test_01_deepseek_api_stream(self, project_config: Config) -> None:
        client = DeepSeekClient.from_config(project_config)
        req = MessageRequest(
            model=project_config.model or project_config.default_text_model,
            messages=[Message.user("只回复两个字母：OK")],
            stream=True,
            max_tokens=64,
        )
        chunks: list[str] = []

        async def _consume() -> None:
            async for event in client.stream_chat_completion(req):
                if isinstance(event, StreamTextDelta):
                    chunks.append(event.text)

        try:
            await asyncio.wait_for(_consume(), timeout=_TIMEOUT_API)
        finally:
            await client.close()

        text = "".join(chunks).strip()
        assert text, "expected non-empty assistant text"
        assert "OK" in text.upper()

    async def test_02_real_fetch_mcp_discover_and_call(
        self, fetch_only_mcp_path: Path
    ) -> None:
        servers = load_mcp_config(fetch_only_mcp_path)
        mgr = McpManager(servers, config_path=fetch_only_mcp_path)

        async def _run() -> str:
            tools = await mgr.discover_tools()
            names = [t["function"]["name"] for t in tools]
            assert any(n.startswith("mcp_fetch_") for n in names)
            tool_name = next(n for n in names if n.startswith("mcp_fetch_"))
            assert is_mcp_tool(tool_name)
            result = await mgr.call_tool(
                tool_name, {"url": "https://example.com"}
            )
            assert result.get("isError") is False
            blocks = result.get("content", [])
            assert blocks and isinstance(blocks[0], dict)
            text = blocks[0].get("text", "")
            assert "example.com" in text.lower()
            return tool_name

        try:
            qualified = await asyncio.wait_for(_run(), timeout=_TIMEOUT_MCP)
            assert qualified == "mcp_fetch_fetch"
        finally:
            await mgr.stop_all()

    async def test_03_lifecycle_hook_fires_on_engine_tool(
        self, project_config: Config, fetch_only_mcp_path: Path, tmp_path: Path
    ) -> None:
        """tool_call_before runs before a real fetch MCP tool invocation."""
        marker = tmp_path / "lifecycle_hook.ran"
        cfg = project_config.model_copy(deep=True)
        cfg.mcp_config_path = fetch_only_mcp_path
        cfg.hooks = HooksConfig(
            enabled=True,
            hooks=[
                LifecycleHookEntry(
                    event="tool_call_before",
                    command=f"touch {marker}",
                    timeout_secs=5.0,
                )
            ],
        )

        client = DeepSeekClient.from_config(cfg)
        handle = EngineHandle(hooks=build_hook_dispatcher(cfg))

        async def _run() -> None:
            engine = await Engine.create(
                handle,
                client,
                config=cfg,
                working_directory=PROJECT_ROOT,
                approval_handler=AutoApprovalHandler(),
                exec_policy=ExecPolicyEngine(approval_policy="auto"),
            )
            try:
                tools = await engine._get_tools_with_mcp()
                tool_name = next(
                    t["function"]["name"]
                    for t in tools
                    if t["function"]["name"].startswith("mcp_fetch_")
                )
                tc = ToolCall(
                    id="live-tc-1",
                    name=tool_name,
                    arguments={"url": "https://example.com"},
                )
                result = await engine._execute_single_tool(
                    tc, tools, cfg.model or cfg.default_text_model
                )
                assert result is not None and result.success
                assert marker.is_file(), "tool_call_before lifecycle hook did not run"
            finally:
                await engine.shutdown()
                await client.close()

        await asyncio.wait_for(_run(), timeout=_TIMEOUT_ENGINE)

    async def test_04_app_server_mcp_startup_fetch(
        self, project_config: Config, fetch_only_mcp_path: Path, tmp_path: Path
    ) -> None:
        from deepseek_tui.server.runtime import AppRuntime
        from deepseek_tui.tools.runtime import create_tool_runtime

        cfg = project_config.model_copy(deep=True)
        cfg.mcp_config_path = fetch_only_mcp_path
        cfg.hooks.jsonl_path = tmp_path / "startup_hooks.jsonl"

        servers = load_mcp_config(fetch_only_mcp_path)
        mgr = McpManager(servers, config_path=fetch_only_mcp_path)

        async def _run() -> None:
            runtime = await create_tool_runtime(
                config=cfg,
                working_directory=PROJECT_ROOT,
                mcp_manager=mgr,
                start_mcp=False,
            )
            app = AppRuntime(
                config=cfg,
                tool_runtime=runtime,
                working_directory=PROJECT_ROOT,
            )
            try:
                out = await app.mcp_startup()
                assert out.get("ok") is True
                summary = out.get("summary", {})
                assert "fetch" in summary.get("ready", [])
                assert cfg.hooks.jsonl_path.exists()
                lines = cfg.hooks.jsonl_path.read_text(encoding="utf-8").strip()
                assert lines, "expected MCP startup hook JSONL frames"
            finally:
                await app.shutdown()

        await asyncio.wait_for(_run(), timeout=_TIMEOUT_MCP)

    async def test_05_bridge_tool_alias_and_fixture_engine_path(
        self, tmp_path: Path
    ) -> None:
        """Registry bridge alias (local) + real stdio fixture subprocess."""
        assert normalize_mcp_bridge_tool_name("mcp_read_resource") == "read_mcp_resource"

        fixture_cfg = [
            McpServerConfig(
                name="fixture",
                command=sys.executable,
                args=[str(FIXTURE_SERVER)],
                connect_timeout=10.0,
                read_timeout=15.0,
            )
        ]
        mgr = McpManager(fixture_cfg)

        async def _run() -> None:
            tools = await mgr.discover_tools()
            name = next(t["function"]["name"] for t in tools if t["function"]["name"] == "mcp_fixture_echo")
            tc = ToolCall(id="live-fixture", name=name, arguments={"message": "live"})
            cfg = Config()
            registry = build_default_registry(cfg)
            engine = Engine(
                handle=EngineHandle(),
                client=DeepSeekClient(api_key="dummy", base_url="https://example.invalid"),
                tool_registry=registry,
                exec_policy=ExecPolicyEngine(approval_policy="auto"),
                approval_handler=AutoApprovalHandler(),
            )
            engine.tool_context.metadata["mcp_manager"] = mgr
            engine._mcp_tools_cache = tools
            result = await engine._execute_single_tool(tc, tools, "deepseek-chat")
            assert result is not None
            assert result.content == "echo:live"
            await mgr.stop_all()
            await engine.client.close()

        await asyncio.wait_for(_run(), timeout=_TIMEOUT_HOOK)

    async def test_06_pre_tool_document_check_hook(
        self, project_config: Config, tmp_path: Path
    ) -> None:
        """tool_call_before reads a policy document and logs tool name (real shell hook)."""
        policy_doc = tmp_path / "TOOL_POLICY.md"
        policy_doc.write_text(
            "# Agent Tool Policy\nReview this document before any tool executes.\n",
            encoding="utf-8",
        )
        audit_log = tmp_path / "pre_tool_audit.log"
        hook_cmd = f"sh {PRE_TOOL_DOC_HOOK} {policy_doc} {audit_log}"

        cfg = project_config.model_copy(deep=True)
        cfg.hooks = HooksConfig(
            enabled=True,
            hooks=[
                LifecycleHookEntry(
                    event="tool_call_before",
                    name="review-tool-policy",
                    command=hook_cmd,
                    timeout_secs=5.0,
                )
            ],
        )

        fixture_cfg = [
            McpServerConfig(
                name="fixture",
                command=sys.executable,
                args=[str(FIXTURE_SERVER)],
                connect_timeout=10.0,
                read_timeout=15.0,
            )
        ]
        mgr = McpManager(fixture_cfg)
        client = DeepSeekClient.from_config(cfg)
        handle = EngineHandle(hooks=build_hook_dispatcher(cfg))

        async def _run() -> None:
            from deepseek_tui.integrations.hooks import build_lifecycle_hook_executor
            from deepseek_tui.tools.runtime import create_tool_runtime

            runtime_cfg = cfg.model_copy(deep=True)
            runtime_cfg.features.mcp = True
            runtime = await create_tool_runtime(
                config=runtime_cfg,
                working_directory=PROJECT_ROOT,
                mcp_manager=mgr,
                start_mcp=True,
            )
            engine = Engine(
                handle=handle,
                client=client,
                tool_runtime=runtime,
                hook_executor=build_lifecycle_hook_executor(cfg, PROJECT_ROOT),
                approval_handler=AutoApprovalHandler(),
                exec_policy=ExecPolicyEngine(approval_policy="auto"),
            )
            try:
                tools = await engine._get_tools_with_mcp()
                tool_name = next(
                    t["function"]["name"]
                    for t in tools
                    if t["function"]["name"] == "mcp_fixture_echo"
                )
                tc = ToolCall(
                    id="live-doc-hook",
                    name=tool_name,
                    arguments={"message": "after-policy-check"},
                )
                result = await engine._execute_single_tool(
                    tc, tools, cfg.model or cfg.default_text_model
                )
                assert result is not None and result.success
                assert audit_log.is_file(), "pre-tool audit log was not created"
                line = audit_log.read_text(encoding="utf-8").strip()
                assert "tool=mcp_fixture_echo" in line
                assert "policy=# Agent Tool Policy" in line
            finally:
                await runtime.shutdown()
                await client.close()

        await asyncio.wait_for(_run(), timeout=_TIMEOUT_ENGINE)
