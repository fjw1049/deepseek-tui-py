from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProviderDefaults:
    base_url: str
    model: str


PROVIDER_DEFAULTS: dict[str, ProviderDefaults] = {
    "deepseek": ProviderDefaults(
        base_url="https://api.deepseek.com",
        model="deepseek-v4-pro",
    ),
    "openai": ProviderDefaults(
        base_url="https://api.openai.com/v1",
        model="gpt-4.1",
    ),
    "nvidia-nim": ProviderDefaults(
        base_url="https://integrate.api.nvidia.com/v1",
        model="deepseek-ai/deepseek-v4-pro",
    ),
    "fireworks": ProviderDefaults(
        base_url="https://api.fireworks.ai/inference/v1",
        model="accounts/fireworks/models/deepseek-v4-pro",
    ),
    "sglang": ProviderDefaults(
        base_url="http://localhost:30000/v1",
        model="deepseek-ai/DeepSeek-V4-Pro",
    ),
}

MODEL_ALIASES: dict[str, str] = {
    "deepseek-chat": "deepseek-v4-flash",
    "deepseek-reasoner": "deepseek-v4-flash",
}


def normalize_model(model: str) -> str:
    return MODEL_ALIASES.get(model, model)


def context_window_for_model(model: str) -> int:
    normalized = normalize_model(model).lower()
    if "deepseek" in normalized and ("v4" in normalized or normalized in MODEL_ALIASES):
        return 1_000_000
    if "deepseek" in normalized:
        return 128_000
    return 128_000
