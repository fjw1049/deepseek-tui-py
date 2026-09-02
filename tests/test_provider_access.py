"""Unit tests for provider/model access fixes.

Covers:
- ``SecretsManager.resolve_api_key`` env → config.toml precedence
- ``DeepSeekClient`` chat-completions URL normalization (no double ``/v1``)
- ``Config.effective_provider_config`` PROVIDER_DEFAULTS gap-filling
- SSE chunk JSON-decode tolerance in the streaming client
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from deepseek_tui.client.deepseek import DeepSeekClient
from deepseek_tui.config.models import Config, ProviderConfig
from deepseek_tui.protocol.messages import MessageRequest
from deepseek_tui.protocol.responses import StreamTextDelta
from deepseek_tui.state.secrets import SecretsManager, write_active_api_key, write_api_key

# ── SecretsManager.resolve_api_key ────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clear_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "NVIDIA_API_KEY"):
        monkeypatch.delenv(var, raising=False)


def test_resolve_api_key_prefers_env_over_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    config = Config(providers={"deepseek": ProviderConfig(api_key="toml-key")})
    assert SecretsManager().resolve_api_key(config) == "env-key"


def test_resolve_api_key_falls_back_to_config_toml() -> None:
    config = Config(providers={"deepseek": ProviderConfig(api_key="toml-key")})
    assert SecretsManager().resolve_api_key(config) == "toml-key"


def test_resolve_api_key_top_level_fallback_and_none() -> None:
    mgr = SecretsManager()
    assert mgr.resolve_api_key(Config(api_key="top-key")) == "top-key"
    assert mgr.resolve_api_key(Config()) is None


def test_resolve_api_key_does_not_reuse_active_provider_key() -> None:
    config = Config(provider="deepseek", api_key="deepseek-key")
    assert SecretsManager().resolve_api_key(config, provider_name="openai") is None


def _read_toml(path: Path) -> dict[str, object]:
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - Python 3.10
        import tomli as tomllib

    with path.open("rb") as handle:
        return tomllib.load(handle)


def test_write_api_key_preserves_config_and_mirrors_active_provider(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        'provider = "openai"\n'
        'api_key = "old-top"\n\n'
        "[providers.openai]\n"
        'base_url = "https://api.openai.com/v1"\n'
        'api_key = "old-provider"\n\n'
        "[asr]\n"
        'api_key = "asr-key"\n',
        encoding="utf-8",
    )

    write_active_api_key('sk-"quoted"\\value', path=path)

    config = _read_toml(path)
    assert config["api_key"] == 'sk-"quoted"\\value'
    assert config["providers"]["openai"]["api_key"] == 'sk-"quoted"\\value'  # type: ignore[index]
    assert config["providers"]["openai"]["base_url"] == "https://api.openai.com/v1"  # type: ignore[index]
    assert config["asr"]["api_key"] == "asr-key"  # type: ignore[index]


def test_write_api_key_keeps_inactive_provider_out_of_top_level(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        'provider = "deepseek"\napi_key = "deepseek-key"\n',
        encoding="utf-8",
    )

    write_api_key("openai", "openai-key", path=path)

    config = _read_toml(path)
    assert config["api_key"] == "deepseek-key"
    assert config["providers"]["openai"]["api_key"] == "openai-key"  # type: ignore[index]


def test_write_api_key_clear_removes_active_provider_copies(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        'provider = "deepseek"\n'
        'api_key = "top-key"\n\n'
        "[providers.deepseek]\n"
        'api_key = "provider-key"\n'
        'base_url = "https://api.deepseek.com"\n',
        encoding="utf-8",
    )

    write_api_key("deepseek", None, path=path)

    config = _read_toml(path)
    assert "api_key" not in config
    assert "api_key" not in config["providers"]["deepseek"]  # type: ignore[index]
    assert config["providers"]["deepseek"]["base_url"] == "https://api.deepseek.com"  # type: ignore[index]


def test_write_api_key_quotes_custom_provider_name(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    write_api_key("acme.cloud", "custom-key", path=path)

    config = _read_toml(path)
    assert config["providers"]["acme.cloud"]["api_key"] == "custom-key"  # type: ignore[index]


def test_write_api_key_rejects_unsafe_provider_name(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    with pytest.raises(ValueError, match="provider name"):
        write_api_key("bad]name", "key", path=path)
    assert not path.exists()


# ── DeepSeekClient URL normalization ─────────────────────────────────────


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("https://api.deepseek.com", "https://api.deepseek.com/v1/chat/completions"),
        ("https://api.openai.com/v1", "https://api.openai.com/v1/chat/completions"),
        ("https://openrouter.ai/api/v1", "https://openrouter.ai/api/v1/chat/completions"),
        (
            "https://api.fireworks.ai/inference/v1",
            "https://api.fireworks.ai/inference/v1/chat/completions",
        ),
        ("http://localhost:30000/v1/", "http://localhost:30000/v1/chat/completions"),
    ],
)
def test_chat_completions_url_no_double_v1(base_url: str, expected: str) -> None:
    client = DeepSeekClient(api_key="k", base_url=base_url)
    assert client._chat_completions_url() == expected


# ── Config.effective_provider_config registry defaults ───────────────────


def test_effective_provider_config_fills_base_url_from_registry() -> None:
    config = Config(provider="openai")
    assert config.effective_provider_config().base_url == "https://api.openai.com/v1"


def test_effective_provider_config_explicit_table_wins() -> None:
    config = Config(
        provider="openai",
        providers={"openai": ProviderConfig(base_url="https://proxy.example/v1")},
    )
    assert config.effective_provider_config().base_url == "https://proxy.example/v1"


def test_effective_provider_config_top_level_override_wins() -> None:
    config = Config(provider="openai", base_url="https://override.example")
    assert config.effective_provider_config().base_url == "https://override.example"


def test_effective_provider_config_deepseek_default_unchanged() -> None:
    config = Config()
    pc = config.effective_provider_config()
    assert pc.base_url == "https://api.deepseek.com"
    assert pc.model == "deepseek-v4-pro"


# ── SSE chunk JSON tolerance ──────────────────────────────────────────────


class _FakeSSE:
    def __init__(self, data: str) -> None:
        self.data = data


class _FakeEventSource:
    """Minimal fake — no ``response`` attribute, so status checks are skipped."""

    def __init__(self, events: list[_FakeSSE]) -> None:
        self._events = events

    def aiter_sse(self):  # type: ignore[no-untyped-def]
        async def _gen():
            for event in self._events:
                yield event

        return _gen()


def _patch_sse(monkeypatch: pytest.MonkeyPatch, events: list[_FakeSSE]) -> None:
    @asynccontextmanager
    async def fake_aconnect_sse(client, method, url, **kwargs):  # type: ignore[no-untyped-def]
        yield _FakeEventSource(events)

    monkeypatch.setattr(
        "deepseek_tui.client.deepseek.aconnect_sse", fake_aconnect_sse
    )


async def test_stream_skips_malformed_sse_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    valid_chunk = '{"choices": [{"delta": {"content": "hello"}}]}'
    _patch_sse(
        monkeypatch,
        [
            _FakeSSE("{not json"),
            _FakeSSE(valid_chunk),
            _FakeSSE("[DONE]"),
        ],
    )
    client = DeepSeekClient(api_key="k", base_url="https://api.deepseek.com")
    request = MessageRequest(model="deepseek-v4-pro")
    events = [
        event async for event in client.stream_chat_completion(request)
    ]
    text_deltas = [e for e in events if isinstance(e, StreamTextDelta)]
    assert len(text_deltas) == 1
    assert text_deltas[0].text == "hello"
