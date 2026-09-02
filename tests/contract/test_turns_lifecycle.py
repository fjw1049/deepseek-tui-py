from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_fork_thread(client: AsyncClient) -> None:
    create = await client.post("/v1/threads", json={})
    thread_id = create.json()["id"]
    fork = await client.post(f"/v1/threads/{thread_id}/fork")
    assert fork.status_code == 201
    forked = fork.json()
    assert forked["id"] != thread_id
    assert forked["id"].startswith("thr_")


@pytest.mark.asyncio
async def test_start_turn_empty_prompt_is_400(client: AsyncClient) -> None:
    """Caller errors (empty prompt) must surface as 400, not 409.

    Regression for the bug where every ``ValueError`` from
    ``RuntimeThreadManager.start_turn`` was lumped into ``409 turn_conflict``,
    making the GUI display "another turn in progress" for trivial bad input.
    """
    create = await client.post("/v1/threads", json={})
    thread_id = create.json()["id"]
    r = await client.post(
        f"/v1/threads/{thread_id}/turns",
        json={"prompt": "   "},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "invalid_request"


@pytest.mark.asyncio
async def test_start_turn_missing_api_key_is_400(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(
        "deepseek_tui.state.secrets.SecretsManager.resolve_api_key",
        lambda self, config, provider_name=None: None,
    )

    create = await client.post("/v1/threads", json={"provider": "kimi"})
    thread_id = create.json()["id"]
    r = await client.post(
        f"/v1/threads/{thread_id}/turns",
        json={"prompt": "hello", "provider": "kimi"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "missing_api_key"
