"""GET /v1/skills — discovered skills for Workbench."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_skills_returns_registry_shape(client: AsyncClient) -> None:
    r = await client.get("/v1/skills")
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body.get("skills"), list)
    assert isinstance(body.get("warnings"), list)
