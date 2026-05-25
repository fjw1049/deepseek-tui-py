from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_interrupt_unknown_turn(client: AsyncClient) -> None:
    create = await client.post("/v1/threads", json={})
    thread_id = create.json()["id"]
    r = await client.post(f"/v1/threads/{thread_id}/turns/not-a-turn/interrupt")
    assert r.status_code in {404, 409, 422}


@pytest.mark.asyncio
async def test_steer_unknown_turn(client: AsyncClient) -> None:
    create = await client.post("/v1/threads", json={})
    thread_id = create.json()["id"]
    r = await client.post(
        f"/v1/threads/{thread_id}/turns/not-a-turn/steer",
        json={"prompt": "Please prioritize this message."},
    )
    assert r.status_code in {404, 409, 422}
