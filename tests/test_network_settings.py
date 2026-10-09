import json

import httpx
import pytest
from pydantic import ValidationError

from deepseek_tui.client.anthropic import AnthropicCompatClient
from deepseek_tui.client.network import NetworkSettings, read_network_settings


@pytest.mark.parametrize(
    "host", ["https://example.com", "example.com:7890", "*.example.com", "", "a/b"]
)
def test_reject_invalid_bypass_hosts(host):
    with pytest.raises(ValidationError):
        NetworkSettings(bypassHosts=(host,))


async def test_changes_apply_to_next_request_without_closing_active_client(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path))
    monkeypatch.setattr(
        "httpx._client.get_environment_proxies",
        lambda: {"http://": "http://127.0.0.1:7890", "https://": "http://127.0.0.1:7890"},
    )
    path = tmp_path / "network.json"
    assert read_network_settings() == NetworkSettings()
    client = AnthropicCompatClient(api_key="test", base_url="http://internal.example")
    first = client._get_http_client()
    url = httpx.URL("http://internal.example")
    assert first._transport_for_url(url) is not first._transport
    path.write_text(json.dumps({"mode": "direct", "bypassHosts": []}))
    second = client._get_http_client()
    assert second._transport_for_url(url) is second._transport
    assert first is not second
    assert not first.is_closed
    assert client._get_http_client() is second
    path.write_text(json.dumps({"mode": "system", "bypassHosts": []}))
    assert client._get_http_client() is first
    await client.close()
    assert first.is_closed and second.is_closed

