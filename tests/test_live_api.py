"""Live integration tests using project ``.deepseek/config.toml`` and ``mcp.json``.

Run explicitly (skipped in default CI):

    uv run pytest tests/test_live_api.py -m live -v
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from deepseek_tui.client.deepseek import DeepSeekClient
from deepseek_tui.config.loader import ConfigLoader
from deepseek_tui.mcp.config import load_mcp_config
from deepseek_tui.mcp.manager import McpManager
from deepseek_tui.protocol.messages import Message
from deepseek_tui.protocol.messages import MessageRequest
from deepseek_tui.protocol.responses import StreamTextDelta

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _project_config() -> tuple[object, Path]:
    cfg = ConfigLoader().load(workspace=PROJECT_ROOT)
    mcp_path = cfg.mcp_config_path.expanduser()
    if not mcp_path.is_absolute():
        mcp_path = PROJECT_ROOT / mcp_path
    return cfg, mcp_path


def _has_api_key(cfg: object) -> bool:
    pc = cfg.effective_provider_config()  # type: ignore[union-attr]
    return bool(getattr(cfg, "api_key", None) or pc.api_key)


@pytest.fixture(scope="module")
def project_config():
    cfg, mcp_path = _project_config()
    if not _has_api_key(cfg):
        pytest.skip("no API key in .deepseek/config.toml or provider config")
    return cfg, mcp_path


@pytest.mark.live
class TestLiveDeepSeekApi:
    async def test_stream_chat_from_project_config(self, project_config) -> None:
        cfg, _ = project_config
        client = DeepSeekClient.from_config(cfg)
        req = MessageRequest(
            model=cfg.model or cfg.default_text_model,  # type: ignore[union-attr]
            messages=[Message.user("只回复两个字母：OK")],
            stream=True,
            max_tokens=512,
        )
        chunks: list[str] = []
        try:
            async for event in client.stream_chat_completion(req):
                if isinstance(event, StreamTextDelta):
                    chunks.append(event.text)
        finally:
            await client.close()
        text = "".join(chunks).strip()
        assert text, "expected non-empty assistant content"
        assert "OK" in text.upper()


@pytest.mark.live
class TestLiveProjectMcp:
    async def test_fetch_server_from_mcp_json(self, project_config) -> None:
        if shutil.which("uvx") is None:
            pytest.skip("uvx not on PATH")

        _, mcp_path = project_config
        if not mcp_path.exists():
            pytest.skip(f"mcp config missing: {mcp_path}")

        servers = [
            s for s in load_mcp_config(mcp_path) if s.name == "fetch" and s.enabled
        ]
        if not servers:
            pytest.skip("fetch MCP server not configured or disabled")

        mgr = McpManager(servers)
        tools = await mgr.discover_tools()
        names = [t["function"]["name"] for t in tools]
        assert any(n.startswith("mcp_fetch_") for n in names)

        tool_name = next(n for n in names if n.startswith("mcp_fetch_"))
        result = await mgr.call_tool(tool_name, {"url": "https://example.com"})
        assert result.get("isError") is False
        blocks = result.get("content", [])
        assert blocks and isinstance(blocks[0], dict)
