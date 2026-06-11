from __future__ import annotations

import pytest

from deepseek_tui.host.services import ServiceRegistry, ServiceRegistryError, ServiceScope


class FakeService:
    def __init__(self, events: list[str], name: str) -> None:
        self._events = events
        self._name = name

    async def shutdown(self) -> None:
        self._events.append(self._name)


def test_service_registry_typed_require_optional_and_duplicate() -> None:
    registry = ServiceRegistry()
    service = FakeService([], "svc")

    assert registry.optional(FakeService) is None
    registry.add(FakeService, service, owner="test", scope=ServiceScope.PROCESS)

    assert registry.require(FakeService) is service
    assert registry.optional(FakeService) is service
    assert registry.registration_for(FakeService).owner == "test"

    with pytest.raises(ServiceRegistryError, match="already registered"):
        registry.add(FakeService, service, owner="other", scope=ServiceScope.PROCESS)


def test_service_registry_named_bridge() -> None:
    registry = ServiceRegistry()
    service = object()

    assert registry.optional_named("legacy_key") is None
    registry.add_named("legacy_key", service, owner="legacy", scope=ServiceScope.THREAD)

    assert registry.require_named("legacy_key") is service
    assert registry.named_registration_for("legacy_key").scope is ServiceScope.THREAD

    with pytest.raises(ServiceRegistryError, match="named service"):
        registry.add_named("legacy_key", object(), owner="other", scope=ServiceScope.THREAD)


def test_service_registry_missing_require_has_clear_error() -> None:
    registry = ServiceRegistry()

    with pytest.raises(ServiceRegistryError, match="required service"):
        registry.require(FakeService)
    with pytest.raises(ServiceRegistryError, match="required named service"):
        registry.require_named("missing")


@pytest.mark.asyncio
async def test_service_registry_shutdown_reverse_order_once_per_object() -> None:
    events: list[str] = []
    first = FakeService(events, "first")
    second = FakeService(events, "second")
    registry = ServiceRegistry()

    registry.add(FakeService, first, owner="first", scope=ServiceScope.PROCESS)
    registry.add_named("first_alias", first, owner="first", scope=ServiceScope.PROCESS)
    registry.add_named("second", second, owner="second", scope=ServiceScope.PROCESS)

    await registry.shutdown()

    assert events == ["second", "first"]
