"""Generic live MCP probe against project ``.deepseek/mcp.json``.

Sequentially connects to **each enabled server**, lists tools, and optionally
runs a safe probe call for known server types (``fetch`` only today).

Run:

    .venv/bin/python -m pytest tests/test_live_mcp_generic.py -m live_mcp -v

Budget: **≤90s** for the full scan (25s cap per server). Servers that exceed
the cap are recorded as ``timeout`` — the test still passes if **at least one**
server connects (typically ``fetch``).

Expected ``mcp.json`` shapes (also ``servers`` instead of ``mcpServers``):

```json
{
  "timeouts": { "connect_timeout": 15, "read_timeout": 30 },
  "mcpServers": {
    "my-stdio-server": {
      "command": "uvx",
      "args": ["some-mcp-package"],
      "env": { "API_KEY": "..." },
      "enabled": true,
      "required": false
    },
    "my-http-server": {
      "url": "http://127.0.0.1:3000/mcp",
      "enabled": true
    }
  }
}
```

Stdio servers need ``command`` (+ optional ``args`` / ``env``).
HTTP/SSE servers need ``url`` instead of ``command``.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from deepseek_tui.mcp.config import McpServerConfig, load_mcp_config
from deepseek_tui.mcp.manager import McpManager

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_MCP = PROJECT_ROOT / ".deepseek" / "mcp.json"

_PER_SERVER_TIMEOUT = 25.0
_SUITE_BUDGET_SEC = 90.0


@dataclass
class ServerProbeResult:
    name: str
    status: str  # ok | timeout | error | skipped
    transport: str
    tool_count: int = 0
    tool_names: list[str] | None = None
    probe_call: str | None = None
    error: str | None = None
    elapsed_sec: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "transport": self.transport,
            "tool_count": self.tool_count,
            "tool_names": self.tool_names or [],
            "probe_call": self.probe_call,
            "error": self.error,
            "elapsed_sec": round(self.elapsed_sec, 2),
        }


def _project_mcp_path() -> Path:
    if not PROJECT_MCP.exists():
        pytest.skip(f"project mcp.json missing: {PROJECT_MCP}")
    return PROJECT_MCP


def _enabled_servers(path: Path) -> list[McpServerConfig]:
    return [s for s in load_mcp_config(path) if s.enabled]


def _transport(cfg: McpServerConfig) -> str:
    return "http/sse" if cfg.url else "stdio"


async def _safe_probe_call(
    mgr: McpManager, cfg: McpServerConfig, tool_names: list[str]
) -> str | None:
    """Optional read-only probe — only for known-safe server profiles."""
    if cfg.name == "fetch":
        qualified = next((n for n in tool_names if n.startswith("mcp_fetch_")), None)
        if qualified is None:
            return None
        result = await mgr.call_tool(qualified, {"url": "https://example.com"})
        if result.get("isError"):
            raise RuntimeError(f"fetch probe failed: {result}")
        return qualified
    return None


async def _probe_one_server(cfg: McpServerConfig, timeout: float) -> ServerProbeResult:
    started = time.monotonic()
    mgr = McpManager([cfg])
    try:

        async def _inner() -> ServerProbeResult:
            tools = await mgr.discover_tools()
            names = [t["function"]["name"] for t in tools]
            probe = await _safe_probe_call(mgr, cfg, names)
            return ServerProbeResult(
                name=cfg.name,
                status="ok",
                transport=_transport(cfg),
                tool_count=len(names),
                tool_names=names[:12],
                probe_call=probe,
                elapsed_sec=time.monotonic() - started,
            )

        return await asyncio.wait_for(_inner(), timeout=timeout)
    except asyncio.TimeoutError:
        return ServerProbeResult(
            name=cfg.name,
            status="timeout",
            transport=_transport(cfg),
            error=f"exceeded {timeout}s",
            elapsed_sec=time.monotonic() - started,
        )
    except Exception as exc:  # noqa: BLE001
        return ServerProbeResult(
            name=cfg.name,
            status="error",
            transport=_transport(cfg),
            error=str(exc),
            elapsed_sec=time.monotonic() - started,
        )
    finally:
        await mgr.stop_all()


@pytest.fixture(scope="module", autouse=True)
def _generic_mcp_deadline() -> None:
    started = time.monotonic()
    yield
    elapsed = time.monotonic() - started
    if elapsed > _SUITE_BUDGET_SEC:
        pytest.fail(
            f"generic MCP suite exceeded {_SUITE_BUDGET_SEC}s "
            f"({elapsed:.1f}s) — consider disabling slow servers in mcp.json"
        )


@pytest.mark.live_mcp
class TestLiveMcpGeneric:
    async def test_all_enabled_servers_from_project_mcp_json(self) -> None:
        path = _project_mcp_path()
        servers = _enabled_servers(path)
        if not servers:
            pytest.skip("no enabled MCP servers in project mcp.json")

        results: list[ServerProbeResult] = []
        suite_started = time.monotonic()
        for cfg in servers:
            elapsed_suite = time.monotonic() - suite_started
            if elapsed_suite > _SUITE_BUDGET_SEC - _PER_SERVER_TIMEOUT:
                results.append(
                    ServerProbeResult(
                        name=cfg.name,
                        status="skipped",
                        transport=_transport(cfg),
                        error="suite time budget exhausted",
                    )
                )
                continue
            results.append(await _probe_one_server(cfg, _PER_SERVER_TIMEOUT))

        report = {
            "config": str(path),
            "servers": [r.to_dict() for r in results],
        }
        print("\n--- MCP generic probe report ---")
        print(json.dumps(report, indent=2, ensure_ascii=False))

        ok = [r for r in results if r.status == "ok"]
        assert ok, (
            "no MCP server connected — check mcp.json commands, env keys, and PATH "
            f"(results: {[r.to_dict() for r in results]})"
        )

        # At least fetch (or any server) should expose tools when ok
        assert any(r.tool_count > 0 for r in ok), "connected servers returned zero tools"
