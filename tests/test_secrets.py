from __future__ import annotations

from deepseek_tui.config.models import Config, ProviderConfig
from deepseek_tui.secrets.manager import SecretsManager


def test_resolve_api_key_prefers_env(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-secret")
    config = Config(providers={"deepseek": ProviderConfig(api_key="config-secret")})

    assert SecretsManager().resolve_api_key(config) == "env-secret"


def test_resolve_api_key_falls_back_to_config(monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    config = Config(providers={"deepseek": ProviderConfig(api_key="config-secret")})

    assert SecretsManager().resolve_api_key(config) == "config-secret"


def test_list_providers_includes_active_and_configured() -> None:
    config = Config(
        provider="deepseek",
        providers={
            "deepseek": ProviderConfig(),
            "openai": ProviderConfig(),
        },
    )

    assert SecretsManager().list_providers(config) == ["deepseek", "openai"]


def test_delete_api_key_returns_false_when_missing(monkeypatch) -> None:
    manager = SecretsManager()

    def fake_delete_password(service_name: str, provider: str) -> None:
        raise manager_delete_error()

    def manager_delete_error() -> Exception:
        from keyring.errors import PasswordDeleteError

        return PasswordDeleteError("missing")

    monkeypatch.setattr("keyring.delete_password", fake_delete_password)

    assert manager.delete_api_key("deepseek") is False


def test_delete_api_key_returns_true_when_removed(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_delete_password(service_name: str, provider: str) -> None:
        calls.append((service_name, provider))

    monkeypatch.setattr("keyring.delete_password", fake_delete_password)

    manager = SecretsManager()
    assert manager.delete_api_key("deepseek") is True
    assert calls == [(manager.SERVICE_NAME, "deepseek")]


def test_resolve_api_key_for_multiple_providers(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config = Config(
        provider="openai",
        providers={
            "deepseek": ProviderConfig(api_key="deepseek-secret"),
            "openai": ProviderConfig(api_key="openai-secret"),
        },
    )

    assert SecretsManager().resolve_api_key(config, provider_name="openai") == "openai-secret"
    assert SecretsManager().resolve_api_key(config, provider_name="deepseek") == "deepseek-secret"
