"""Phase-bridge narration — stage summaries after reasoning → tools."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

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
)
from deepseek_tui.presentation.semantics import (
    batch_root as _batch_root,
)
from deepseek_tui.presentation.semantics import (
    script_counts as _script_counts,
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

MAX_PUBLISHED_PER_TURN = 12
GateDecision = Literal["skip", "use_preface", "compute"]


def preface_matches_locale(text: str, locale: str) -> bool:
    cjk, latin = _script_counts(text)
    total = cjk + latin
    if total == 0:
        return False
    if locale == "zh":
        return cjk > 0 and cjk / total >= 0.12
    return latin > 0 and cjk / total < 0.15


def locale_preface(text: str | None, locale: str) -> str | None:
    preface = usable_preface(text)
    if preface is None:
        return None
    if preface_matches_locale(preface, locale):
        return preface
    return None


def preface_language_mismatch(text: str | None, locale: str) -> bool:
    return usable_preface(text) is not None and locale_preface(text, locale) is None


def text_matches_locale(text: str, locale: str) -> bool:
    cleaned = text.strip()
    if not cleaned:
        return False
    cjk, latin = _script_counts(cleaned)
    total = cjk + latin
    if total == 0:
        return True
    if locale == "zh":
        return cjk > 0
    return latin > 0 and cjk / total < 0.2


@dataclass(frozen=True, slots=True)
class ReasoningSegment:
    item_id: str
    text: str


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


def usable_preface(text: str | None) -> str | None:
    if not text or not text.strip():
        return None
    cleaned = text.strip()
    if contains_tool_name(cleaned):
        return None
    if len(cleaned) < 8:
        return None
    return _truncate(cleaned, 120)


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
    preface_text: str | None,
    narrated_ids: set[str],
    min_chars: int,
    has_tool_error: bool,
    pending_scheduled: int = 0,
    locale: str = "zh",
    max_published: int = MAX_PUBLISHED_PER_TURN,
) -> GateDecision:
    if not tool_calls or segment is None:
        return "skip"
    if segment.item_id in narrated_ids:
        return "skip"
    if state.published_count + pending_scheduled >= max_published:
        return "skip"
    if len(segment.text.strip()) < min_chars:
        return "skip"

    batch = classify_batch(tool_calls)
    preface = locale_preface(preface_text, locale)

    if batch == BatchKind.EXPLORE_READ:
        fp = _normalize_fingerprint(batch_intent_text(batch, tool_calls, locale=locale))
        if state.last_fingerprint and fp == state.last_fingerprint:
            return "skip"
        return "compute"

    if batch == BatchKind.EXPLORE_DIR:
        root = _batch_root(tool_calls) or "."
        if root in state.explored_roots:
            return "skip"
        return "compute"

    if batch == BatchKind.SEARCH:
        fp = _normalize_fingerprint(batch_intent_text(batch, tool_calls, locale=locale))
        if state.last_fingerprint and fp == state.last_fingerprint:
            return "skip"
        return "compute"

    if batch == BatchKind.MIXED and len(tool_calls) >= 2:
        fp = _normalize_fingerprint(batch_intent_text(batch, tool_calls, locale=locale))
        if state.last_fingerprint and fp == state.last_fingerprint:
            return "skip"
        return "compute"

    if batch == BatchKind.MUTATE:
        return "compute"
    if batch == BatchKind.INSPECT and state.phase in {Phase.LOCATE, Phase.VERIFY, Phase.RECOVER}:
        return "compute"
    if has_tool_error or state.phase == Phase.RECOVER:
        return "compute"
    if infer_next_phase(state.phase, batch, has_tool_error=has_tool_error) != state.phase:
        return "compute"
    if preface and state.published_count == 0 and batch in {BatchKind.INSPECT, BatchKind.MIXED}:
        return "compute"

    return "skip"


def validate_plan(plan: NarrationPlan, *, locale: str = "zh") -> bool:
    combined = f"{plan.finding} {plan.next_goal}"
    if not plan.finding.strip() and not plan.next_goal.strip():
        return False
    if contains_tool_name(combined):
        return False
    return text_matches_locale(combined, locale)


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


def _flash_prompts(bundle: IntentBundle) -> tuple[str, str]:
    body = _format_intent_bundle(bundle)
    if bundle.locale == "en":
        user_prompt = (
            f"{body}\n"
            "Return ONLY one JSON object with fields:\n"
            '{"publish": true|false, "phase": "explore|locate|change|verify|recover", '
            '"finding": "confirmed/located fact from confirmed facts only", '
            '"next_goal": "next verification goal in English, no tool names"}\n'
            "Rules: publish=false when there is no new progress; finding/next_goal must "
            "not contain tool function names; do not repeat confirmed facts verbatim; "
            "finding and next_goal must be English."
        )
        system_prompt = (
            "You decide whether to show a one-line coding-assistant progress update. "
            "Respond with JSON only. All user-visible strings must be English."
        )
        return user_prompt, system_prompt

    user_prompt = (
        f"{body}\n\n"
        "请用一句中文（20-50字）描述当前进展。格式要求：\n"
        "- 直接输出一句话，不要任何前缀、分析过程或解释\n"
        "- 描述已确认的发现或正在做的事，例如：\n"
        "  「定位到 workflow 调度入口在 orchestrator.py 的 round-robin 循环中」\n"
        "  「发现配置加载链路经过 3 层：CLI → Config → TOML」\n"
        "  「正在分析 engine 的多轮工具调用机制」\n"
        "- 不要出现工具函数名(read_file/grep_files等)\n"
        "- 不要说「我们分析」「用户要求」等元描述"
    )
    system_prompt = (
        "直接输出一句中文进度描述。不要分析，不要解释，不要JSON。只输出那一句话。"
    )
    return user_prompt, system_prompt


def _parse_plan_json(raw: str) -> NarrationPlan | None:
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
    return NarrationPlan(
        publish=bool(data.get("publish")),
        phase=str(data.get("phase") or "explore"),
        finding=str(data.get("finding") or "").strip(),
        next_goal=str(data.get("next_goal") or "").strip(),
    )


_META_PREFIXES = re.compile(
    r"^(我们分析|我来分析|让我分析|分析一下|分析本轮|本轮工作摘要[：:]?\s*)"
    r"|^(当前阶段|用户(当前|正在|要求|提供|说))"
    r"|^(根据|基于|综合|总结[：:]?\s*)",
    re.MULTILINE,
)


def _extract_narration_from_text(raw: str) -> NarrationPlan | None:
    """Extract a usable narration when Flash returns prose instead of JSON.

    Strips meta-commentary prefixes and finds the core descriptive content.
    """
    text = raw.strip()
    if not text or len(text) < 6:
        return None

    # Strip meta prefixes like "我们分析一下..."
    cleaned = _META_PREFIXES.sub("", text).strip()
    if not cleaned:
        cleaned = text

    # If multi-sentence, try to find the most informative one
    sentences = re.split(r'[。；\n]', cleaned)
    sentences = [s.strip() for s in sentences if len(s.strip()) >= 8]

    best = None
    for s in sentences:
        if contains_tool_name(s):
            continue
        # Skip sentences that are still meta-commentary
        if re.match(r'^(用户|当前|上一轮|下一步|因此|所以)', s):
            continue
        best = s
        break

    if not best and sentences:
        # Fallback: just take first non-tool-name sentence
        for s in sentences:
            if not contains_tool_name(s):
                best = s
                break

    if not best:
        return None

    best = _truncate(best, 120)
    if len(best) < 6:
        return None

    return NarrationPlan(
        publish=True,
        phase="explore",
        finding=best,
        next_goal="",
    )


async def compute_narration_plan(
    client: LLMClient,
    *,
    model: str,
    bundle: IntentBundle,
    timeout_s: float,
) -> NarrationPlan | None:
    from deepseek_tui.protocol.messages import Message as Msg
    from deepseek_tui.protocol.messages import MessageRequest

    user_prompt, system_prompt = _flash_prompts(bundle)
    request = MessageRequest(
        model=model,
        messages=[Msg.user(user_prompt)],
        system_prompt=system_prompt,
        max_tokens=180,
        temperature=0.1,
        reasoning_effort="low",
    )

    async def _run() -> NarrationPlan | None:
        chunks: list[str] = []
        thinking_chunks: list[str] = []
        from deepseek_tui.protocol.responses import StreamTextDelta, StreamThinkingDelta

        async for event in client.stream_chat_completion(request):
            if isinstance(event, StreamTextDelta):
                chunks.append(event.text)
            elif isinstance(event, StreamThinkingDelta):
                thinking_chunks.append(event.thinking)
        raw_text = "".join(chunks)
        raw_thinking = "".join(thinking_chunks)
        # Try text first; if empty, try thinking content (some models
        # put the JSON response in reasoning tokens)
        source = raw_text.strip() or raw_thinking.strip()
        if not source:
            logger.info("phase_bridge flash returned empty response")
            return None
        plan = _parse_plan_json(source)
        if plan is not None:
            return plan
        # JSON parsing failed — Flash returned natural language instead.
        # Extract a usable narration directly from the raw text.
        logger.info(
            "phase_bridge flash not JSON, extracting from raw=%s",
            (source[:120] + "...") if len(source) > 120 else source,
        )
        return _extract_narration_from_text(source)

    try:
        return await asyncio.wait_for(_run(), timeout=timeout_s)
    except asyncio.TimeoutError:
        logger.info("phase_bridge flash timeout after %.1fs", timeout_s)
        return None
    except Exception as exc:
        logger.info(
            "phase_bridge flash failed: %s: %s",
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
    cfg: ProcessNarrationConfig = config.ui.process_narration
    model = resolve_narration_model(config)
    batch = classify_batch(tool_calls)
    fallback = template_narration(locale=locale, batch=batch, tool_calls=tool_calls)
    if not model:
        logger.info("phase_bridge no flash model; using template fallback")
        return fallback
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
    if plan is not None:
        rendered = render_plan(plan, locale=locale)
        if rendered:
            logger.info("phase_bridge success narration=%s", rendered[:80])
            return rendered
        logger.info(
            "phase_bridge render_plan rejected publish=%s finding=%r next_goal=%r",
            plan.publish,
            plan.finding[:60] if plan.finding else "",
            plan.next_goal[:60] if plan.next_goal else "",
        )
    else:
        logger.info("phase_bridge compute_narration_plan returned None")
    if fallback:
        logger.info(
            "phase_bridge using template fallback locale=%s batch=%s",
            locale,
            batch.value,
        )
    return fallback


def decide_and_prepare(
    *,
    state: TurnNarrationState,
    segment: ReasoningSegment,
    tool_calls: Sequence[ToolCall],
    preface_text: str | None,
    narrated_ids: set[str],
    min_chars: int,
    has_tool_error: bool,
    pending_scheduled: int = 0,
    locale: str = "zh",
    max_published: int = MAX_PUBLISHED_PER_TURN,
) -> tuple[GateDecision, str | None]:
    """Return gate decision and optional immediate display text (preface path).

    When the gate decides to narrate and the model already wrote a usable,
    locale-matching preface for this batch, surface the model's own words
    (``use_preface``) instead of regenerating a competing line via the flash
    model. The mid-turn preface is otherwise discarded by the UI, so this is
    the model's narration finally reaching the user.
    """
    decision = gate_decision(
        state=state,
        segment=segment,
        tool_calls=tool_calls,
        preface_text=preface_text,
        narrated_ids=narrated_ids,
        min_chars=min_chars,
        has_tool_error=has_tool_error,
        pending_scheduled=pending_scheduled,
        locale=locale,
        max_published=max_published,
    )
    if decision == "skip":
        return "skip", None
    preface = locale_preface(preface_text, locale)
    if preface is not None:
        return "use_preface", preface
    return "compute", None
