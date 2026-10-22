"""UI loops are judged by what the surface returned, not by the calls that produced it."""

import io
from typing import Any
from unittest.mock import AsyncMock

import pytest
from PIL import Image, ImageDraw

from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.engine.ui_progress import (
    BLOCK_STREAK,
    REMIND_STREAK,
    UiProgress,
    observation_of,
)
from deepseek_tui.media import import_image
from deepseek_tui.protocol.messages import Message
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.tools.registry import ToolCapability, ToolContext, ToolResult, ToolSpec
from tests.engine.test_browser_primary_loop import ScriptedClient


@pytest.fixture(autouse=True)
def media_home(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))


def screen(*, text: str = "", quality: int = 90, size=(1600, 1000), cursor=None):
    """A window capture: a sidebar and, optionally, typed text in an input box."""
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, size[0] // 5, size[1]), fill=(235, 235, 235))
    draw.rectangle((size[0] // 3, size[1] - 160, size[0] - 40, size[1] - 40), outline="gray")
    if text:
        draw.text((size[0] // 3 + 20, size[1] - 130), text, fill="black", font_size=28)
    if cursor:
        draw.polygon([cursor, (cursor[0], cursor[1] + 30), (cursor[0] + 20, cursor[1] + 22)],
                     fill="black")
    data = io.BytesIO()
    image.save(data, "JPEG", quality=quality)
    return import_image(data.getvalue())


def shot(*images, text="1 image(s) attached."):
    return observation_of(ToolResult(True, text, images=list(images)))


def tree(text):
    return observation_of(ToolResult(True, text))


def test_recapture_of_an_unchanged_screen_is_not_new():
    progress = UiProgress()
    assert progress.record("cua_js", shot(screen(quality=90))) == ""
    # A re-encode differs byte for byte but shows the same screen.
    assert "nothing new" in progress.record("cua_js", shot(screen(quality=70)))


def test_typed_text_is_new():
    progress = UiProgress()
    progress.record("cua_js", shot(screen()))
    assert progress.record("cua_js", shot(screen(text="hello"))) == ""


def test_a_drawn_pointer_counts_as_change():
    # Erring toward "new" only withholds a note; the opposite would deny a real change.
    progress = UiProgress()
    progress.record("cua_js", shot(screen()))
    assert progress.record("cua_js", shot(screen(cursor=(800, 500)))) == ""


def test_window_unchanged_across_other_text_reaches_the_stuck_reminder():
    # The loop that motivated this: the window stays the same while menus are read.
    progress = UiProgress()
    progress.record("cua_js", shot(screen()))
    notes = []
    for i in range(REMIND_STREAK):
        assert progress.record("cua_js", tree(f"menu {i}")) == ""  # new text, not a loop
        notes.append(progress.record("cua_js", shot(screen(), text=f"menu {i} open")))
    assert "nothing new" in notes[0] and "Do not act" not in notes[0]
    assert f"last {REMIND_STREAK} screenshots" in notes[-1]
    assert "request_user_input" in notes[-1]


def test_repeated_text_only_results_count_separately():
    progress = UiProgress()
    progress.record("cua_js", tree("Window: Notes"))
    notes = [progress.record("cua_js", tree("Window: Notes")) for _ in range(REMIND_STREAK)]
    assert f"last {REMIND_STREAK} text-only results" in notes[-1]


def test_new_screenshot_clears_the_streak():
    progress = UiProgress()
    progress.record("cua_js", shot(screen()))
    for _ in range(REMIND_STREAK):
        progress.record("cua_js", shot(screen()))
    assert progress.record("cua_js", shot(screen(text="sent"))) == ""
    assert "Do not act" not in progress.record("cua_js", shot(screen(text="sent")))


def test_block_after_the_limit_until_a_person_acts():
    progress = UiProgress()
    progress.record("cua_js", shot(screen()))
    for _ in range(BLOCK_STREAK - 1):
        progress.record("cua_js", shot(screen()))
        assert progress.blocked_content("cua_js") is None
    progress.record("cua_js", shot(screen()))
    assert "Not executed" in progress.blocked_content("cua_js")
    assert "Not executed" in progress.blocked_content("cua_js_reset")  # same connection
    assert progress.blocked_content("browser_use") is None  # another surface
    progress.reset()
    assert progress.blocked_content("cua_js") is None


def test_browser_receipts_do_not_hide_an_unchanged_page():
    def page(action_id):
        browser = {"receipt": {"action_id": action_id},
                   "observation": {"observation_id": action_id, "text": "Cart is empty"}}
        return observation_of(ToolResult(True, str(browser), metadata={"browser": browser}))

    progress = UiProgress()
    progress.record("browser_use", page("a1"))
    assert "nothing new" in progress.record("browser_use", page("a2"))


def test_failures_and_empty_results_are_not_observations():
    assert observation_of(ToolResult(False, "Accessibility error")) is None
    assert observation_of(ToolResult(True, "")) is None


class RepeatingScreen(ToolSpec):
    def __init__(self):
        self.calls = 0

    def name(self) -> str:
        return "cua_js"

    def description(self) -> str:
        return "Desktop REPL"

    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"code": {"type": "string"}}}

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, Any], context: ToolContext) -> ToolResult:
        self.calls += 1
        return ToolResult(True, "1 image(s) attached.", images=[screen(quality=60 + self.calls)])


async def test_engine_appends_notes_and_stops_executing_a_dead_loop(tmp_path):
    attempts = BLOCK_STREAK + 2
    client = ScriptedClient([
        *(ToolCall(id=f"c{i}", name="cua_js", arguments={"code": f"click {i}"})
          for i in range(attempts)),
        ToolCall(id="finish", name="finish_task", arguments={
            "status": "blocked", "answer": "The window never responded.", "evidence": [],
            "remaining": ["The window shows nothing"],
        }),
    ])
    engine = await Engine.create(
        handle=EngineHandle(), client=client, working_directory=tmp_path,
        config=Config(features=FeatureConfig(
            tasks=False, subagents=False, mcp=False, automations=False)),
        start_mcp=False,
    )
    tool = RepeatingScreen()
    engine.tool_registry.register(tool)
    engine._handle_approval_flow = AsyncMock(return_value=False)
    try:
        result = await engine._run_conversation([Message.user("Open it")], "test", "sys", None)
        contents = {b.tool_use_id: str(b.content) for m in client.requests[-1].messages
                    for b in m.content if b.type == "tool_result"}
        assert "nothing new" in contents["c1"]
        assert "Do not act" in contents[f"c{REMIND_STREAK}"]
        assert tool.calls == BLOCK_STREAK + 1  # the first capture, then the repeats
        assert "Not executed" in contents[f"c{BLOCK_STREAK + 1}"]
        assert result.task_outcome["status"] == "blocked"
        # The next turn starts with a clean history: the same screen is new again.
        client.replies = iter([
            ToolCall(id="again", name="cua_js", arguments={"code": "look"}),
            ToolCall(id="done", name="finish_task", arguments={
                "status": "completed", "answer": "Seen.", "evidence": ["tool:again"],
                "remaining": [],
            }),
        ])
        await engine._run_conversation([Message.user("Look again")], "test", "sys", None)
        assert tool.calls == BLOCK_STREAK + 2
    finally:
        await engine.shutdown_session()
