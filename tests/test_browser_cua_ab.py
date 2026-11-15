"""The paid acceptance entry must also work with a scripted, free model."""
import json
from pathlib import Path
from types import SimpleNamespace

from deepseek_tui.config.models import Config
from deepseek_tui.protocol.responses import ToolCall
from scripts import browser_cua_ab
from tests import test_cua as fixtures
from tests.engine.test_browser_primary_loop import ScriptedClient

fresh_runtime_cache = fixtures.fresh_runtime_cache
installation = fixtures.installation


async def test_native_acceptance_supplies_real_host_ids(tmp_path, monkeypatch, installation):
    from deepseek_tui import client
    from deepseek_tui.config.loader import ConfigLoader

    scripted = ScriptedClient([
        ToolCall(id="read", name="cua_observe", arguments={"app": "dev.fixture"}),
        "Observed the fixture.",
    ])
    monkeypatch.setattr(client, "build_llm_client", lambda cfg: scripted)
    monkeypatch.setattr(ConfigLoader, "load", lambda self: Config(cua=installation))
    monkeypatch.setattr(browser_cua_ab, "prepare", lambda case, work: work / "unused")
    args = SimpleNamespace(provider="deepseek", model="deepseek-flash", variant="offline",
                           source_root=Path(__file__).resolve().parents[1] / "src")
    case = {"id": "calculator", "app": "dev.fixture", "prompt": "Read the fixture."}
    await browser_cua_ab.run(args, case, tmp_path)
    result = json.loads((tmp_path / "result.json").read_text())
    assert result["status"] == "executed"
    assert result["calls"][0]["success"] is True
    assert "1 text Saved" in result["calls"][0]["content"]
    assert len(scripted.requests) == 2
    events = fixtures._calls(tmp_path / "workspace")
    assert all(event["hostTurn"] == f"ab-{tmp_path.name}" for event in events)
    assert any(event["call"] == "call-1" for event in events)
