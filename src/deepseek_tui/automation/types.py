"""Optional automation metadata (delivery / digest) — backward compatible."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class DeliveryConfig:
    """Mirrors OpenHuman ``DeliveryConfig`` subset used after cron agent runs."""

    mode: str = "silent"
    chat_id: str | None = None
    channel: str | None = None
    to: str | None = None
    best_effort: bool = True
    thread_id: str | None = None

    def is_active(self) -> bool:
        return self.mode.strip().lower() not in ("", "silent", "none")

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None) -> DeliveryConfig:
        if not raw:
            return cls()
        mode = str(raw.get("mode", "silent")).strip().lower() or "silent"
        return cls(
            mode=mode,
            chat_id=_opt_str(raw.get("chat_id")),
            channel=_opt_str(raw.get("channel")),
            to=_opt_str(raw.get("to")),
            best_effort=bool(raw.get("best_effort", True)),
            thread_id=_opt_str(raw.get("thread_id")),
        )


@dataclass(frozen=True, slots=True)
class DigestConfig:
    """Prefetch sources injected before the agent prompt (email / feishu / …)."""

    sources: tuple[str, ...] = ()
    account: str | None = None

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None) -> DigestConfig | None:
        if not raw:
            return None
        sources_raw = raw.get("sources")
        if not isinstance(sources_raw, list) or not sources_raw:
            return None
        sources = tuple(str(s).strip() for s in sources_raw if str(s).strip())
        if not sources:
            return None
        return cls(sources=sources, account=_opt_str(raw.get("account")))


def _opt_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def cron_prompt_prefix(automation_id: str, name: str) -> str:
    """Align with OpenHuman ``[cron:{id} {name}]`` prefix."""
    return f"[cron:{automation_id} {name}] "
