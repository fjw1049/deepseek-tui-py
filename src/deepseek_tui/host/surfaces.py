"""Runtime surface contribution contracts for capability modules."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

HttpMethod = Literal["GET", "POST", "PATCH", "PUT", "DELETE"]
SurfaceHandler = Callable[..., Awaitable[object] | object]


@dataclass(frozen=True, slots=True)
class RuntimeRouteContribution:
    id: str
    owner: str
    method: HttpMethod
    path: str
    handler: SurfaceHandler
    status_code: int | None = None


class RuntimeSurfaceRegistryError(RuntimeError):
    """Raised when runtime surface contributions conflict."""


class RuntimeSurfaceRegistry:
    """Registry for optional API/event surfaces contributed by capabilities.

    The registry records contributions only; app-server integration remains
    host-owned so route paths, status codes, and payload policy stay centralized.
    """

    def __init__(self) -> None:
        self._routes: dict[tuple[str, str], RuntimeRouteContribution] = {}

    def add_route(
        self,
        *,
        id: str,
        owner: str,
        method: HttpMethod,
        path: str,
        handler: SurfaceHandler,
        status_code: int | None = None,
    ) -> None:
        normalized_method = method.upper()
        route_key = (normalized_method, path)
        if route_key in self._routes:
            existing = self._routes[route_key]
            raise RuntimeSurfaceRegistryError(
                f"runtime route {normalized_method} {path!r} already registered "
                f"by {existing.owner}"
            )
        self._routes[route_key] = RuntimeRouteContribution(
            id=id,
            owner=owner,
            method=normalized_method,  # type: ignore[arg-type]
            path=path,
            handler=handler,
            status_code=status_code,
        )

    def routes(self) -> tuple[RuntimeRouteContribution, ...]:
        return tuple(
            sorted(self._routes.values(), key=lambda item: (item.path, item.method))
        )

    def merge_routes_from(self, source: RuntimeSurfaceRegistry) -> None:
        """Copy route contributions from *source* into this registry."""
        for route in source.routes():
            self.add_route(
                id=route.id,
                owner=route.owner,
                method=route.method,
                path=route.path,
                handler=route.handler,
                status_code=route.status_code,
            )


def mount_surface_routes(router: object, registry: RuntimeSurfaceRegistry) -> None:
    """Mount contributed runtime routes onto an isolated FastAPI router."""
    for contribution in registry.routes():
        route_kwargs: dict[str, object] = {
            "methods": [contribution.method],
            "name": contribution.id,
        }
        if contribution.status_code is not None:
            route_kwargs["status_code"] = contribution.status_code
        router.add_api_route(  # type: ignore[attr-defined]
            contribution.path,
            contribution.handler,
            **route_kwargs,
        )


def build_surface_router(registry: RuntimeSurfaceRegistry) -> object:
    """Build a router containing only contributed runtime surfaces."""
    from fastapi import APIRouter

    router = APIRouter()
    mount_surface_routes(router, registry)
    return router
