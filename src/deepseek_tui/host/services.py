"""Typed service registry for host-owned runtime composition.

Capability modules should register long-lived dependencies here instead of
adding new magic-string entries to ``ToolContext.metadata``. Existing metadata
keys remain supported through the named-service bridge during migration.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from enum import Enum
from typing import Any, TypeVar, cast

T = TypeVar("T")


class ServiceScope(str, Enum):
    PROCESS = "process"
    ENGINE = "engine"
    THREAD = "thread"
    TURN = "turn"


class ServiceRegistryError(RuntimeError):
    """Raised when service composition is invalid."""


@dataclass(frozen=True, slots=True)
class ServiceRegistration:
    key: object
    value: object
    owner: str
    scope: ServiceScope


class ServiceRegistry:
    """Small typed service locator owned by the host assembly layer."""

    def __init__(self) -> None:
        self._typed: dict[type[Any], ServiceRegistration] = {}
        self._named: dict[str, ServiceRegistration] = {}
        self._start_order: list[ServiceRegistration] = []
        self._externally_owned_values: set[int] = set()
        self._shutdown_values: set[int] = set()

    def add(
        self,
        key: type[T],
        value: T,
        *,
        owner: str,
        scope: ServiceScope,
    ) -> None:
        if key in self._typed:
            existing = self._typed[key]
            raise ServiceRegistryError(
                f"service {key.__module__}.{key.__qualname__} already registered "
                f"by {existing.owner}"
            )
        registration = ServiceRegistration(key=key, value=value, owner=owner, scope=scope)
        self._typed[key] = registration
        self._start_order.append(registration)

    def require(self, key: type[T]) -> T:
        value = self.optional(key)
        if value is None:
            raise ServiceRegistryError(
                f"required service {key.__module__}.{key.__qualname__} is not registered"
            )
        return value

    def optional(self, key: type[T]) -> T | None:
        registration = self._typed.get(key)
        if registration is None:
            return None
        return cast(T, registration.value)

    def add_named(
        self,
        key: str,
        value: object,
        *,
        owner: str,
        scope: ServiceScope,
    ) -> None:
        if key in self._named:
            existing = self._named[key]
            raise ServiceRegistryError(
                f"named service {key!r} already registered by {existing.owner}"
            )
        registration = ServiceRegistration(key=key, value=value, owner=owner, scope=scope)
        self._named[key] = registration
        self._start_order.append(registration)

    def require_named(self, key: str) -> object:
        value = self.optional_named(key)
        if value is None:
            raise ServiceRegistryError(f"required named service {key!r} is not registered")
        return value

    def optional_named(self, key: str) -> object | None:
        registration = self._named.get(key)
        if registration is None:
            return None
        return registration.value

    def registration_for(self, key: type[object]) -> ServiceRegistration | None:
        return self._typed.get(key)

    def named_registration_for(self, key: str) -> ServiceRegistration | None:
        return self._named.get(key)

    def typed_keys(self) -> tuple[type[Any], ...]:
        return tuple(self._typed.keys())

    def named_keys(self) -> tuple[str, ...]:
        return tuple(self._named.keys())

    def mark_externally_owned(self, value: object) -> None:
        """Exclude a caller-owned service from registry-coordinated shutdown."""
        self._externally_owned_values.add(id(value))

    def merge_from(self, other: ServiceRegistry) -> None:
        """Copy registrations from *other* into this registry."""
        for registration in other._start_order:
            if isinstance(registration.key, str):
                if registration.key in self._named:
                    existing = self._named[registration.key]
                    raise ServiceRegistryError(
                        f"named service {registration.key!r} already registered "
                        f"by {existing.owner}"
                    )
                self._named[registration.key] = registration
            else:
                key = cast(type[Any], registration.key)
                if key in self._typed:
                    existing = self._typed[key]
                    raise ServiceRegistryError(
                        f"service {key.__module__}.{key.__qualname__} already registered "
                        f"by {existing.owner}"
                    )
                self._typed[key] = registration
            self._start_order.append(registration)

    async def shutdown(self) -> None:
        """Best-effort reverse shutdown for host-owned services."""
        await self.shutdown_scope()

    async def shutdown_scope(self, scope: ServiceScope | None = None) -> None:
        """Shutdown services, optionally limited to one scope."""
        seen: set[int] = set()
        for registration in reversed(self._start_order):
            if scope is not None and registration.scope != scope:
                continue
            value = registration.value
            identity = id(value)
            if (
                identity in seen
                or identity in self._shutdown_values
                or identity in self._externally_owned_values
            ):
                continue
            seen.add(identity)
            await self._shutdown_value(value)
            self._shutdown_values.add(identity)

    async def _shutdown_value(self, value: object) -> None:
        for method_name in ("shutdown", "stop", "stop_all", "close", "close_all"):
            method = getattr(value, method_name, None)
            if not callable(method):
                continue
            result = method()
            if inspect.isawaitable(result):
                await result
            return


def copy_process_scoped_services(
    source: ServiceRegistry,
    target: ServiceRegistry,
) -> None:
    """Copy PROCESS-scoped registrations from *source* into *target*."""
    for registration in source._start_order:
        if registration.scope != ServiceScope.PROCESS:
            continue
        if isinstance(registration.key, str):
            if target.optional_named(registration.key) is not None:
                continue
            target.add_named(
                registration.key,
                registration.value,
                owner=registration.owner,
                scope=registration.scope,
            )
            continue
        key = cast(type[Any], registration.key)
        if target.optional(key) is not None:
            continue
        target.add(
            key,
            registration.value,
            owner=registration.owner,
            scope=registration.scope,
        )
