from __future__ import annotations

import json
from typing import Any

import pytest

from deepseek_tui.memory.l2 import SceneStore
from deepseek_tui.protocol.responses import StreamTextDelta, StreamToolCallComplete, ToolCall


class _SceneClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.requests = []

    async def stream_with_retry(self, request):  # noqa: ANN001
        self.requests.append(request)
        yield StreamTextDelta(text=json.dumps(self.payload, ensure_ascii=False))


class _ToolSceneClient:
    def __init__(self) -> None:
        self.requests = []

    async def stream_with_retry(self, request):  # noqa: ANN001
        self.requests.append(request)
        if len(self.requests) == 1:
            yield StreamToolCallComplete(
                tool_call=ToolCall(
                    id="call_1",
                    name="write",
                    arguments={
                        "path": "work.md",
                        "content": (
                            "-----META-START-----\n"
                            "summary: Work preferences\n"
                            "heat: 3\n"
                            "-----META-END-----\n\n"
                            "## 用户核心特征\n用户偏好 pytest。"
                        ),
                    },
                )
            )
            return
        yield StreamTextDelta(
            text=(
                "[PERSONA_UPDATE_REQUEST]\n"
                "reason: pytest 偏好稳定出现\n"
                "[/PERSONA_UPDATE_REQUEST]"
            )
        )


@pytest.mark.asyncio
async def test_l2_scene_extractor_prefers_tool_agent_path(tmp_path) -> None:
    scenes = SceneStore(tmp_path / "data")
    client = _ToolSceneClient()

    result = await scenes.extract_with_llm(
        client,  # type: ignore[arg-type]
        model="fake-model",
        scenes=[
            {
                "scene_name": "Work",
                "memories": [{"content": "User prefers pytest"}],
            }
        ],
        workspace="/ws",
        max_scenes=15,
    )

    assert result.scenes_processed == 1
    assert result.persona_update_reason == "pytest 偏好稳定出现"
    assert (tmp_path / "data" / "scene_blocks" / "work.md").is_file()
    assert (tmp_path / "data" / ".backup" / "scene_blocks").is_dir()
    assert {t["function"]["name"] for t in client.requests[0].tools} == {
        "edit",
        "read",
        "write",
    }
    assert "work" in scenes.navigation_markdown(workspace="/ws")


@pytest.mark.asyncio
async def test_l2_scene_extractor_applies_structured_ops(tmp_path) -> None:
    scenes = SceneStore(tmp_path / "data")
    old_path = tmp_path / "data" / "scene_blocks" / "old.md"
    old_path.write_text("# old\n", encoding="utf-8")
    payload = {
        "operations": [
            {
                "action": "write_scene",
                "filename": "work.md",
                "content": (
                    "-----META-START-----\n"
                    "summary: Work preferences\n"
                    "heat: 2\n"
                    "-----META-END-----\n\n"
                    "## 用户核心特征\n用户偏好 pytest。"
                ),
            },
            {"action": "delete_scene", "filename": "old.md"},
            {"action": "write_scene", "filename": "../escape.md", "content": "bad"},
            {"action": "request_persona_update", "reason": "偏好发生变化"},
        ]
    }
    result = await scenes.extract_with_llm(
        _SceneClient(payload),  # type: ignore[arg-type]
        model="fake-model",
        scenes=[
            {
                "scene_name": "Work",
                "memories": [{"content": "User prefers pytest"}],
            }
        ],
        workspace="/ws",
        max_scenes=15,
    )

    assert result.scenes_processed == 2
    assert result.persona_update_reason == "偏好发生变化"
    assert (tmp_path / "data" / "scene_blocks" / "work.md").is_file()
    assert not old_path.exists()
    assert not (tmp_path / "data" / "escape.md").exists()
    nav = scenes.navigation_markdown(workspace="/ws")
    assert "work" in nav


class _CoroutineClient:
    async def stream_with_retry(self, request):  # noqa: ANN001, ARG002
        return []


@pytest.mark.asyncio
async def test_l2_scene_extractor_falls_back_to_lite_scene_writer(tmp_path) -> None:
    scenes = SceneStore(tmp_path / "data")
    result = await scenes.extract_with_llm(
        _CoroutineClient(),  # type: ignore[arg-type]
        model="fake-model",
        scenes=[
            {
                "scene_name": "Fallback",
                "memories": [{"content": "User asked for concise answers"}],
            }
        ],
        workspace="/ws",
    )

    assert result.used_fallback
    assert result.scenes_processed == 1
    assert "Fallback" in scenes.navigation_markdown(workspace="/ws")
