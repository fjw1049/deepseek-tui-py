"""Recovery and completion use observations, never arbitrary REPL output."""

from dataclasses import replace

import pytest

from deepseek_tui.cua.session import CuaSession, _code_fingerprint
from deepseek_tui.cua.tools import CuaObserveTool, CuaTool, register_tools
from deepseek_tui.engine.ui_progress import UiProgress
from deepseek_tui.tools.registry import ToolContext, ToolError, ToolRegistry, ToolResult
from tests import test_cua as fixtures

fresh_runtime_cache = fixtures.fresh_runtime_cache
installation = fixtures.installation
session = fixtures.session
_calls = fixtures._calls


@pytest.mark.asyncio
async def test_recovery_allows_observation_and_keeps_blocking_actions(session, tmp_path):
    await session.connect()
    context = ToolContext(tmp_path, metadata={"cua_turn_id": "t", "cua_call_id": "c"})
    registry = ToolRegistry(context)
    register_tools(registry, session)
    session.invalidate_observation("The user brought the app to the front.")
    try:
        for _ in range(2):
            with pytest.raises(ToolError, match="cua_observe"):
                await registry.get("cua_js").execute({"code": "click"}, context)
        result = await registry.get("cua_observe").execute({"app": "dev.fixture"}, context)
        assert result.success and result.metadata["cua_observation"]["text"]
        assert not session.outside_change
        assert (await registry.get("cua_js").execute({"code": "ok"}, context)).success
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_observation_keeps_unknown_outcome_across_actions_and_restart(session, tmp_path):
    await session.connect()
    await session.record_outcome("old-turn", "uncertain-click", "unknown",
                                 code=_code_fingerprint({"code": "click"}))
    context = ToolContext(tmp_path, metadata={"cua_turn_id": "t", "cua_call_id": "c"})
    registry = ToolRegistry(context)
    register_tools(registry, session)
    try:
        result = await registry.get("cua_observe").execute({"app": "dev.fixture"}, context)
        assert result.success and "unknown outcome" in result.content
        # Seeing the app is not proof that the earlier operation succeeded.
        assert session.unresolved is not None
        other = await registry.get("cua_js").execute({"code": "read"}, context)
        assert other.success and "unknown outcome" in other.content
        restored = CuaSession(session.config, tmp_path, "other", owner_id="session-a")
        assert restored.unresolved is not None
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_code_after_an_unknown_outcome_gets_the_app_state_first(
        session, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from deepseek_tui.cua import session as cua_session

    monkeypatch.setattr(cua_session, "sys", SimpleNamespace(platform="darwin"))
    context = ToolContext(tmp_path, metadata={"cua_turn_id": "t", "cua_call_id": "c"})
    await session.connect()
    try:
        tool = CuaTool(session, session.descriptors[0])
        await tool.execute({"code": "surface:dev.fixture"}, context)
        await session.record_outcome("t", "lost", "unknown")
        held = await tool.execute({"code": "click"}, context)
        assert not held.success and "unknown outcome" in held.content
        assert "1 text Saved" in held.content
        assert "click" not in [c["args"]["code"] for c in _calls(tmp_path)]
        assert session.unresolved is not None
        assert (await tool.execute({"code": "click"}, context)).success
        # An app that cannot be observed still runs the code, told the old way.
        await tool.execute({"code": "surface:dev.unobservable"}, context)
        await session.record_outcome("t", "lost-again", "unknown")
        ran = await tool.execute({"code": "press"}, context)
        assert ran.success and "unknown outcome" in ran.content
    finally:
        await session.close()


def test_observe_schema_offers_only_this_platforms_native_target(session, monkeypatch):
    from types import SimpleNamespace

    from deepseek_tui.cua import tools

    observe = CuaObserveTool(session)
    for platform, native, other in (("darwin", "app", "window_id"), ("linux", "window_id", "app")):
        monkeypatch.setattr(tools, "sys", SimpleNamespace(platform=platform))
        schema = observe.input_schema()
        assert native in schema["properties"] and other not in schema["properties"]
        assert schema["oneOf"] == [{"required": [native]}, {"required": ["browser", "tab_id"]}]
        assert f"Supply {native}" in observe.description()


def observed(text):
    return ToolResult(
        True,
        "arbitrary model commentary",
        metadata={
            "cua_observation": {"target": {"app": "dev.fixture"}, "text": text, "complete": True}
        },
    )


def test_focus_ids_and_filtered_prints_do_not_disguise_stall():
    progress = UiProgress()
    for i in range(12):
        progress.record_result(
            "cua_observe",
            observed(
                f"Window: Form, App: Fixture.\n{i + 1} 按钮 Save\n"
                f"The focused UI element is {i + 1} 按钮 Save"
            ),
        )
        progress.record_result(
            "cua_js",
            ToolResult(
                True, f"different filtered output {i}", metadata={"cua_runtime_content": True}
            ),
        )
    assert progress.blocked_content("cua_js")
    assert progress.blocked_content("cua_observe") is None
    progress.record_result("cua_observe", observed("Window: Form\n22 文本 Saved successfully"))
    assert progress.blocked_content("cua_js") is None


def test_returning_to_same_two_states_does_not_count_as_unlimited_progress():
    progress = UiProgress()
    for i in range(14):
        progress.record_result("cua_observe", observed(f"Window: Form\n1 文本 Tab {i % 2}"))
    assert progress.blocked_content("cua_js")


def test_unmet_expected_result_does_not_reset_on_unrelated_changes():
    progress = UiProgress()
    for i in range(10):
        result = observed(f"Window: Form\n1 文本 Loading {i}")
        result.metadata["cua_observation"]["expectations"] = [{"text": "Saved", "matched": False}]
        progress.record_result("cua_observe", result)
    assert progress.blocked_content("cua_js")
    assert progress.blocked_content("cua_observe") is None
    result = observed("Window: Form\n1 文本 Saved")
    result.metadata["cua_observation"]["expectations"] = [{"text": "Saved", "matched": True}]
    progress.record_result("cua_observe", result)
    assert progress.blocked_content("cua_js") is None


@pytest.mark.asyncio
async def test_observation_cannot_accept_code_and_matches_expected_text(session, tmp_path):
    context = ToolContext(tmp_path, metadata={"cua_turn_id": "t", "cua_call_id": "c"})
    tool = CuaObserveTool(session)
    with pytest.raises(ToolError, match="no code"):
        await tool.execute({"app": "dev.fixture", "code": "click()"}, context)
    assert session.process is None
    try:
        result = await tool.execute({"app": "dev.fixture", "expect": ["Saved", "Missing"]}, context)
        assert result.metadata["cua_observation"]["expectations"] == [
            {"text": "Saved", "matched": True},
            {"text": "Missing", "matched": False},
        ]
        assert "Not verified: Missing" in result.content
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_change_during_observation_cannot_release_guard(session, tmp_path, monkeypatch):
    context = ToolContext(tmp_path, metadata={"cua_turn_id": "t", "cua_call_id": "c"})
    request = session._request

    async def interrupted(kind, **kwargs):
        result = await request(kind, **kwargs)
        if kind == "observe":
            session.invalidate_observation("user changed the app again")
        return result

    monkeypatch.setattr(session, "_request", interrupted)
    try:
        result = await CuaObserveTool(session).execute({"app": "dev.fixture"}, context)
        assert not result.success
        assert session.outside_change
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_observer_handles_existing_browser_tab(session, tmp_path):
    context = ToolContext(tmp_path, metadata={"cua_turn_id": "t", "cua_call_id": "c"})
    try:
        result = await CuaObserveTool(session).execute(
            {"browser": "chrome", "tab_id": 'tab"1', "expect": ["Saved"]}, context
        )
        assert result.success
        observation = result.metadata["cua_observation"]
        assert observation["target"] == {"browser": "chrome", "tab_id": 'tab"1'}
        assert observation["expectations"][0]["matched"]
        assert "documentation" not in observation["text"]
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_observing_another_app_switches_target_and_releases_guard(session, tmp_path):
    # The original app may have quit; a fresh view of another target must not deadlock.
    context = ToolContext(tmp_path, metadata={"cua_turn_id": "t", "cua_call_id": "c"})
    await session.connect()
    try:
        tool = CuaTool(session, session.descriptors[0])
        await tool.execute({"code": "surface:dev.original"}, context)
        session.invalidate_observation("The original app changed")
        # The host observes the last app itself instead of refusing the code.
        healed = await tool.execute({"code": "click"}, context)
        assert not healed.success and "observed dev.original for you" in healed.content
        assert healed.metadata["cua_observation"]["target"] == {"app": "dev.original"}
        assert "click" not in [c["args"]["code"] for c in _calls(tmp_path)]
        assert not session.outside_change
        session.invalidate_observation("The original app quit")
        await CuaObserveTool(session).execute({"app": "dev.other"}, context)
        assert not session.outside_change
        assert session.last_surface == {"kind": "app", "app_id": "dev.other"}
        assert (await tool.execute({"code": "ok"}, context)).success
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_app_that_cannot_be_observed_does_not_block_code_for_good(session, tmp_path):
    # Custom-drawn or windowless apps time out on observation; the guard must not deadlock.
    context = ToolContext(tmp_path, metadata={"cua_turn_id": "t", "cua_call_id": "c"})
    await session.connect()
    try:
        tool = CuaTool(session, session.descriptors[0])
        await tool.execute({"code": "surface:dev.unobservable"}, context)
        session.invalidate_observation("CUA code failed; inspect its actual effects.")
        held = await tool.execute({"code": "click"}, context)
        assert not held.success and "Your next cua_js runs" in held.content
        assert "click" not in [c["args"]["code"] for c in _calls(tmp_path)]
        assert (await tool.execute({"code": "click"}, context)).success
        assert "click" in [c["args"]["code"] for c in _calls(tmp_path)]
    finally:
        await session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [
    'await app["click"]({x:1,y:2}); console.log("done")',
    'await submit(); console.log("done")',
    "const s = await cua.getState(); nodeRepl.write(s)",
])
async def test_interrupted_arbitrary_js_preserves_receipt(session, monkeypatch, code):
    await session.connect()
    original_request = session._request

    async def request(kind, **values):
        if kind == "call" and not values["arguments"]["code"].startswith(
                ("if (!globalThis.__deepseekTrace)", 'nodeRepl.write("__DEEPSEEK_TRACE__"')):
            raise ToolError("connection lost")
        return await original_request(kind, **values)

    monkeypatch.setattr(session, "_request", request)
    with pytest.raises(ToolError):
        await session.call("js", {"code": code},
                           "turn", "read")
    assert session.unresolved["call_id"] == "read"
    await session.connect()
    with pytest.raises(ToolError):
        await session.call("js", {"code": "await app.click(3)"}, "turn", "act")
    assert session.unresolved["call_id"] == "read"
    await session.acknowledge("read")
    assert session.unresolved["call_id"] == "act"


def test_canvas_pixels_are_preserved_and_cannot_override_missing_expectation(tmp_path, monkeypatch):
    from tests.engine.test_ui_progress import screen

    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    progress = UiProgress()
    for i in range(10):
        result = observed("Window: Drawing\n1 canvas")
        result = replace(result, images=[screen(text=f"Frame {i}")])
        progress.record_result("cua_observe", result)
        assert progress.blocked_content("cua_js") is None
    for i in range(10):
        result = replace(result, images=[screen(text=f"Other {i}")])
        result.metadata["cua_observation"]["expectations"] = [{"text": "Saved", "matched": False}]
        progress.record_result("cua_observe", result)
    assert progress.blocked_content("cua_js")


def test_ax_completeness_never_reads_an_unknown_range_as_complete():
    from deepseek_tui.cua.tools import ax_complete

    assert ax_complete("Window: Notes\n1 button Save")
    assert ax_complete("2 HTML (showing 0-40 of 40 items)")
    assert not ax_complete("2 HTML (showing 0-100 of 350 items)")
    assert not ax_complete("2 HTML (Showing first 100 of 350)")


@pytest.mark.asyncio
async def test_observation_binds_once_per_repl(session, tmp_path):
    await session.connect()
    context = ToolContext(tmp_path, metadata={"cua_turn_id": "t", "cua_call_id": "c"})
    observe = CuaObserveTool(session)
    try:
        first = await observe.execute({"app": "dev.fixture"}, context)
        assert "Original observation documentation" in first.content
        # The binding already printed the tree; a repeat must not rebind and print it again.
        again = await observe.execute({"app": "dev.fixture"}, context)
        assert again.success and "documentation" not in again.content
        assert again.content.count("0 button Save") == 1
        await CuaTool(session, session.descriptors[1]).execute({}, context)  # js_reset
        rebound = await observe.execute({"app": "dev.fixture"}, context)
        assert "Original observation documentation" in rebound.content
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_observation_accepts_window_ids_for_linux_and_windows(session, tmp_path):
    await session.connect()
    context = ToolContext(tmp_path, metadata={"cua_turn_id": "t", "cua_call_id": "c"})
    observe = CuaObserveTool(session)
    try:
        result = await observe.execute({"window_id": 3}, context)
        assert result.success
        assert result.metadata["cua_observation"]["target"] == {"window_id": 3}
        for bad in ({"window_id": True}, {"window_id": -1}, {"window_id": "3"},
                    {"window_id": 3, "app": "dev.fixture"}):
            with pytest.raises(ToolError, match="window_id"):
                await observe.execute(bad, context)
    finally:
        await session.close()


def test_observation_resolves_localized_app_names_but_never_retries_a_denial():
    import json
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if not node:
        pytest.skip("Node required")
    bridge = Path(__file__).parents[1] / "src/deepseek_tui/cua/bridge.mjs"
    script = """
const fs = await import('node:fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const [install, openApp] = (0, eval)(
  src.slice(src.indexOf('const INPUTS'), src.indexOf('let observedTarget'))
  + '\\n;[TRACE_INSTALL, OPEN_APP]');
const calls = [];
let listed = 0;
globalThis.cua = {
  async getApp(name) {
    calls.push(name);
    if (name === 'com.apple.TextEdit' || name === 'com.soda.music') return 'bound';
    if (name === 'Denied') throw new Error('Computer Use was not approved to use Denied');
    throw new Error('Invalid app: ' + name);
  },
  async listApps() {
    listed += 1;
    return [{ id: 'com.apple.TextEdit', displayName: '文本编辑' },
            { id: 'com.soda.music', displayName: '汽水音乐' },
            { id: 'a.one', displayName: 'Twin' }, { id: 'a.two', displayName: 'twin' }];
  },
};
const open = (0, eval)(openApp);
const out = { localized: await open('文本编辑') };
for (const name of ['Denied', 'Twin', 'Nope']) {
  try { await open(name); } catch (error) { out[name] = error.message; }
}
out.calls = calls.splice(0);
// Model code binds through the traced entry point, which resolves the same way.
await new (Object.getPrototypeOf(async () => {}).constructor)(install)();
out.traced = await cua.getApp('汽水音乐');
listed = 0;
await cua.getApp('com.soda.music');
out.tracedCalls = calls;
out.listedForBundleId = listed;
console.log(JSON.stringify(out));
"""
    result = subprocess.run([node, "--input-type=module", "-e", script, str(bridge)],
                            capture_output=True, text=True, timeout=30, check=True)
    out = json.loads(result.stdout)
    # A display name binds by its id, never through getApp's own name lookup.
    assert out["localized"] == "bound" and out["calls"][0] == "com.apple.TextEdit"
    assert out["traced"] == "bound"
    assert out["tracedCalls"] == ["com.soda.music", "com.soda.music"]
    assert out["listedForBundleId"] == 0
    # A refusal is not an unknown name: asking again would re-prompt the user.
    assert "not approved" in out["Denied"] and out["calls"].count("Denied") == 1
    # Two apps share the name: never guess between them.
    assert out["Twin"] == "Invalid app: Twin" and out["Nope"] == "Invalid app: Nope"


def test_trace_records_inputs_and_state_reads_without_double_wrapping():
    import json
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if not node:
        pytest.skip("Node required")
    bridge = Path(__file__).parents[1] / "src/deepseek_tui/cua/bridge.mjs"
    script = """
const fs = await import('node:fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const install = (0, eval)(src.slice(src.indexOf('const INPUTS'), src.indexOf('const TRACE_MARK'))
  + '\\nTRACE_INSTALL');
const run = code => new (Object.getPrototypeOf(async () => {}).constructor)(code)();
globalThis.cua = { async getApp() { return {
  async click() {}, async getAXState() { return 'tree'; },
  async pressKey() { throw new Error('keyNotFound'); } }; } };
await run(install);
const app = await cua.getApp('x');
await app.click([1, 2]);
await app.getAXState();
const first = globalThis.__deepseekTrace.splice(0);
await run(install);  // the next call installs again: same wrappers, cleared trace
const again = await cua.getApp('x');
await again.click(3);
try { await again.pressKey('down'); } catch {}
const second = globalThis.__deepseekTrace.splice(0);
cua.createBrowserTab = async () => ({ playwright: { locator() { return 'locator'; } } });
await run(install);  // a fresh REPL would wrap the new entry point as well
delete globalThis.__deepseekTrace;
await run(install);
const tab = await cua.createBrowserTab('chrome', 'http://127.0.0.1/');
tab.playwright.locator('#name');
const third = globalThis.__deepseekTrace.splice(0);
delete globalThis.__deepseekTrace; delete globalThis.__deepseekTabs;
cua.createBrowserTab = async () => { throw new Error('Capability is not available: visibility'); };
await run(install);
try { await cua.createBrowserTab('chrome', 'http://127.0.0.1/', { visible: true }); } catch {}
console.log(JSON.stringify({ first, second, third, tabs: Boolean(globalThis.__deepseekTabs) }));
"""
    out = json.loads(subprocess.run([node, "--input-type=module", "-e", script, str(bridge)],
                                    capture_output=True, text=True, timeout=30,
                                    check=True).stdout)
    assert out["first"] == [
        {"action": "getApp", "observe": True, "ok": True},
        {"action": "click", "coordinate": True, "ok": True},
        {"action": "getAXState", "observe": True, "ok": True},
    ]
    assert out["second"] == [
        {"action": "getApp", "observe": True, "ok": True},
        {"action": "click", "coordinate": False, "ok": True},
        {"action": "pressKey", "coordinate": False, "ok": False},
    ]
    # Playwright method calls are recorded, including locator construction.
    assert out["third"] == [
        {"action": "createBrowserTab", "observe": True, "ok": True},
        {"action": "playwright", "method": "locator", "ok": True},
    ]
    # A tab that failed to open cannot take Playwright input.
    assert out["tabs"] is False


def test_preview_follows_reused_apps_and_cached_chained_locators():
    import json
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which('node')
    if not node:
        pytest.skip('Node required')
    bridge = Path(__file__).parents[1] / 'src/deepseek_tui/cua/bridge.mjs'
    script = r"""
const fs = await import('node:fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const install = (0, eval)(src.slice(src.indexOf('const INPUTS'), src.indexOf('const TRACE_MARK')) + '\nTRACE_INSTALL');
const run = code => new (Object.getPrototypeOf(async () => {}).constructor)(code)();
const make = id => ({
  async click() {}, async getScreenshot() { return id; },
  playwright: { locator() { return {
    first() { return this; }, async click() {},
    async next() { return { async fill() {} }; }
  }; } }
});
globalThis.cua = { async getApp(id) { return make(id); }, async getTab(id) { return make(id); } };
await run(install);
const a = await cua.getApp('A');
const b = await cua.getApp('B');
await run(install);
await a.click();
const app = await globalThis.__deepseekTarget.getScreenshot();
const t = await cua.getTab('T');
const cached = t.playwright.locator('button').first();
const nested = await cached.next();
await cua.getTab('Other');
await run(install);
await cached.click();
const tab = await globalThis.__deepseekTarget.getScreenshot();
await b.click();
await nested.fill('text');
const chained = await globalThis.__deepseekTarget.getScreenshot();
console.log(JSON.stringify({app, tab, chained}));
"""
    result = subprocess.run([node, '--input-type=module', '-e', script, str(bridge)],
                            capture_output=True, text=True, check=True, timeout=30)
    assert json.loads(result.stdout) == {'app': 'A', 'tab': 'T', 'chained': 'T'}


@pytest.mark.asyncio
async def test_failure_that_may_have_acted_arrives_with_current_state(session, tmp_path):
    context = ToolContext(tmp_path, metadata={"cua_turn_id": "t", "cua_call_id": "c"})
    await session.connect()
    try:
        tool = CuaTool(session, session.descriptors[0])
        await tool.execute({"code": "surface:dev.fixture"}, context)
        failed = await tool.execute(
            {"code": 'actions:[{"action":"pressKey","ok":true},{"action":"click","ok":false}]'},
            context)
        assert not failed.success
        assert "observed dev.fixture just now" in failed.content
        assert "1 text Saved" in failed.content
        assert failed.metadata["cua_stats"]["delivery"] == "uncertain"
        # The model already has the state, so its next code runs instead of being replaced.
        assert not session.outside_change
        assert (await tool.execute({"code": "next"}, context)).success
        assert "next" in [c["args"]["code"] for c in _calls(tmp_path)]
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_failure_on_an_app_that_cannot_be_observed_keeps_the_guard(session, tmp_path):
    context = ToolContext(tmp_path, metadata={"cua_turn_id": "t", "cua_call_id": "c"})
    await session.connect()
    try:
        tool = CuaTool(session, session.descriptors[0])
        await tool.execute({"code": "surface:dev.unobservable"}, context)
        failed = await tool.execute(
            {"code": 'actions:[{"action":"pressKey","ok":true},{"action":"click","ok":false}]'},
            context)
        assert "Check its state with cua_observe" in failed.content
        assert session.outside_change
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_wait_polls_text_until_expected_then_observes_once(session, tmp_path, monkeypatch):
    from deepseek_tui.cua import tools

    monkeypatch.setattr(tools, "WAIT_POLL_SECONDS", 0.01)
    context = ToolContext(tmp_path, metadata={"cua_turn_id": "t", "cua_call_id": "c"})
    await session.connect()
    try:
        observe = CuaObserveTool(session)
        result = await observe.execute(
            {"app": "dev.loading", "expect": ["Done"], "wait_ms": 5000}, context)
        assert result.success and "Waited" in result.content and "Observed: Done" in result.content
        assert result.metadata["cua_stats"]["expect_met"] is True
        reads = [c for c in _calls(tmp_path) if "getAXStateAndScreenshot" in c["args"]["code"]]
        assert len(reads) == 2
        assert sum(".getAXState(" in c["args"]["code"] for c in _calls(tmp_path)) == 2
        missed = await observe.execute(
            {"app": "dev.loading", "expect": ["Never"], "wait_ms": 50}, context)
        assert "Not verified: Never" in missed.content
        assert missed.metadata["cua_stats"]["expect_met"] is False
        # Without expect, wait_ms lets the app settle and then observes once.
        settled = await observe.execute({"app": "dev.fixture", "wait_ms": 50}, context)
        assert settled.success and settled.metadata["cua_stats"]["waited_ms"] >= 50
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_wait_returns_at_once_when_expected_text_is_already_there(session, tmp_path):
    context = ToolContext(tmp_path, metadata={"cua_turn_id": "t", "cua_call_id": "c"})
    await session.connect()
    try:
        result = await CuaObserveTool(session).execute(
            {"app": "dev.fixture", "expect": ["Saved"], "wait_ms": 5000}, context)
        assert result.success and "Waited" not in result.content
        reads = [c for c in _calls(tmp_path) if "getAXStateAndScreenshot" in c["args"]["code"]]
        assert len(reads) == 1
    finally:
        await session.close()


def _open_panel(rows: int) -> str:
    lines = ['Window: "Open", App: Fixture.', "0 standard window Open", "\t1 browser", "\t\t2 list"]
    for i in range(rows):
        first = 10 + i * 3
        lines += [f"\t\t\t{first} container", f"\t\t\t\t{first + 1} image",
                  f"\t\t\t\t{first + 2} text field Value: file-{i}.txt"]
    return "\n".join([*lines, "\t900 button Cancel", "\t901 button Open", "",
                      "Selected:", "\t40 container", ""])


def test_shortening_cuts_only_long_sibling_runs_and_keeps_the_selection():
    from deepseek_tui.cua.ax_text import shorten

    text, omitted = shorten(_open_panel(200), 3, 2)
    lines = text.split("\n")
    # Headers, the controls after the list, and the selected row all stay.
    assert lines[:4] == _open_panel(0).split("\n")[:4]
    assert "\t900 button Cancel" in lines and "\t901 button Open" in lines
    assert "\t\t\t40 container" in lines and "\t\t\t\t42 text field Value: file-10.txt" in lines
    # Rows 0-2 and the last two remain; the gaps around the selected row are named.
    assert "\t\t\t… 7 more items here not shown, indices 19-39" in lines
    assert "\t\t\t… 187 more items here not shown, indices 43-603" in lines
    assert omitted == (7 + 187) * 3 and len(text) < len(_open_panel(200)) // 10


def test_shortening_leaves_short_lists_and_diff_markers_intact():
    from deepseek_tui.cua.ax_text import shorten

    small = _open_panel(5)
    assert shorten(small, 3, 2) == (small, 0)
    diff = ("The following is a diff from the previous accessibility tree for Window: \"\"\n"
            "+0 list\n" + "\n".join(f"+\t{i} row r{i}" for i in range(1, 30)))
    text, omitted = shorten(diff, 2, 1)
    assert text.split("\n")[:4] == diff.split("\n")[:4]
    assert "\t… 26 more items here not shown, indices 3-28" in text and omitted == 26


@pytest.mark.asyncio
async def test_oversized_listing_is_shortened_instead_of_failing(session, tmp_path, monkeypatch):
    from deepseek_tui.tools import runtime

    monkeypatch.setattr(runtime, "spillover_root", lambda: tmp_path / "spill")
    context = ToolContext(tmp_path, metadata={"cua_turn_id": "t", "cua_call_id": "c"})
    await session.connect()
    try:
        acted = await CuaTool(session, session.descriptors[0]).execute({"code": "huge"}, context)
        assert acted.success and "more items here not shown" in acted.content
        assert "3701 button Open" in acted.content and "1510 container" in acted.content
        assert len(acted.content.encode()) < 64 * 1024
        saved = next((tmp_path / "spill").glob("*.txt")).read_text()
        assert "file-1199.txt" in saved and str(tmp_path / "spill") in acted.content
        assert acted.metadata["cua_stats"]["shortened_items"] > 3000
        observed = await CuaObserveTool(session).execute(
            {"app": "dev.huge", "expect": ["file-700.txt"]}, context)
        # The host checks the whole listing; the model is told it saw a shortened one.
        assert observed.success and "Observed: file-700.txt" in observed.content
        assert observed.metadata["cua_observation"]["complete"] is False
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_first_observation_keeps_documentation_but_not_a_second_state_copy(session, tmp_path):
    context = ToolContext(tmp_path, metadata={"cua_turn_id": "t", "cua_call_id": "c"})
    await session.connect()
    try:
        result = await CuaObserveTool(session).execute({"app": "dev.fixture"}, context)
        assert "Original observation documentation" in result.content
        assert "printed by binding" not in result.content and "1 text Saved" in result.content
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_waited_observation_preserves_unknown_outcome_warning(session, tmp_path):
    await session.connect()
    await session.record_outcome("old-turn", "lost-submit", "unknown")
    context = ToolContext(tmp_path, metadata={"cua_turn_id": "t", "cua_call_id": "c"})
    try:
        result = await CuaObserveTool(session).execute({
            "app": "dev.fixture", "expect": ["not present"], "wait_ms": 1,
        }, context)
        assert result.success and "unknown outcome" in result.content
        assert "lost-submit" in result.content and session.unresolved is not None
        again = await CuaObserveTool(session).execute({"app": "dev.fixture"}, context)
        assert "unknown outcome" in again.content
    finally:
        await session.close()
