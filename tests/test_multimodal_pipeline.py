"""Image ingress, protocol, persistence and explicitly routed helper contracts."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from PIL import Image

from deepseek_tui.client.anthropic import _build_anthropic_messages
from deepseek_tui.client.base import LLMClient, MeteredLLMClient
from deepseek_tui.client.chat_messages import build_chat_messages
from deepseek_tui.client.deepseek import DeepSeekClient
from deepseek_tui.client.media import budget_media_request, prepare_media_request
from deepseek_tui.config.models import Config, ProviderConfig, VisionConfig
from deepseek_tui.config.paths import user_media_dir
from deepseek_tui.config.routing import config_for_model
from deepseek_tui.engine.context import estimate_input_tokens_conservative, estimated_input_tokens
from deepseek_tui.engine.turn import prepare_turn_for_model
from deepseek_tui.engine.usage_ledger import TurnUsageLedger
from deepseek_tui.mcp.execute import mcp_response_to_tool_result
from deepseek_tui.media import image_data_url, import_image, message_images
from deepseek_tui.protocol.messages import (
    Message,
    MessageOrigin,
    MessageRequest,
    Role,
    ToolUseBlock,
)
from deepseek_tui.protocol.responses import StreamDone, StreamTextDelta, Usage
from deepseek_tui.tools.file import ReadFileTool
from deepseek_tui.tools.registry import ToolContext, ToolError


@pytest.fixture(autouse=True)
def media_home(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))


def image_bytes(format="PNG", size=(48, 32)):
    output = io.BytesIO()
    Image.new("RGB", size, "red").save(output, format=format)
    return output.getvalue()


def tool_messages(image):
    return [
        Message.user("Inspect the screen"),
        Message(
            role=Role.ASSISTANT,
            content=[
                ToolUseBlock(id="a", name="screen", input={}),
                ToolUseBlock(id="b", name="read_file", input={"path": "code.py"}),
            ],
        ),
        Message.tool_result("a", "Screenshot", images=[image]),
        Message.tool_result("b", "file text"),
    ]


@pytest.mark.parametrize("format", ["PNG", "JPEG", "WEBP", "BMP", "TIFF"])
def test_original_is_preserved_and_crop_is_derived(format):
    data = image_bytes(format)
    block = import_image(data)
    assert block.asset_id == hashlib.sha256(data).hexdigest()
    assert (user_media_dir() / block.asset_id).read_bytes() == data
    crop = block.model_copy(update={"crop": (5, 4, 12, 10)})
    wire = base64.b64decode(image_data_url(crop).split(",")[1])
    with Image.open(io.BytesIO(wire)) as decoded:
        assert decoded.size == (12, 10)
    assert block.crop is None
    assert import_image(data).asset_id == block.asset_id


def test_corruption_and_animation_fail_explicitly():
    with pytest.raises(ValueError):
        import_image(b"not an image")
    out = io.BytesIO()
    Image.new("RGB", (10, 10), "red").save(
        out,
        format="GIF",
        save_all=True,
        append_images=[Image.new("RGB", (10, 10), "blue")],
        duration=100,
    )
    with pytest.raises(ValueError, match="Animated"):
        import_image(out.getvalue())
    block = import_image(image_bytes())
    (user_media_dir() / block.asset_id).write_bytes(b"changed")
    with pytest.raises(ValueError, match="integrity"):
        image_data_url(block)


async def test_at_path_and_read_file_crop_reopen_original(tmp_path):
    path = tmp_path / "screen.png"
    path.write_bytes(image_bytes())
    prepared = prepare_turn_for_model("Explain @screen.png", workspace=tmp_path)
    assert len(prepared.images) == 1
    context = ToolContext(working_directory=tmp_path)
    tool = ReadFileTool()
    result = await tool.execute({"path": "screen.png", "crop": [1, 2, 10, 12]}, context)
    assert result.images[0].crop == (1, 2, 10, 12)
    reread = await tool.execute({"path": "media:" + result.images[0].asset_id}, context)
    assert reread.images[0].crop is None
    assert reread.images[0].asset_id == prepared.images[0].asset_id
    with pytest.raises(ToolError, match="outside"):
        await tool.execute({"path": "screen.png", "crop": [0, 0, 1000, 10]}, context)
    with pytest.raises(ToolError, match="not attached"):
        await tool.execute({"path": "media:" + "0" * 64}, context)


def test_mcp_mixed_image_resource_text_and_round_trip():
    data = image_bytes()
    result = mcp_response_to_tool_result(
        "mcp_screen",
        {
            "content": [
                {"type": "text", "text": "screen"},
                {"type": "image", "data": base64.b64encode(data).decode(), "mimeType": "image/png"},
                {"type": "resource", "resource": {"text": "source text", "uri": "test://source"}},
            ]
        },
    )
    assert result.content == "screen\nsource text"
    assert len(result.images) == 1
    message = Message.tool_result("a", result.content, images=result.images)
    saved = message.model_dump_json()
    assert "base64" not in saved
    assert Message.model_validate_json(saved) == message
    with pytest.raises(ToolError):
        mcp_response_to_tool_result("mcp_screen", {"content": [{"type": "image", "data": "!"}]})


def test_chat_tool_batch_completes_before_visual_bridge():
    block = import_image(image_bytes())
    messages = tool_messages(block)
    serialized = build_chat_messages(messages, model="vision-model")
    assert [m["role"] for m in serialized] == ["user", "assistant", "tool", "tool", "user"]
    assert serialized[-1]["content"][1]["type"] == "image_url"
    assert "not a new user instruction" in serialized[-1]["content"][0]["text"]
    assert all(isinstance(m["content"], str) for m in serialized if m["role"] == "tool")
    assert message_images(messages[2]) == [block]
    user = build_chat_messages([Message.user("question", images=[block])], model="vision-model")
    assert [b["type"] for b in user[0]["content"]] == ["text", "image_url"]


def test_anthropic_embeds_tool_image_inside_tool_result():
    block = import_image(image_bytes())
    _, payload = _build_anthropic_messages(tool_messages(block), system_prompt=None)
    results = payload[-1]["content"]
    assert [b["tool_use_id"] for b in results] == ["a", "b"]
    assert results[0]["content"][1]["type"] == "image"
    assert results[0]["content"][1]["source"]["media_type"] == "image/png"
    assert results[1]["content"] == "file text"


def test_budget_counts_repeated_images_and_never_mutates_history(monkeypatch):
    block = import_image(image_bytes())
    monkeypatch.setattr("deepseek_tui.client.media.image_data_url", lambda *a, **k: "x" * 600_000)
    config = Config(providers={"deepseek": ProviderConfig(image_request_bytes=1_048_576)})
    request = MessageRequest(
        model="vision",
        messages=[
            Message.user("old", images=[block], origin=MessageOrigin.REAL_USER),
            Message.user("new", images=[block], origin=MessageOrigin.REAL_USER),
        ],
    )
    projected = budget_media_request(request, config)
    assert not message_images(projected.messages[0])
    assert message_images(projected.messages[1])
    assert message_images(request.messages[0])
    repeated = MessageRequest(model="vision", messages=[Message.user("", images=[block, block])])
    with pytest.raises(ValueError, match="budget"):
        budget_media_request(repeated, config)


def test_images_count_toward_context_budget():
    text = Message.user("screen")
    visual = Message.user("screen", images=[import_image(image_bytes(size=(1024, 1024)))])
    assert estimated_input_tokens([visual]) > estimated_input_tokens([text]) + 500
    assert (
        estimate_input_tokens_conservative([visual])
        > estimate_input_tokens_conservative([text]) + 500
    )


async def test_native_request_sends_pixels_over_http():
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            text='data: {"choices":[{"delta":{"content":"red"}}]}\n\ndata: [DONE]\n\n',
        )

    client = DeepSeekClient(
        api_key="test", base_url="https://example.test/v1", transport=httpx.MockTransport(handler)
    )
    try:
        events = [
            event
            async for event in client.stream_chat_completion(
                MessageRequest(
                    model="vision",
                    messages=[Message.user("color?", images=[import_image(image_bytes())])],
                )
            )
        ]
    finally:
        await client.close()
    assert any(isinstance(event, StreamTextDelta) and event.text == "red" for event in events)
    assert requests[0]["messages"][0]["content"][1]["image_url"]["url"].startswith(
        "data:image/png;base64,"
    )


def test_provider_qualified_route_clears_overrides():
    config = Config(
        api_key="wrong",
        base_url="https://wrong.test",
        providers={
            "visual": ProviderConfig(
                api_key="right", base_url="https://right.test", protocol="anthropic"
            )
        },
    )
    resolved = config_for_model(config, "visual::chosen")
    assert resolved.provider == "visual"
    assert resolved.effective_provider_config().api_key == "right"
    assert resolved.effective_provider_config().base_url == "https://right.test"
    assert resolved.effective_provider_config().model == "chosen"
    assert config.api_key == "wrong"
    with pytest.raises(ValueError, match="Unknown"):
        config_for_model(config, "typo::model")


class VisionStub(LLMClient):
    def __init__(self, *, fail=False, block=False):
        super().__init__()
        self.requests = []
        self.fail = fail
        self.block = block
        self.close = AsyncMock()

    async def stream_chat_completion(self, request):
        self.requests.append(request)
        if self.block:
            await asyncio.sleep(10)
        if not self.fail:
            yield StreamTextDelta(text="Image 1 shows a red rectangle.")
        yield StreamDone(usage=Usage(input_tokens=100, output_tokens=10))


def helper_config():
    return Config(
        vision=VisionConfig(model="visual::image-model"),
        providers={
            "visual": ProviderConfig(
                api_key="visual-key", base_url="https://visual.test", image_input=True
            )
        },
    )


async def test_helper_projection_cache_provenance_and_metering(monkeypatch):
    stub = VisionStub()
    seen = []

    def build(config):
        seen.append(config)
        return stub

    monkeypatch.setattr("deepseek_tui.client.factory.build_llm_client", build)
    config = helper_config()
    request = MessageRequest(
        model="deepseek-chat",
        messages=[Message.user("Color?", images=[import_image(image_bytes())])],
    )
    ledger = TurnUsageLedger()
    cache = {}
    projected = await prepare_media_request(request, config, cache, ledger)
    assert seen[0].provider == "visual"
    assert stub.requests[0].model == "image-model"
    assert message_images(stub.requests[0].messages[0])
    assert all(not message_images(m) for m in projected.messages)
    assert projected.messages[-1].origin == MessageOrigin.SYSTEM_REMINDER
    assert "red rectangle" in projected.messages[-1].text_content()
    assert "not a new user instruction" in projected.messages[-1].text_content()
    assert message_images(request.messages[0])
    assert ledger.items[0].source == "vision"
    assert ledger.items[0].model == "image-model"
    await prepare_media_request(request, config, cache, ledger)
    assert len(stub.requests) == 1
    stub.close.assert_awaited_once()


async def test_helper_failures_timeout_and_no_recursive_fallback(monkeypatch):
    request = MessageRequest(
        model="deepseek-chat", messages=[Message.user("", images=[import_image(image_bytes())])]
    )
    with pytest.raises(ValueError, match="Configure vision.model"):
        await prepare_media_request(request, Config())
    cfg = helper_config()
    cfg.vision.model = "deepseek::deepseek-chat"
    with pytest.raises(ValueError, match="vision-capable"):
        await prepare_media_request(request, cfg)
    for fail, block in [(True, False), (False, True)]:
        stub = VisionStub(fail=fail, block=block)
        monkeypatch.setattr(
            "deepseek_tui.client.factory.build_llm_client", lambda cfg, current=stub: current
        )
        cfg = helper_config()
        cfg.vision.timeout_seconds = 0.01
        with pytest.raises(TimeoutError if block else ValueError):
            await prepare_media_request(request, cfg)
        stub.close.assert_awaited_once()


async def test_shared_client_attributes_usage_to_correct_turn(monkeypatch):
    from deepseek_tui.client.rate_limit import RateLimitedLLMClient

    class MainStub(LLMClient):
        async def stream_chat_completion(self, request):
            await self.prepare_media(request)
            yield StreamDone(usage=Usage(input_tokens=20, output_tokens=5))

    monkeypatch.setattr("deepseek_tui.client.factory.build_llm_client", lambda cfg: VisionStub())
    inner = MainStub()
    inner.media_config = helper_config()
    wrapped = RateLimitedLLMClient(inner, api_key="test", limit=100)
    ledgers = [TurnUsageLedger(), TurnUsageLedger()]
    clients = [MeteredLLMClient(wrapped, ledger) for ledger in ledgers]
    image = import_image(image_bytes())

    async def run(client, question):
        return [
            e
            async for e in client.stream_chat_completion(
                MessageRequest(
                    model="deepseek-chat", messages=[Message.user(question, images=[image])]
                )
            )
        ]

    await asyncio.gather(run(clients[0], "a"), run(clients[1], "b"))
    assert [sorted(i.source for i in ledger.items) for ledger in ledgers] == [
        ["unknown", "vision"],
        ["unknown", "vision"],
    ]


def test_thread_restore_retains_user_and_tool_images(tmp_path):
    from datetime import datetime, timezone

    from deepseek_tui.server.threads import (
        RuntimeTurnStatus,
        TurnItemKind,
        TurnItemLifecycleStatus,
        TurnItemRecord,
        TurnRecord,
    )
    from deepseek_tui.server.threads.items import reconstruct_messages_from_turn
    from deepseek_tui.server.threads.store import RuntimeThreadStore

    block = import_image(image_bytes())
    store = RuntimeThreadStore(tmp_path / "threads")
    turn = TurnRecord(
        id="turn",
        thread_id="thread",
        status=RuntimeTurnStatus.COMPLETED,
        input_summary="screen",
        created_at=datetime.now(timezone.utc),
        item_ids=["user", "tool"],
    )
    store.save_turn(turn)
    store.save_item(
        TurnItemRecord(
            id="user",
            turn_id="turn",
            kind=TurnItemKind.USER_MESSAGE,
            status=TurnItemLifecycleStatus.COMPLETED,
            summary="screen",
            metadata={
                "input_message": Message.user("screen", images=[block]).model_dump(mode="json")
            },
        )
    )
    store.save_item(
        TurnItemRecord(
            id="tool",
            turn_id="turn",
            kind=TurnItemKind.TOOL_CALL,
            status=TurnItemLifecycleStatus.COMPLETED,
            summary="screen result",
            metadata={
                "tool_call_id": "a",
                "tool_name": "read_file",
                "arguments": {"path": "screen.png"},
                "images": [block.model_dump(mode="json")],
            },
        )
    )
    restored = reconstruct_messages_from_turn(RuntimeThreadStore(tmp_path / "threads"), turn)
    assert message_images(restored[0]) == [block]
    assert message_images(restored[-1]) == [block]
    assert image_data_url(message_images(restored[-1])[0]).startswith("data:image/png")


def test_conversation_bundle_restores_original_images(tmp_path):
    import zipfile

    from deepseek_tui.server.data_bundle import export_bundle, import_bundle

    data = image_bytes()
    block = import_image(data)
    records = tmp_path / "threads"
    records.mkdir()
    (records / "record.json").write_text(Message.user("image", images=[block]).model_dump_json())
    orphan = import_image(image_bytes(size=(2, 2)))
    bundle = tmp_path / "export.zip"
    export_bundle(
        bundle,
        scope="conversations",
        threads_dir=tmp_path / "threads",
        sessions_dir=tmp_path / "sessions",
    )
    with zipfile.ZipFile(bundle) as zf:
        assert zf.read("media/" + block.asset_id) == data
        assert "media/" + orphan.asset_id not in zf.namelist()
    (user_media_dir() / block.asset_id).unlink()
    import_bundle(
        bundle,
        threads_dir=tmp_path / "threads2",
        sessions_dir=tmp_path / "sessions2",
        import_settings=False,
    )
    assert (user_media_dir() / block.asset_id).read_bytes() == data


def test_switch_route_updates_new_subagent_runtime_only(tmp_path):
    from dataclasses import dataclass

    from deepseek_tui.engine.orchestrator.core import Engine

    @dataclass
    class Runtime:
        client: object
        model: str
        config: Config

    original = Runtime(VisionStub(), "old", Config())
    manager = SimpleNamespace(default_model="old", loop_runtime=original)
    manager.attach_loop_runtime = lambda runtime: setattr(manager, "loop_runtime", runtime)
    engine = object.__new__(Engine)
    engine.turn_usage_ledger = TurnUsageLedger()
    engine.turn_loop = SimpleNamespace(client=original.client)
    engine.tool_context = ToolContext(working_directory=tmp_path, subagent_manager=manager)
    cfg = helper_config()
    Engine.set_model_route(engine, VisionStub(), cfg, "new")
    assert engine.client is engine.turn_loop.client
    assert manager.loop_runtime.client is engine.client
    assert manager.loop_runtime.model == "new"
    assert manager.default_model == "new"
    assert original.model == "old"
    assert original.client is not engine.client
    assert engine.tool_context.metadata["task_config"] is cfg


async def test_compaction_keeps_reread_references_across_multiple_compactions(monkeypatch):
    from deepseek_tui.engine.capacity import CompactionConfig, compact_messages_safe

    monkeypatch.setattr(
        "deepseek_tui.engine.capacity._create_summary", AsyncMock(return_value="Summary")
    )
    monkeypatch.setattr("deepseek_tui.engine.capacity.validate_compaction_summary", lambda _: None)
    image = import_image(image_bytes())
    messages = [Message.user("original", images=[image])]
    messages += [Message.user("history " + "x" * 300) for _ in range(20)]
    for _ in range(2):
        result = await compact_messages_safe(
            VisionStub(), messages, CompactionConfig(keep_recent_tokens=50)
        )
        assert result.success
        restored = Message.model_validate_json(result.messages[0].model_dump_json())
        assert restored.image_references == [image]
        assert "media:" + image.asset_id in restored.text_content()
        assert not message_images(restored)
        messages = [*result.messages, *[Message.user("later " + "x" * 300) for _ in range(20)]]


async def test_subagent_qualified_route_preserves_identity_and_closes_owned_client(monkeypatch):
    from dataclasses import dataclass

    from deepseek_tui.engine.dispatch import real_subagent_executor
    from deepseek_tui.tools.subagent import AgentRunOutput

    @dataclass
    class Runtime:
        config: Config
        client: object
        model: str

    client = VisionStub()
    monkeypatch.setattr("deepseek_tui.client.factory.build_llm_client", lambda _: client)
    captured = []

    async def run(agent, runtime, cancel):
        captured.append(runtime)
        return AgentRunOutput(text="done", structured=None)

    monkeypatch.setattr("deepseek_tui.tools.subagent.run_subagent_loop", run)
    original = Runtime(helper_config(), VisionStub(), "deepseek-chat")
    agent = SimpleNamespace(model="visual::image-model", loop_runtime=original)
    await real_subagent_executor(agent, asyncio.Event())
    assert captured[0].model == "image-model"
    assert captured[0].config.provider == "visual"
    assert agent.model == "visual::image-model"
    assert original.model == "deepseek-chat"
    client.close.assert_awaited_once()


async def test_official_vision_model_receives_pixels_directly_even_when_selected_as_helper():
    config = Config(vision=VisionConfig(model="deepseek::deepseek-v4-flash-vision-exp"))
    request = MessageRequest(
        model="deepseek-v4-flash-vision-exp",
        messages=[Message.user("color?", images=[import_image(image_bytes())])],
    )
    assert await prepare_media_request(request, config) is request


async def test_deepseek_text_model_can_use_official_vision_helper(monkeypatch):
    stub = VisionStub()
    monkeypatch.setattr("deepseek_tui.client.factory.build_llm_client", lambda cfg: stub)
    config = Config(vision=VisionConfig(model="deepseek::deepseek-v4-flash-vision-exp"))
    request = MessageRequest(
        model="deepseek-v4-flash",
        messages=[Message.user("color?", images=[import_image(image_bytes())])],
    )
    projected = await prepare_media_request(request, config)
    assert stub.requests[0].model == "deepseek-v4-flash-vision-exp"
    assert message_images(stub.requests[0].messages[0])
    assert all(not message_images(message) for message in projected.messages)
