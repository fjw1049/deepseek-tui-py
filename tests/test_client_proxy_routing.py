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


@pytest.mark.parametrize(
    ("url", "direct"),
    [
        ("http://10.1.2.3:8000/v1/messages", True),
        ("https://api.anthropic.com/v1/messages", False),
    ],
)
async def test_system_mode_follows_os_proxy_exceptions(monkeypatch, url, direct):
    monkeypatch.setattr(
        "httpx._client.get_environment_proxies",
        lambda: {"http://": "http://127.0.0.1:7890", "https://": "http://127.0.0.1:7890"},
    )
    # As if System Settings → Proxies → "Bypass proxy settings for" lists 10.*.
    monkeypatch.setattr(
        "deepseek_tui.client.network.urllib.request.proxy_bypass",
        lambda host: host.startswith("10."),
    )
    monkeypatch.setattr(
        "deepseek_tui.client.base.read_network_settings", lambda: NetworkSettings()
    )
    client = AnthropicCompatClient(api_key="test", base_url=url)
    try:
        http_client = client._get_http_client()
        transport = http_client._transport_for_url(httpx.URL(url))
        assert (transport is http_client._transport) is direct
    finally:
        await client.close()


@pytest.mark.parametrize(
    ("url", "direct"),
    [
        ("https://api.openai.com/v1/responses", False),
        ("http://127.0.0.1:11434/v1/chat/completions", True),
        ("https://internal.example/v1/messages", True),
    ],
)
async def test_system_mode_keeps_os_proxy_when_environment_only_sets_no_proxy(
    monkeypatch, url, direct
):
    # The browser service sets NO_PROXY to keep CDP on loopback; on its own that
    # makes urllib (and httpx) stop reading the OS proxy settings.
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy",
                 "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1,::1")
    monkeypatch.setenv("no_proxy", "localhost,127.0.0.1,::1")
    monkeypatch.setattr(
        "deepseek_tui.client.network._os_proxies",
        lambda: {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"},
        raising=False,
    )
    monkeypatch.setattr("deepseek_tui.client.network.urllib.request.proxy_bypass",
                        lambda host: False)
    monkeypatch.setattr(
        "deepseek_tui.client.network.urllib.request.proxy_bypass_macosx_sysconf",
        lambda host: host == "internal.example", raising=False,
    )
    monkeypatch.setattr(
        "deepseek_tui.client.base.read_network_settings", lambda: NetworkSettings()
    )
    client = AnthropicCompatClient(api_key="test", base_url=url)
    try:
        http_client = client._get_http_client()
        transport = http_client._transport_for_url(httpx.URL(url))
        assert (transport is http_client._transport) is direct
    finally:
        await client.close()


async def test_explicit_transport_handles_requests_even_with_system_proxy(monkeypatch):
    monkeypatch.setattr(
        NetworkSettings, "http_options",
        lambda self, url: {"mounts": {}, "proxy": "http://127.0.0.1:7890"},
    )
    url = "https://example.org/v1"
    mock = httpx.MockTransport(lambda request: httpx.Response(200))
    client = AnthropicCompatClient(api_key="test", base_url=url, transport=mock)
    try:
        assert client._get_http_client()._transport_for_url(httpx.URL(url)) is mock
    finally:
        await client.close()
