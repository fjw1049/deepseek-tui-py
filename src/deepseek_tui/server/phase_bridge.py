"""Phase-bridge narration — stage summaries after reasoning → tools."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from deepseek_tui.config.providers import PROVIDER_DEFAULTS
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
    batch_root as _batch_root,
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
    from deepseek_tui.client.base import LLMClient
    from deepseek_tui.config.models import Config, ProcessNarrationConfig

logger = logging.getLogger(__name__)

PHASE_BRIDGE_METADATA_KEY = "phase_bridge"
PHASE_BRIDGE_AFTER_REASONING_KEY = "after_reasoning_id"
PROCESS_INTENT_METADATA_KEY = "process_intent"
ACTIVE_PLUGIN_METADATA_KEY = "active_plugin"

MAX_PUBLISHED_PER_TURN = 12
GateDecision = Literal["skip", "compute"]

IntentScope = Literal["pre_tool", "milestone"]
IntentSource = Literal["primary_model", "narration_service", "none"]


@dataclass(frozen=True, slots=True)
class ReasoningSegment:
    item_id: str
    text: str


@dataclass(frozen=True, slots=True)
class ProcessIntent:
    """Structured description of one narration frame.

    This is the model-agnostic contract between runtime and UI: semantics live
    in these fields (never inferred from display text), while ``text`` is an
    optional human wording supplied by the primary model or the narration
    service. ``source == "none"`` means the UI should render a neutral
    progress state from the structured fields alone.
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
    published_count: int = 0
    last_fingerprint: str | None = None
    last_published_at: float | None = None
    explored_roots: set[str] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class NarrationPlan:
    publish: bool
    phase: str
    finding: str
    next_goal: str

    def display_text(self, *, locale: str = "zh") -> str | None:
        parts = [p.strip() for p in (self.finding, self.next_goal) if p.strip()]
        if not parts:
            return None
        separator = "，" if locale == "zh" else ", "
        text = separator.join(parts)
        return _truncate(text, 120)


@dataclass(frozen=True, slots=True)
class IntentBundle:
    user_goal: str
    phase: str
    confirmed_facts: tuple[str, ...]
    working_hypothesis: tuple[str, ...]
    next_intent: str
    batch_intent: str
    locale: str


def resolve_narration_model(config: Config) -> str | None:
    cfg = config.ui.process_narration
    if cfg.model and cfg.model.strip():
        return cfg.model.strip()
    defaults = PROVIDER_DEFAULTS.get(config.provider)
    if defaults is None or not defaults.flash_model:
        return None
    return defaults.flash_model


def _normalize_fingerprint(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def extract_confirmed_facts(
    recent_tool_results: Sequence[str], *, limit: int = 3
) -> tuple[str, ...]:
    facts: list[str] = []
    for raw in recent_tool_results[-limit:]:
        line = raw.strip()
        if not line:
            continue
        if ":" in line:
            _, content = line.split(":", 1)
            snippet = _truncate(content.strip(), 160)
            if snippet:
                facts.append(snippet)
                continue
        facts.append(_truncate(line, 160))
    return tuple(facts)


def extract_working_hypothesis(segment: ReasoningSegment) -> tuple[str, ...]:
    lines = [ln.strip() for ln in segment.text.splitlines() if ln.strip()]
    if not lines:
        return ()
    joined = _truncate(" ".join(lines[:3]), 240)
    return (joined,) if joined else ()


def build_intent_bundle(
    *,
    user_goal: str,
    state: TurnNarrationState,
    segment: ReasoningSegment,
    tool_calls: Sequence[ToolCall],
    recent_tool_results: Sequence[str],
    locale: str,
) -> IntentBundle:
    batch = classify_batch(tool_calls)
    intent = batch_intent_text(batch, tool_calls, locale=locale)
    return IntentBundle(
        user_goal=_truncate(user_goal, 400),
        phase=state.phase.value,
        confirmed_facts=extract_confirmed_facts(recent_tool_results),
        working_hypothesis=extract_working_hypothesis(segment),
        next_intent=intent,
        batch_intent=intent,
        locale=locale,
    )


def gate_decision(
    *,
    state: TurnNarrationState,
    segment: ReasoningSegment | None,
    tool_calls: Sequence[ToolCall],
    narrated_ids: set[str],
    min_chars: int,
    has_tool_error: bool,
    pending_scheduled: int = 0,
    max_published: int = MAX_PUBLISHED_PER_TURN,
    min_interval_s: float = 0.0,
) -> GateDecision:
    if not tool_calls or segment is None:
        return "skip"
    if segment.item_id in narrated_ids:
        return "skip"
    if state.published_count + pending_scheduled >= max_published:
        return "skip"
    if len(segment.text.strip()) < min_chars:
        return "skip"
    if (
        not has_tool_error
        and state.last_published_at is not None
        and time.monotonic() - state.last_published_at < min_interval_s
    ):
        return "skip"

    # Phase narration is a low-frequency milestone, not a running commentary.
    # The per-round preface already explains why the next tools are running;
    # emitting another LLM-written line for every read/search batch duplicates
    # that story and tends to arrive after its tools. Only summarize a real
    # phase transition (or recovery after an error).
    batch = classify_batch(tool_calls)
    next_phase = infer_next_phase(
        state.phase,
        batch,
        has_tool_error=has_tool_error,
    )
    if has_tool_error or next_phase != state.phase:
        return "compute"
    return "skip"


def validate_plan(plan: NarrationPlan, *, locale: str = "zh") -> bool:
    # Minimal structural validation only: reject empty plans and internal tool
    # function names leaking into user-visible text. Language/style are the
    # narration model's responsibility (locale is passed in the request).
    combined = f"{plan.finding} {plan.next_goal}"
    if not plan.finding.strip() and not plan.next_goal.strip():
        return False
    if contains_tool_name(combined):
        return False
    return True


def render_plan(plan: NarrationPlan, *, locale: str = "zh") -> str | None:
    if not validate_plan(plan, locale=locale):
        return None
    return plan.display_text(locale=locale)


def note_published(
    state: TurnNarrationState,
    text: str,
    *,
    batch: BatchKind,
    tool_calls: Sequence[ToolCall],
) -> None:
    state.published_count += 1
    state.last_fingerprint = _normalize_fingerprint(text)
    state.last_published_at = time.monotonic()
    if batch == BatchKind.EXPLORE_DIR:
        root = _batch_root(tool_calls)
        if root:
            state.explored_roots.add(root)
    state.phase = infer_next_phase(state.phase, batch, has_tool_error=False)


def _format_intent_bundle(bundle: IntentBundle) -> str:
    facts = "\n".join(f"- {fact}" for fact in bundle.confirmed_facts) or "- (none)"
    hypotheses = "\n".join(f"- {line}" for line in bundle.working_hypothesis) or "- (none)"
    if bundle.locale == "en":
        return (
            f"User goal: {bundle.user_goal}\n"
            f"Current phase: {bundle.phase}\n"
            f"Confirmed facts:\n{facts}\n"
            f"Working hypothesis (unverified):\n{hypotheses}\n"
            f"Next intent: {bundle.next_intent}\n"
            f"Batch summary: {bundle.batch_intent}\n"
            f"Output language: English\n"
        )
    return (
        f"用户目标: {bundle.user_goal}\n"
        f"当前阶段: {bundle.phase}\n"
        f"已确认事实:\n{facts}\n"
        f"当前判断(未验证):\n{hypotheses}\n"
        f"下一步意图: {bundle.next_intent}\n"
        f"本轮工作摘要: {bundle.batch_intent}\n"
        f"输出语言: 中文\n"
    )


NARRATION_TOOL_NAME = "narration_emit"

_LOCALE_LABELS = {"zh": "Chinese", "en": "English"}


def narration_tool_schema() -> dict[str, Any]:
    """Wire schema for the forced narration tool call.

    Structured output travels through the same provider-normalized tool-call
    channel the agent already uses (OpenAI/Anthropic shapes, argument JSON
    repair), so no natural-language parsing is needed on any provider.
    """
    return {
        "type": "function",
        "function": {
            "name": NARRATION_TOOL_NAME,
            "description": (
                "Publish a one-line progress update for the user, or decline "
                "by setting publish=false."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "publish": {
                        "type": "boolean",
                        "description": "False when there is no new, evidence-backed progress worth showing.",
                    },
                    "phase": {
                        "type": "string",
                        "enum": [p.value for p in Phase],
                        "description": "Current work phase.",
                    },
                    "finding": {
                        "type": "string",
                        "description": "What the evidence established or ruled out, anchored to files/symbols.",
                    },
                    "next_goal": {
                        "type": "string",
                        "description": "The next concrete verification objective. Empty if none.",
                    },
                },
                "required": ["publish", "finding"],
            },
        },
    }


def _narration_prompts(bundle: IntentBundle) -> tuple[str, str]:
    body = _format_intent_bundle(bundle)
    language = _LOCALE_LABELS.get(bundle.locale, bundle.locale)
    user_prompt = (
        f"{body}\n"
        f"Call {NARRATION_TOOL_NAME} exactly once to report progress to the user."
    )
    system_prompt = (
        "You summarize a coding agent's progress for its user. "
        f"Always respond by calling the {NARRATION_TOOL_NAME} tool exactly once; "
        "never reply with plain text. Set publish=false when there is no new, "
        "evidence-backed progress. `finding` states what the evidence "
        "established or failed to establish; `next_goal` states the next "
        "verification objective. Do not mention internal tool function names "
        f"or meta-commentary. Write all user-visible strings in {language}."
    )
    return user_prompt, system_prompt


def plan_from_arguments(arguments: dict[str, Any]) -> NarrationPlan:
    return NarrationPlan(
        publish=bool(arguments.get("publish")),
        phase=str(arguments.get("phase") or "explore"),
        finding=str(arguments.get("finding") or "").strip(),
        next_goal=str(arguments.get("next_goal") or "").strip(),
    )


def _parse_plan_json(raw: str) -> NarrationPlan | None:
    """Language-neutral fallback for models that ignore forced tool choice."""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return plan_from_arguments(data)


async def compute_narration_plan(
    client: LLMClient,
    *,
    model: str,
    bundle: IntentBundle,
    timeout_s: float,
) -> NarrationPlan | None:
    from deepseek_tui.protocol.messages import Message as Msg
    from deepseek_tui.protocol.messages import MessageRequest

    user_prompt, system_prompt = _narration_prompts(bundle)
    request = MessageRequest(
        model=model,
        messages=[Msg.user(user_prompt)],
        system_prompt=system_prompt,
        tools=[narration_tool_schema()],
        tool_choice={"type": "tool", "name": NARRATION_TOOL_NAME},
        max_tokens=240,
        temperature=0.1,
        reasoning_effort="low",
    )

    async def _run() -> NarrationPlan | None:
        from deepseek_tui.protocol.responses import (
            StreamTextDelta,
            StreamToolCallComplete,
        )

        chunks: list[str] = []
        async for event in client.stream_chat_completion(request):
            if isinstance(event, StreamToolCallComplete):
                if event.tool_call.name == NARRATION_TOOL_NAME:
                    return plan_from_arguments(event.tool_call.arguments)
            elif isinstance(event, StreamTextDelta):
                chunks.append(event.text)
        source = "".join(chunks).strip()
        if not source:
            logger.info("phase_bridge narration model returned no tool call")
            return None
        return _parse_plan_json(source)

    try:
        return await asyncio.wait_for(_run(), timeout=timeout_s)
    except asyncio.TimeoutError:
        logger.info("phase_bridge narration timeout after %.1fs", timeout_s)
        return None
    except Exception as exc:
        logger.info(
            "phase_bridge narration failed: %s: %s",
            type(exc).__name__,
            exc or "(empty)",
        )
        return None


async def compute_narration_display(
    client: LLMClient,
    config: Config,
    *,
    user_goal: str,
    state: TurnNarrationState,
    segment: ReasoningSegment,
    tool_calls: Sequence[ToolCall],
    recent_tool_results: Sequence[str],
    locale: str,
) -> str | None:
    """Return the narration line, or None when nothing trustworthy exists.

    No template fallback: a milestone either carries model-written,
    evidence-grounded text or is not shown at all. The structured
    ``ProcessIntent`` frame still reaches the UI either way.
    """
    cfg: ProcessNarrationConfig = config.ui.process_narration
    model = resolve_narration_model(config)
    if not model:
        logger.info("phase_bridge no narration model configured")
        return None
    bundle = build_intent_bundle(
        user_goal=user_goal,
        state=state,
        segment=segment,
        tool_calls=tool_calls,
        recent_tool_results=recent_tool_results,
        locale=locale,
    )
    plan = await compute_narration_plan(
        client,
        model=model,
        bundle=bundle,
        timeout_s=cfg.flash_timeout_s,
    )
    if plan is None:
        logger.info("phase_bridge compute_narration_plan returned None")
        return None
    if not plan.publish:
        logger.info("phase_bridge narration declined publish")
        return None
    rendered = render_plan(plan, locale=locale)
    if rendered:
        logger.info("phase_bridge success narration=%s", rendered[:80])
        return rendered
    logger.info(
        "phase_bridge render_plan rejected finding=%r next_goal=%r",
        plan.finding[:60] if plan.finding else "",
        plan.next_goal[:60] if plan.next_goal else "",
    )
    return None
