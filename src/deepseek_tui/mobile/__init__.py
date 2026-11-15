"""Mobile transport adapters over the existing Runtime and desktop services."""

from typing import Any


def attach_mobile_api(app: Any) -> None:
    """Mount the mobile adapters without changing their public route paths."""
    from deepseek_tui.mobile import devices, files, git, models, settings, terminal, voice

    for module in (files, voice, git, terminal, settings, devices, models):
        app.include_router(module.router)


async def close_mobile_services(app: Any) -> None:
    """Release mobile-owned helpers when the Runtime shuts down."""
    from deepseek_tui.mobile.terminal import close_mobile_terminals

    await close_mobile_terminals(app)
