import pytest

from deepseek_tui.config.image_capabilities import image_capability
from deepseek_tui.config.models import Config, ProviderConfig, VisionConfig


@pytest.mark.parametrize(
    "model, expected",
    [
        ("deepseek-v4-flash-vision-exp", True),
        ("deepseek-v4-flash", False),
        ("deepseek-future-model", None),
        ("random-vision-model", None),
    ],
)
def test_official_exact_models_only(model, expected):
    assert image_capability(Config(), model).supported is expected


@pytest.mark.parametrize(
    "url",
    [
        "https://proxy.test",
        "https://api.deepseek.com.proxy.test",
        "https://api.deepseek.com/custom",
        "http://api.deepseek.com",
    ],
)
def test_official_capability_does_not_transfer_to_other_routes(url):
    config = Config(base_url=url)
    assert image_capability(config, "deepseek-v4-flash").supported is None
    assert image_capability(config, "deepseek-v4-flash-vision-exp").supported is None


def test_explicit_model_override_wins_over_provider_and_catalog():
    config = Config(
        providers={
            "deepseek": ProviderConfig(
                image_input=False, image_models={"deepseek-v4-flash-vision-exp": True}
            )
        }
    )
    capability = image_capability(config, "deepseek-v4-flash-vision-exp")
    assert capability.supported is True
    assert capability.source == "model_config"


def test_manual_helper_declaration_is_distinct_from_verified_support():
    config = Config(vision=VisionConfig(model="deepseek::deepseek-new-experiment"))
    capability = image_capability(config, "deepseek-new-experiment")
    assert capability.supported is True
    assert capability.source == "helper_selection"
    assert image_capability(config, "other-model").supported is None
    config.providers["deepseek"] = ProviderConfig(image_input=False)
    assert image_capability(config, "deepseek-new-experiment").supported is False


def test_known_text_helper_stays_rejected_without_explicit_capability_override():
    config = Config(vision=VisionConfig(model="deepseek::deepseek-v4-flash"))
    assert image_capability(config, "deepseek-v4-flash").supported is False
