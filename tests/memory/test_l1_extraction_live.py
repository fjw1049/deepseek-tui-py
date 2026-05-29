"""Live L1 memory extraction — real DeepSeek API (batch B).

Run explicitly (not part of default CI):

    PYTHONPATH=src pytest tests/memory/test_l1_extraction_live.py -m live -v

Requires API key in project ``.deepseek/config.toml`` (or provider section).
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest

from deepseek_tui.client.deepseek import DeepSeekClient
from deepseek_tui.config.models import Config
from deepseek_tui.memory.native.provider import NativeMemoryProvider
from deepseek_tui.protocol.messages import Message
from deepseek_tui.protocol.requests import MessageRequest
from deepseek_tui.protocol.responses import StreamDone, StreamTextDelta

pytestmark = pytest.mark.live


async def _assert_live_api_reachable(client: DeepSeekClient, cfg: Config) -> None:
    """Fail fast with a clear message when the configured key is missing or invalid."""
    model = cfg.model or cfg.default_text_model or "deepseek-chat"
    req = MessageRequest(
        model=model,
        messages=[Message.user("Reply with exactly: OK")],
        max_tokens=16,
    )
    try:
        async for event in client.stream_with_retry(req):
            if isinstance(event, (StreamTextDelta, StreamDone)):
                return
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 401:
            pytest.fail(
                "DeepSeek API authentication failed (401). "
                "Set a valid DEEPSEEK_API_KEY or api_key in .deepseek/config.toml before -m live."
            )
        raise
    pytest.fail("live API preflight returned no text delta")


def _smart_config(base: Config, data_dir: Path) -> Config:
    return Config.merge_dict(
        base,
        {
            "memory": {
                "enabled": True,
                "mode": "hybrid",
                "smart": {
                    "enabled": True,
                    "data_dir": str(data_dir),
                    "l1_confidence_min": 0.6,
                    "l1_max_per_session": 20,
                },
            },
        },
    )


def _synthetic_conversation() -> list[dict]:
    now = int(time.time() * 1000)
    return [
        {
            "id": f"msg_{now}_u1",
            "role": "user",
            "content": (
                "My name is Morgan. I always want you to answer in concise "
                "English and prefer pytest for tests in this repository."
            ),
            "timestamp": now,
        },
        {
            "id": f"msg_{now}_a1",
            "role": "assistant",
            "content": "Understood — concise English and pytest for this repo.",
            "timestamp": now + 1,
        },
        {
            "id": f"msg_{now}_u2",
            "role": "user",
            "content": (
                "Remember: never suggest Jest for this Python project; "
                "we standardize on pytest only."
            ),
            "timestamp": now + 2,
        },
    ]


@pytest.mark.asyncio
async def test_l1_extraction_inserts_memories_from_conversation(
    live_project_config: Config,
    tmp_path: Path,
) -> None:
    """Real LLM extracts at least one L1 row with confidence >= 0.6."""
    import asyncio

    cfg = _smart_config(live_project_config, tmp_path / "memory_data")
    client = DeepSeekClient.from_config(cfg)
    await _assert_live_api_reachable(client, cfg)
    provider = NativeMemoryProvider(cfg, client)
    thread_id = "thr_live_l1"
    workspace = str(tmp_path.resolve())

    await provider.start()
    try:
        assert provider._l1 is not None
        result = await asyncio.wait_for(
            provider._l1.extract_and_store(
                thread_id,
                _synthetic_conversation(),
                workspace=workspace,
            ),
            timeout=120.0,
        )
        assert result.inserted >= 1, "expected L1 extractor to persist at least one memory"

        conn = provider._store._conn_required()
        rows = conn.execute(
            "SELECT confidence, content, type FROM memories WHERE thread_id = ?",
            (thread_id,),
        ).fetchall()
        assert rows, "memories table should contain rows for thread"
        assert all(float(r[0]) >= 0.6 for r in rows)

        recall = await provider.recall(
            thread_id,
            "pytest testing preference",
            workspace=workspace,
        )
        assert recall.l1_context.strip(), "recall should surface stored memories"
        assert "pytest" in recall.l1_context.lower()
    finally:
        await provider.stop()
        await client.close()


@pytest.mark.asyncio
async def test_capture_and_flush_triggers_l1_pipeline(
    live_project_config: Config,
    tmp_path: Path,
) -> None:
    """Capture + flush_session runs scheduler L1 job on real API."""
    import asyncio

    cfg = _smart_config(
        live_project_config,
        tmp_path / "memory_data_capture",
    )
    cfg = Config.merge_dict(
        cfg,
        {"memory": {"smart": {"l1_every_n": 1, "l1_idle_timeout_seconds": 2}}},
    )
    client = DeepSeekClient.from_config(cfg)
    await _assert_live_api_reachable(client, cfg)
    provider = NativeMemoryProvider(cfg, client)
    thread_id = "thr_live_capture"
    workspace = str(tmp_path.resolve())

    await provider.start()
    try:
        from deepseek_tui.memory.provider import CaptureInput

        await provider.capture(
            CaptureInput(
                thread_id=thread_id,
                user_text=(
                    "I work at Acme Corp on the payments team. "
                    "Our production database is PostgreSQL 16."
                ),
                workspace=workspace,
                messages=[
                    {
                        "role": "assistant",
                        "content": "I'll keep Acme and PostgreSQL 16 in mind.",
                    }
                ],
                had_tool_calls=False,
                success=True,
            )
        )
        await provider.flush_session(thread_id)
        if provider._scheduler is not None and provider._scheduler._tasks:
            await asyncio.gather(
                *list(provider._scheduler._tasks),
                return_exceptions=True,
            )

        count = provider._store.count_memories_for_thread(thread_id)
        assert count >= 1, "capture/flush should have completed an L1 extraction job"
    finally:
        await provider.stop()
        await client.close()
