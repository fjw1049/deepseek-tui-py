"""Process intents: the structured step shown for each tool round."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from deepseek_tui.presentation.semantics import (
    BatchKind,
    Phase,
    batch_intent_text,
    classify_batch,
    contains_tool_name,
    infer_next_phase,
    resolve_narration_locale,
    template_narration,
    tool_path,
)
from deepseek_tui.presentation.semantics import (
    truncate_text as _truncate,
)
from deepseek_tui.protocol.responses import ToolCall

__all__ = [
    "BatchKind",
    "Phase",
    "batch_intent_text",
    "classify_batch",
    "contains_tool_name",
    "infer_next_phase",
    "resolve_narration_locale",
    "template_narration",
]

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

PROCESS_INTENT_METADATA_KEY = "process_intent"
ACTIVE_PLUGIN_METADATA_KEY = "active_plugin"

GateDecision = Literal["skip", "compute"]

IntentScope = Literal["pre_tool", "milestone"]
IntentSource = Literal["primary_model", "narration_service", "runtime", "none"]


@dataclass(frozen=True, slots=True)
class ProcessIntent:
    """Structured description of one narration frame.

    This is the model-agnostic contract between runtime and UI: semantics live
    in these fields (never inferred from display text), while ``text`` is an
    optional human wording supplied by the primary model or the narration
    service. ``source == "none"`` keeps an invisible frame for a later wording upsert;
    the UI must not manufacture prose from tool parameters.
    """

    scope: IntentScope
    source: IntentSource
    phase: str
    batch: str
    tool_count: int
    anchors: tuple[str, ...] = ()
    locale: str = "zh"

    def to_metadata(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "source": self.source,
            "phase": self.phase,
            "batch": self.batch,
            "tool_count": self.tool_count,
            "anchors": list(self.anchors),
            "locale": self.locale,
        }


@dataclass(frozen=True, slots=True)
class PluginMountInfo:
    """Structured snapshot of the session's mounted-plugin state.

    Mirrors :class:`~deepseek_tui.engine.events.PluginMountEvent`: persisted
    under ``metadata[ACTIVE_PLUGIN_METADATA_KEY]`` on a STATUS turn item so
    the UI can render a persistent chip and the engine can re-apply the mount
    on thread reload. ``name is None`` means unmounted.
    """

    name: str | None
    version: str = ""
    path: str = ""
    scope: str = ""
    trusted: bool = False
    permissions: tuple[str, ...] = ()
    mcp_active: bool = False

    def to_metadata(self) -> dict[str, Any] | None:
        if self.name is None:
            return None
        return {
            "name": self.name,
            "version": self.version,
            "path": self.path,
            "scope": self.scope,
            "trusted": self.trusted,
            "permissions": list(self.permissions),
            "mcp_active": self.mcp_active,
        }

    @classmethod
    def from_metadata(cls, raw: Any) -> PluginMountInfo | None:
        """Reconstruct from persisted metadata.

        Returns ``None`` when ``raw`` is ``None`` (explicit unmount marker
        is preserved as a bare ``PluginMountInfo(name=None)`` by the caller
        distinguishing "no signal" from "unmounted"). Here we only parse a
        dict payload; callers treat ``None`` themselves.
        """
        if not isinstance(raw, dict):
            return None
        name = raw.get("name")
        return cls(
            name=str(name) if isinstance(name, str) and name else None,
            version=str(raw.get("version") or ""),
            path=str(raw.get("path") or ""),
            scope=str(raw.get("scope") or ""),
            trusted=bool(raw.get("trusted", False)),
            permissions=tuple(
                p for p in (raw.get("permissions") or []) if isinstance(p, str)
            ),
            mcp_active=bool(raw.get("mcp_active", False)),
        )


def extract_anchors(tool_calls: Sequence[ToolCall], *, limit: int = 4) -> tuple[str, ...]:
    """Collect display anchors (paths/queries) from structured tool arguments.

    Purely structural: reads known argument keys, never parses prose.
    """
    anchors: list[str] = []
    for tool_call in tool_calls:
        args = dict(tool_call.arguments) if tool_call.arguments else None
        target = tool_path(args)
        if target is None and args:
            for key in ("query", "pattern", "command", "url"):
                value = args.get(key)
                if isinstance(value, str) and value.strip():
                    target = value.strip()
                    break
        if target:
            cleaned = _truncate(target, 80)
            if cleaned not in anchors:
                anchors.append(cleaned)
        if len(anchors) >= limit:
            break
    return tuple(anchors)


def build_process_intent(
    *,
    scope: IntentScope,
    source: IntentSource,
    phase: Phase,
    tool_calls: Sequence[ToolCall],
    locale: str,
) -> ProcessIntent:
    return ProcessIntent(
        scope=scope,
        source=source,
        phase=phase.value,
        batch=classify_batch(tool_calls).value,
        tool_count=len(tool_calls),
        anchors=extract_anchors(tool_calls),
        locale=locale,
    )


@dataclass
class TurnNarrationState:
    phase: Phase = Phase.EXPLORE


NARRATION_TOOL_NAME = "narration_emit"


