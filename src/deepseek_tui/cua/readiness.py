"""Check the active model route before exposing desktop actions."""

from deepseek_tui.config.image_capabilities import image_capability
from deepseek_tui.config.routing import config_for_model


def vision_error(config, model: str) -> str:
    try:
        route = config_for_model(config, model)
        model = route.effective_provider_config().model
    except ValueError as exc:
        return f"CUA model configuration is invalid: {exc}"
    if image_capability(route, model).supported is not False:
        return ""
    if not route.vision.model:
        return "CUA needs a vision-capable model or a configured vision.model helper."
    try:
        helper = config_for_model(route, route.vision.model)
        helper_model = helper.effective_provider_config().model
        if (
            helper.provider == route.provider
            and helper_model == model
            or image_capability(helper, helper_model).supported is False
        ):
            return "CUA vision.model must select a different, vision-capable route."
    except ValueError as exc:
        return f"CUA vision configuration is invalid: {exc}"
    return ""
