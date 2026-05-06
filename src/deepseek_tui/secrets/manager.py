from __future__ import annotations

import os

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

from deepseek_tui.config.models import Config


class SecretsManager:
    SERVICE_NAME = "deepseek-tui"

    def resolve_api_key(self, config: Config, provider_name: str | None = None) -> str | None:
        provider = provider_name or config.provider
        env_key = self._env_var_name(provider)
        if env_value := os.getenv(env_key):
            return env_value

        provider_config = config.providers.get(provider)
        if provider_config and provider_config.api_key:
            return provider_config.api_key

        try:
            return keyring.get_password(self.SERVICE_NAME, provider)
        except KeyringError:
            return None

    def set_api_key(self, provider: str, value: str) -> None:
        keyring.set_password(self.SERVICE_NAME, provider, value)

    def delete_api_key(self, provider: str) -> bool:
        try:
            keyring.delete_password(self.SERVICE_NAME, provider)
        except PasswordDeleteError:
            return False
        return True

    def list_providers(self, config: Config) -> list[str]:
        providers = set(config.providers)
        providers.add(config.provider)
        return sorted(providers)

    @staticmethod
    def _env_var_name(provider: str) -> str:
        normalized = provider.upper().replace("-", "_")
        return f"{normalized}_API_KEY"
