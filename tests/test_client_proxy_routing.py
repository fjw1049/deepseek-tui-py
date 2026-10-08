import httpx
import pytest

from deepseek_tui.client.anthropic import AnthropicCompatClient
from deepseek_tui.client.network import NetworkSettings


@pytest.mark.parametrize(
    ("url", "direct"),
    [
        ("http://devpilot.zhonganonline.com/devpilot/v1/messages", True),
        ("https://devpilot.zhonganonline.com/devpilot/v1/messages", True),
        ("https://api.anthropic.com/v1/messages", False),
        ("https://devpilot.zhonganonline.com.example.org/v1/messages", False),
    ],
)
async def test_devpilot_bypasses_system_proxy_only_for_exact_host(monkeypatch, url, direct):
    monkeypatch.setattr(
        "httpx._client.get_environment_proxies",
        lambda: {"http://": "http://127.0.0.1:7890", "https://": "http://127.0.0.1:7890"},
    )
    monkeypatch.setattr(
        "deepseek_tui.client.base.read_network_settings",
        lambda: NetworkSettings(bypassHosts=("devpilot.zhonganonline.com",)),
    )
    client = AnthropicCompatClient(api_key="test", base_url=url)
    try:
        http_client = client._get_http_client()
        transport = http_client._transport_for_url(httpx.URL(url))
        assert (transport is http_client._transport) is direct
    finally:
        await client.close()
