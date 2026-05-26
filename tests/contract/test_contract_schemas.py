from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from httpx import AsyncClient

from deepseek_tui.app_server.runtime_api.sse import runtime_event_payload
from deepseek_tui.app_server.runtime_threads import RuntimeEventRecord

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"


def _load_schema(name: str) -> dict[str, object]:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def _matches_error_body(body: dict[str, object]) -> bool:
    if "detail" in body:
        detail = body["detail"]
        return isinstance(detail, dict) and isinstance(detail.get("message"), str)
    return isinstance(body.get("message"), str)


def test_sse_event_schema_locks_approval_and_user_input_payload() -> None:
    # Avoid pulling jsonschema (transitive ``attrs`` not always installed in
    # CI) — assert the locked fields directly from the JSON document.
    schema = _load_schema("sse-event.schema.json")
    rules = {
        block["if"]["properties"]["event"]["const"]: set(  # type: ignore[index]
            block["then"]["properties"]["payload"]["required"]  # type: ignore[index]
        )
        for block in schema["allOf"]  # type: ignore[index]
    }
    assert rules["approval.required"] == {"id", "approval_id", "tool_name"}
    assert rules["user_input.required"] == {"id", "request_id", "questions"}


def test_sse_event_schema_matches_runtime_event_payload() -> None:
    schema = _load_schema("sse-event.schema.json")
    required = set(schema["required"])  # type: ignore[arg-type]

    record = RuntimeEventRecord(
        seq=1,
        timestamp=datetime.now(timezone.utc),
        thread_id="thr_test",
        turn_id="turn_test",
        item_id="item_test",
        event="item.delta",
        payload={"delta": "hi", "kind": "agent_message"},
    )
    payload = runtime_event_payload(record)
    assert required <= set(payload.keys())
    assert payload["event"] == "item.delta"
    assert isinstance(payload["payload"], dict)


@pytest.mark.asyncio
async def test_errors_schema_matches_auth_middleware_body(
    authed_runtime_app: tuple[object, str],
) -> None:
    app, _token = authed_runtime_app
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        denied = await client.get("/v1/threads")
        assert denied.status_code == 401
        assert _matches_error_body(denied.json())


@pytest.mark.asyncio
async def test_errors_schema_matches_fastapi_wrapped_body(client: AsyncClient) -> None:
    create = await client.post("/v1/threads", json={})
    thread_id = create.json()["id"]
    r = await client.post(
        f"/v1/threads/{thread_id}/turns",
        json={"prompt": "   "},
    )
    assert r.status_code == 400
    assert _matches_error_body(r.json())
