"""Runtime ports and registration leases owned by a PluginSession."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class RegistrationLease:
    async def close(self) -> None:
        """Remove this registration. Must be idempotent."""


@dataclass(slots=True)
class ToolRegistrationLease:
    registry: Any
    name: str
    _closed: bool = False

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        removed = self.registry.remove(self.name)
        if removed is None:
            return


@dataclass(slots=True)
class LeaseBag:
    leases: list[RegistrationLease] = field(default_factory=list)

    def add(self, lease: RegistrationLease) -> RegistrationLease:
        self.leases.append(lease)
        return lease

    async def close(self) -> None:
        # Close in reverse activation order.
        while self.leases:
            lease = self.leases.pop()
            await lease.close()
