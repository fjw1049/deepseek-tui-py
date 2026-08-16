"""Contract tests for /v1/automation/* ingress hardening.

- feishu inbound requires DEEPSEEK_FEISHU_WEBHOOK_SECRET; an unconfigured
  secret rejects (401) instead of silently skipping verification.
- test-send endpoints send only to the configured default target; the
  request body can no longer redirect messages to arbitrary recipients.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

import deepseek_tui.server.routes as routes_mod
from deepseek_tui.server.runtime import AppRuntime
from deepseek_tui.server.app import build_fastapi_app
from deepseek_tui.config.models import Config, FeatureConfig


@pytest.fixture
async def ingress_client(
    runtime_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncClient]:
    monkeypatch.setenv(
        "DEEPSEEK_AUTOMATIONS_DIR", str(runtime_data_dir / "automations-home")
    )
    monkeypatch.delenv("DEEPSEEK_FEISHU_WEBHOOK_SECRET", raising=False)
    config = Config(
        features=FeatureConfig(
            mcp=False,
            tasks=True,
            subagents=False,
            automations=True,
        ),
    )
    runtime = await AppRuntime.create(config=config, working_directory=runtime_data_dir)
    app = build_fastapi_app(runtime, http_mode=True, insecure_no_auth=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


_INBOUND_BODY = {"text": "hello", "sender_id": "ou_sender"}


@pytest.mark.asyncio
async def test_feishu_inbound_rejected_when_secret_unconfigured(
    ingress_client: AsyncClient,
) -> None:
    r = await ingress_client.post(
        "/v1/automation/feishu/inbound", json=_INBOUND_BODY
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_feishu_inbound_secret_gate(
    ingress_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_FEISHU_WEBHOOK_SECRET", "s3cret")

    missing = await ingress_client.post(
        "/v1/automation/feishu/inbound", json=_INBOUND_BODY
    )
    assert missing.status_code == 401

    wrong = await ingress_client.post(
        "/v1/automation/feishu/inbound",
        json=_INBOUND_BODY,
        headers={"Authorization": "Bearer nope"},
    )
    assert wrong.status_code == 401

    ok = await ingress_client.post(
        "/v1/automation/feishu/inbound",
        json=_INBOUND_BODY,
        headers={"Authorization": "Bearer s3cret"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["ok"] is True


@pytest.mark.asyncio
async def test_feishu_test_send_ignores_body_receive_id(
    ingress_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        routes_mod, "default_feishu_chat_id_from_config", lambda: "oc_default"
    )
    sent: dict[str, str] = {}

    async def _fake_send(
        *, receive_id: str, text: str, receive_id_type: str | None = None
    ) -> None:
        sent["receive_id"] = receive_id

    monkeypatch.setattr(routes_mod, "feishu_send_text", _fake_send)

    r = await ingress_client.post(
        "/v1/automation/feishu/test-send",
        json={"receive_id": "ou_attacker", "text": "x"},
    )
    assert r.status_code == 200, r.text
    assert sent["receive_id"] == "oc_default"


@pytest.mark.asyncio
async def test_feishu_test_send_requires_configured_default(
    ingress_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        routes_mod, "default_feishu_chat_id_from_config", lambda: None
    )
    r = await ingress_client.post(
        "/v1/automation/feishu/test-send",
        json={"receive_id": "ou_attacker", "text": "x"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_email_test_send_ignores_body_to_addr(
    ingress_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        routes_mod, "default_mail_to_from_config", lambda: "default@example.com"
    )
    sent: dict[str, str] = {}

    async def _fake_send(*, to_addr: str, subject: str, body: str) -> None:
        sent["to_addr"] = to_addr

    monkeypatch.setattr(routes_mod, "email_send_text", _fake_send)

    r = await ingress_client.post(
        "/v1/automation/email/test-send",
        json={"to_addr": "attacker@example.com"},
    )
    assert r.status_code == 200, r.text
    assert sent["to_addr"] == "default@example.com"
