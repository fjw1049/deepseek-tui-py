"""Resolve a provider-qualified model without carrying another provider's key."""

from deepseek_tui.config.models import Config


def config_for_model(
    config: Config, model: str | None = None, *, provider: str | None = None
) -> Config:
    resolved = config.model_copy(deep=True)
    selected = model
    if selected and "::" in selected:
        provider, selected = selected.split("::", 1)
        if not provider.strip() or not selected.strip():
            raise ValueError("Model reference must be provider::model")
    target = (provider or config.provider).strip()
    from deepseek_tui.config.providers import PROVIDER_DEFAULTS

    if (
        target != config.provider
        and target not in config.providers
        and target not in PROVIDER_DEFAULTS
    ):
        raise ValueError(f"Unknown model provider: {target}")
    if target != config.provider:
        resolved.api_key = None
        resolved.base_url = None
        resolved.model = None
    resolved.provider = target
    if selected is not None:
        resolved.model = selected.strip()
    return resolved
