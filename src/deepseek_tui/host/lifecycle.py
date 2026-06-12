"""Lifecycle observer contracts for capability modules.

These registries are intentionally narrow: the host owns turn/tool execution
order, while capability modules can register observers for explicit phases.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

PREPARED_USER_TURN_DECORATION = "host.prepared_user_turn"
TURN_LIFECYCLE_RESULT_DECORATION = "host.turn_lifecycle_result"


@dataclass(slots=True)
class PreparedUserTurn:
    thread_id: str
    recall: object | None
    user_message: object


@dataclass(slots=True)
class TurnLifecycleResult:
    follow_up: object | None = None
    steer: str | None = None


@dataclass(frozen=True, slots=True)
class BeforeUserTurnContext:
    thread_id: str
    turn_id: str
    user_text: str
    workspace: Path
    metadata: dict[str, object]
    services: object
    decorations: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TurnStartedContext:
    thread_id: str
    turn_id: str
    metadata: dict[str, object]
    services: object


@dataclass(frozen=True, slots=True)
class TurnCompletionContext:
    thread_id: str
    turn_id: str
    success: bool
    usage: object | None
    metadata: dict[str, object]
    services: object
    decorations: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TurnFailureContext:
    thread_id: str
    turn_id: str
    reason: str
    usage: object | None
    metadata: dict[str, object]
    services: object
    decorations: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AfterToolContext:
    tool_call_id: str
    tool_name: str
    arguments: dict[str, object]
    success: bool
    result: object | None
    metadata: dict[str, object]
    services: object


class BeforeUserTurnObserver(Protocol):
    async def before_user_turn(self, context: BeforeUserTurnContext) -> None: ...


class TurnStartedObserver(Protocol):
    async def on_turn_started(self, context: TurnStartedContext) -> None: ...


class TurnCompletionObserver(Protocol):
    async def on_turn_completed(self, context: TurnCompletionContext) -> None: ...


class TurnFailureObserver(Protocol):
    async def on_turn_failed(self, context: TurnFailureContext) -> None: ...


class ToolObserver(Protocol):
    async def after_tool(self, context: AfterToolContext) -> None: ...


@dataclass(frozen=True, slots=True)
class LifecycleObserverRegistration:
    id: str
    owner: str
    order: int
    observer: object


class LifecycleRegistryError(RuntimeError):
    """Raised when lifecycle observer registration is invalid."""


class LifecycleRegistry:
    """Ordered observer registry for host-owned lifecycle phases."""

    def __init__(self) -> None:
        self._registrations: dict[str, LifecycleObserverRegistration] = {}

    def add(
        self,
        *,
        id: str,
        owner: str,
        observer: object,
        order: int = 1000,
    ) -> None:
        if id in self._registrations:
            existing = self._registrations[id]
            raise LifecycleRegistryError(
                f"lifecycle observer {id!r} already registered by {existing.owner}"
            )
        self._registrations[id] = LifecycleObserverRegistration(
            id=id,
            owner=owner,
            order=order,
            observer=observer,
        )

    def registrations(self) -> tuple[LifecycleObserverRegistration, ...]:
        return tuple(
            sorted(self._registrations.values(), key=lambda item: (item.order, item.id))
        )

    async def before_user_turn(self, context: BeforeUserTurnContext) -> None:
        await self._dispatch("before_user_turn", context)

    async def on_turn_started(self, context: TurnStartedContext) -> None:
        await self._dispatch("on_turn_started", context)

    async def on_turn_completed(self, context: TurnCompletionContext) -> None:
        await self._dispatch("on_turn_completed", context)

    async def on_turn_failed(self, context: TurnFailureContext) -> None:
        await self._dispatch("on_turn_failed", context)

    async def after_tool(self, context: AfterToolContext) -> None:
        await self._dispatch("after_tool", context)

    async def _dispatch(self, method_name: str, context: object) -> None:
        for registration in self.registrations():
            method = getattr(registration.observer, method_name, None)
            if not callable(method):
                continue
            await method(context)


def lifecycle_observer_registered(registry: LifecycleRegistry, observer_id: str) -> bool:
    return any(
        registration.id == observer_id for registration in registry.registrations()
    )


@dataclass(frozen=True, slots=True)
class FunctionLifecycleObserver:
    """Small adapter for tests and simple capability glue."""

    on_before_user_turn: Callable[[BeforeUserTurnContext], Awaitable[None]] | None = None
    on_turn_started_cb: Callable[[TurnStartedContext], Awaitable[None]] | None = None
    on_turn_completed_cb: Callable[[TurnCompletionContext], Awaitable[None]] | None = None
    on_turn_failed_cb: Callable[[TurnFailureContext], Awaitable[None]] | None = None
    after_tool_cb: Callable[[AfterToolContext], Awaitable[None]] | None = None

    async def before_user_turn(self, context: BeforeUserTurnContext) -> None:
        if self.on_before_user_turn is not None:
            await self.on_before_user_turn(context)

    async def on_turn_started(self, context: TurnStartedContext) -> None:
        if self.on_turn_started_cb is not None:
            await self.on_turn_started_cb(context)

    async def on_turn_completed(self, context: TurnCompletionContext) -> None:
        if self.on_turn_completed_cb is not None:
            await self.on_turn_completed_cb(context)

    async def on_turn_failed(self, context: TurnFailureContext) -> None:
        if self.on_turn_failed_cb is not None:
            await self.on_turn_failed_cb(context)

    async def after_tool(self, context: AfterToolContext) -> None:
        if self.after_tool_cb is not None:
            await self.after_tool_cb(context)
