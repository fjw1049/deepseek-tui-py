"""Verify session isolation with installed LCU; no app access or model calls."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from deepseek_tui.config.models import Config
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.tools.registry import ToolContext, ToolRegistry

ROOT = Path(__file__).resolve().parent


async def main():
    shared = ToolRegistry()
    runtime = SimpleNamespace(registry=shared)
    engines = []
    try:
        for _ in range(2):
            engine = Engine(handle=EngineHandle(), client=None, tool_context=ToolContext(ROOT))
            engine._app_config = Config(cua={"enabled": True}, vision={"model": "deepseek::deepseek-v4-flash-vision-exp"})
            engine.tool_runtime = runtime
            engine.tool_registry = shared
            engines.append(engine)
        first, second = engines
        await first._prepare_cua()
        tool = first.tool_registry.get("cua_js")
        context = ToolContext(ROOT, metadata={"cua_turn_id": "isolation-test", "cua_call_id": "before"})
        result = await tool.execute({"code": "await cua.rewriteDocumentation();", "title": "Isolation probe"}, context)
        assert result.success
        assert first._cua_session.lease.fd is not None
        await second._prepare_cua()
        assert first.tool_registry.get("cua_js") is tool
        assert not shared.contains("cua_js")
        context.metadata["cua_call_id"] = "after"
        result = await first.tool_registry.get("cua_js").execute({"code": "await cua.rewriteDocumentation();", "title": "Isolation verification"}, context)
        assert result.success
        report = {"real_lcu": True, "first_session_survives_second_engine_preparation": True, "shared_registry_unmodified": True}
    finally:
        for engine in engines:
            await engine._close_cua()
    report["leases_released"] = all(e._cua_session.lease.fd is None for e in engines)
    assert report["leases_released"]
    (ROOT / "shared-registry-result.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


asyncio.run(main())
