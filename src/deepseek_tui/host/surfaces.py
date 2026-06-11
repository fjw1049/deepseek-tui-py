"""Runtime surface contribution contracts for capability modules."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

HttpMethod = Literal["GET", "POST", "PATCH", "PUT", "DELETE"]
SurfaceHandler = Callable[..., Awaitable[object] | object]
EventPresenter = Callable[[object], dict[str, Any] | None]


@dataclass(frozen=True, slots=True)
class RuntimeRouteContribution:
    id: str
    owner: str
    method: HttpMethod
    path: str
    handler: SurfaceHandler


@dataclass(frozen=True, slots=True)
class EventPresenterContribution:
    id: str
    owner: str
    event_kind: str
    presenter: EventPresenter
    version: int = 1


class RuntimeSurfaceRegistryError(RuntimeError):
    """Raised when runtime surface contributions conflict."""


class RuntimeSurfaceRegistry:
    """Registry for optional API/event surfaces contributed by capabilities.

    The registry records contributions only; app-server integration remains
    host-owned so route paths, status codes, and payload policy stay centralized.
    """

    def __init__(self) -> None:
        self._routes: dict[tuple[str, str], RuntimeRouteContribution] = {}
        self._presenters: dict[str, EventPresenterContribution] = {}

    def add_route(
        self,
        *,
        id: str,
        owner: str,
        method: HttpMethod,
        path: str,
        handler: SurfaceHandler,
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
        )

    def add_event_presenter(
        self,
        *,
        id: str,
        owner: str,
        event_kind: str,
        presenter: EventPresenter,
        version: int = 1,
    ) -> None:
        if event_kind in self._presenters:
            existing = self._presenters[event_kind]
            raise RuntimeSurfaceRegistryError(
                f"event presenter {event_kind!r} already registered by "
                f"{existing.owner}"
            )
        self._presenters[event_kind] = EventPresenterContribution(
            id=id,
            owner=owner,
            event_kind=event_kind,
            presenter=presenter,
            version=version,
        )

    def routes(self) -> tuple[RuntimeRouteContribution, ...]:
        return tuple(
            sorted(self._routes.values(), key=lambda item: (item.path, item.method))
        )

    def event_presenters(self) -> tuple[EventPresenterContribution, ...]:
        return tuple(sorted(self._presenters.values(), key=lambda item: item.event_kind))

    def presenter_for(self, event_kind: str) -> EventPresenterContribution | None:
        return self._presenters.get(event_kind)


def mount_surface_routes(router: object, registry: RuntimeSurfaceRegistry) -> None:
    """Mount contributed runtime routes onto an isolated FastAPI router."""
    for contribution in registry.routes():
        router.add_api_route(  # type: ignore[attr-defined]
            contribution.path,
            contribution.handler,
            methods=[contribution.method],
            name=contribution.id,
        )


def build_surface_router(registry: RuntimeSurfaceRegistry) -> object:
    """Build a router containing only contributed runtime surfaces."""
    from fastapi import APIRouter

    router = APIRouter()
    mount_surface_routes(router, registry)
    return router
