"""Image capability evidence for a specific endpoint and exact model ID."""

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from deepseek_tui.config.models import Config


@dataclass(frozen=True)
class ImageCapability:
    supported: bool | None
    source: Literal[
        "model_config", "provider_config", "official_docs", "helper_selection", "unknown"
    ]


# Verified 2026-09-10: https://api-docs.deepseek.com/guides/vision/
# Never extend these declarations to model prefixes or third-party endpoints.
_DEEPSEEK_IMAGES = {
    "deepseek-v4-flash-vision-exp": True,
    "deepseek-v4-flash": False,
    "deepseek-v4-pro": False,
    "deepseek-chat": False,
    "deepseek-reasoner": False,
}


def image_capability(config: Config, model: str) -> ImageCapability:
    pc = config.effective_provider_config()
    if model in pc.image_models:
        return ImageCapability(pc.image_models[model], "model_config")
    if pc.image_input is not None:
        return ImageCapability(pc.image_input, "provider_config")

    endpoint = urlsplit(pc.base_url or "")
    if (
        endpoint.scheme == "https"
        and endpoint.netloc.lower() == "api.deepseek.com"
        and endpoint.path.rstrip("/") in {"", "/v1", "/anthropic", "/anthropic/v1"}
        and not endpoint.query
        and pc.protocol in {"openai", "anthropic"}
        and model in _DEEPSEEK_IMAGES
    ):
        return ImageCapability(_DEEPSEEK_IMAGES[model], "official_docs")

    if config.vision.model:
        from deepseek_tui.config.routing import config_for_model

        helper = config_for_model(config, config.vision.model)
        if helper.provider == config.provider and helper.effective_provider_config().model == model:
            # A user declaration enables a native attempt; it is not a successful vision test.
            return ImageCapability(True, "helper_selection")
    return ImageCapability(None, "unknown")
