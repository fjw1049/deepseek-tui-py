"""Rust-parity /v1 runtime routes for DeepSeek Workbench.

Routes are split by domain (health/threads/turns/events/approvals/user_inputs/
workspace) to keep each file under ~80 LOC. ``build_runtime_api_router``
assembles them so the public surface seen by ``attach_runtime_api`` is
unchanged.
"""

from __future__ import annotations

from fastapi import APIRouter

from deepseek_tui.app_server.runtime_api.routes import (
    approvals,
    elevations,
    events,
    health,
    jobs,
    sessions,
    skills,
    tasks,
    threads,
    turns,
    user_inputs,
    workspace,
)

__all__ = ["build_runtime_api_router"]


def build_runtime_api_router() -> APIRouter:
    from deepseek_tui.config.models import Config
    from deepseek_tui.host.assembler import collect_builtin_contributions
    from deepseek_tui.host.surfaces import mount_surface_routes

    router = APIRouter()
    router.include_router(health.router)
    router.include_router(threads.router)
    router.include_router(turns.router)
    router.include_router(events.router)
    router.include_router(approvals.router)
    router.include_router(elevations.router)
    router.include_router(jobs.router)
    router.include_router(user_inputs.router)
    router.include_router(sessions.router)
    router.include_router(skills.router)
    router.include_router(tasks.router)
    router.include_router(workspace.router)
    mount_surface_routes(router, collect_builtin_contributions(Config()).surfaces)
    return router
