"""Central LLM client factory — single construction point for all providers.

Design principle: any OpenAI-compatible endpoint works with just
base_url + api_key + model name.  The factory never rejects an unknown
provider or model — it uses safe defaults and lets the API speak for
itself.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from deepseek_tui.client.anthropic import AnthropicCompatClient
from deepseek_tui.client.deepseek import DeepSeekClient

if TYPE_CHECKING:
    from deepseek_tui.config.models import Config


@dataclass(frozen=True, slots=True)
class EndpointTestResult:
    """Result of a connectivity test against an endpoint."""

    success: bool
    latency_ms: int = 0
    model: str = ""
    message: str = ""


def build_llm_client(config: Config) -> DeepSeekClient | AnthropicCompatClient:
    """Build an LLM client driven purely by configuration.

    Resolution chain (highest priority wins):
      1. CLI flags  (--api-key, --base-url, --model)
      2. ``[providers.<name>]`` table in config.toml
      3. ``PROVIDER_DEFAULTS`` for known providers
      4. Safe defaults (base_url from config, thinking=False)

    Unknown providers are fully supported — as long as the user supplies
    base_url + api_key + model in their ``[providers.X]`` section,
    everything works.
    """
    from deepseek_tui.state.secrets import SecretsManager

    mgr = SecretsManager()
    api_key = mgr.resolve_api_key(config) or ""

    pc = config.effective_provider_config()
    base_url = pc.base_url or "https://api.deepseek.com"
    model = pc.model or config.default_text_model

    if pc.protocol == "anthropic":
        return AnthropicCompatClient(
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=float(pc.timeout),
            extra_headers=pc.extra_headers,
        )

    # thinking_supported gates whether reasoning_effort / thinking fields
    # are sent in the request payload.  Default False — most endpoints
    # reject unknown fields with HTTP 400.  Only enable for endpoints
    # known to require these fields (DeepSeek official + DeepSeek models
    # served via third-party hosts).
    thinking = _infer_thinking_supported(base_url, model)

    return DeepSeekClient(
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=float(pc.timeout),
        thinking_supported=thinking,
        extra_headers=pc.extra_headers,
    )


def _infer_thinking_supported(base_url: str, model: str) -> bool:
    """Conservative heuristic — only True when we are confident the
    endpoint accepts DeepSeek's ``reasoning_effort`` / ``thinking``
    request fields.  False is always safe (the model still works,
    it just won't receive explicit reasoning control).
    """
    model_lower = model.lower()
    # DeepSeek v4 models require these fields for reasoning control,
    # regardless of which host serves them.
    if "v4-pro" in model_lower or "v4-flash" in model_lower:
        return True
    # DeepSeek's own endpoint — all reasoning models accept these fields.
    if "deepseek" in base_url.lower() and "deepseek" in model_lower:
        return True
    return False


async def test_endpoint(
    base_url: str,
    api_key: str,
    model: str,
    timeout: float = 15.0,
    protocol: str = "openai",
) -> EndpointTestResult:
    """Test connectivity to an OpenAI-compatible endpoint.

    Sends a minimal non-streaming request and checks for a valid response.
    Returns success/failure with latency and error details.
    """
    import httpx

    url = base_url.rstrip("/")
    if protocol == "anthropic":
        if url.endswith("/v1/messages"):
            pass
        elif url.endswith("/v1"):
            url = f"{url}/messages"
        else:
            url = f"{url}/v1/messages"
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 5,
            "stream": False,
        }
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
    else:
        import re

        if re.search(r"/v\d+$", url):
            url = f"{url}/chat/completions"
        else:
            url = f"{url}/v1/chat/completions"
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 5,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
        latency = int((time.monotonic() - start) * 1000)

        if resp.status_code == 200:
            body = resp.json()
            choices = (
                body.get("content", [])
                if protocol == "anthropic"
                else body.get("choices", [])
            )
            resp_model = body.get("model", model)
            if choices:
                return EndpointTestResult(
                    success=True,
                    latency_ms=latency,
                    model=resp_model,
                    message=f"连接成功 (模型: {resp_model}, 延迟: {latency}ms)",
                )
            return EndpointTestResult(
                success=True,
                latency_ms=latency,
                model=resp_model,
                message=f"连接成功但响应为空 (延迟: {latency}ms)",
            )
        else:
            body_text = resp.text[:200]
            return EndpointTestResult(
                success=False,
                latency_ms=latency,
                model=model,
                message=f"HTTP {resp.status_code}: {body_text}",
            )
    except httpx.TimeoutException:
        latency = int((time.monotonic() - start) * 1000)
        return EndpointTestResult(
            success=False,
            latency_ms=latency,
            model=model,
            message=f"连接超时 ({timeout}s)",
        )
    except httpx.ConnectError as e:
        return EndpointTestResult(
            success=False,
            model=model,
            message=f"连接失败: {e}",
        )
    except Exception as e:
        return EndpointTestResult(
            success=False,
            model=model,
            message=f"错误: {type(e).__name__}: {str(e)[:100]}",
        )


async def test_endpoint_from_config(
    config: Config, provider_name: str | None = None
) -> EndpointTestResult:
    """Test the endpoint for a given provider (or the current active one)."""
    name = provider_name or config.provider
    pc = config.providers.get(name)

    if pc is not None:
        from deepseek_tui.config.providers import PROVIDER_DEFAULTS
        defaults = PROVIDER_DEFAULTS.get(name)
        base_url = pc.base_url or (defaults.base_url if defaults else None)
        api_key = pc.api_key
        model = pc.model
        protocol = pc.protocol or "openai"
    else:
        from deepseek_tui.config.providers import PROVIDER_DEFAULTS
        defaults = PROVIDER_DEFAULTS.get(name)
        if defaults is None:
            return EndpointTestResult(
                success=False, model="", message=f"Provider '{name}' 未配置"
            )
        base_url = defaults.base_url
        api_key = None
        model = defaults.model
        protocol = defaults.protocol

    if not base_url:
        return EndpointTestResult(
            success=False, model=model or "", message="未配置 base_url"
        )
    if not api_key:
        # Try secrets manager
        from deepseek_tui.state.secrets import SecretsManager
        mgr = SecretsManager()
        api_key = mgr.resolve_api_key(config, provider_name=name)
    if not api_key:
        return EndpointTestResult(
            success=False, model=model or "", message=f"未找到 {name} 的 API Key"
        )
    if not model:
        from deepseek_tui.config.providers import PROVIDER_DEFAULTS
        defaults = PROVIDER_DEFAULTS.get(name)
        model = defaults.model if defaults else "unknown"

    return await test_endpoint(base_url, api_key, model, protocol=protocol)
