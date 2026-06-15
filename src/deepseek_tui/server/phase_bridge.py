"""Phase-bridge narration — stage summaries after reasoning → tools."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Literal, Sequence

from deepseek_tui.config.providers import PROVIDER_DEFAULTS
from deepseek_tui.engine.orchestrator import _summarize_call_args
from deepseek_tui.protocol.responses import ToolCall

if TYPE_CHECKING:
    from deepseek_tui.client.base import LLMClient
    from deepseek_tui.config.models import Config, ProcessNarrationConfig

logger = logging.getLogger(__name__)

PHASE_BRIDGE_METADATA_KEY = "phase_bridge"
PHASE_BRIDGE_AFTER_REASONING_KEY = "after_reasoning_id"

MAX_PUBLISHED_PER_TURN = 12
_TOOL_NAME_RE = re.compile(
    r"\b(read_file|list_dir|grep_files?|search_files?|write_file|apply_patch|"
    r"exec_shell|run_terminal|glob_file_search|codebase_search)\b",
    re.I,
)
_MUTATE_TOOLS = frozenset(
    {
        "write_file",
        "apply_patch",
        "edit_file",
        "search_replace",
        "exec_shell",
        "exec_shell_wait",
        "exec_shell_interact",
        "run_terminal_cmd",
    }
)
_SEARCH_TOOLS = frozenset({"grep_files", "grep", "search_files", "glob_file_search", "codebase_search"})
_READ_TOOLS = frozenset({"read_file", "read"})
_DIR_TOOLS = frozenset({"list_dir", "list_directory"})


class BatchKind(str, Enum):
    EXPLORE_DIR = "explore_dir"
    EXPLORE_READ = "explore_read"
    SEARCH = "search"
    INSPECT = "inspect"
    MUTATE = "mutate"
    MIXED = "mixed"


class Phase(str, Enum):
    EXPLORE = "explore"
    LOCATE = "locate"
    CHANGE = "change"
    VERIFY = "verify"
    RECOVER = "recover"


GateDecision = Literal["skip", "use_preface", "compute"]
NarrationLocale = Literal["zh", "en"]

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")
_LATIN_RE = re.compile(r"[A-Za-z]")


def _script_counts(text: str) -> tuple[int, int]:
    cjk = len(_CJK_RE.findall(text))
    latin = len(_LATIN_RE.findall(text))
    return cjk, latin


def resolve_narration_locale(user_text: str, *, config_locale: str = "auto") -> NarrationLocale:
    """Resolve bridge language from user input, with config fallback."""
    cleaned = user_text.strip()
    cjk, latin = _script_counts(cleaned)
    total = cjk + latin
    if total >= 4:
        if cjk > 0 and cjk / total >= 0.15:
            return "zh"
        if latin > 0:
            return "en"
    if config_locale in {"zh", "en"}:
        return config_locale  # type: ignore[return-value]
    return "zh"


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


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)].rstrip() + "…"


def _normalize_fingerprint(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def contains_tool_name(text: str) -> bool:
    return bool(_TOOL_NAME_RE.search(text))


def usable_preface(text: str | None) -> str | None:
    if not text or not text.strip():
        return None
    cleaned = text.strip()
    if contains_tool_name(cleaned):
        return None
    if len(cleaned) < 8:
        return None
    return _truncate(cleaned, 120)


def _tool_path(arguments: dict[str, object] | None) -> str | None:
    if not arguments:
        return None
    for key in ("path", "file_path", "target_directory", "directory", "dir"):
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def classify_batch(tool_calls: Sequence[ToolCall]) -> BatchKind:
    if not tool_calls:
        return BatchKind.MIXED
    names = [tc.name.lower() for tc in tool_calls]
    if any(name in _MUTATE_TOOLS for name in names):
        return BatchKind.MUTATE
    read_count = sum(1 for name in names if name in _READ_TOOLS)
    dir_count = sum(1 for name in names if name in _DIR_TOOLS)
    search_count = sum(1 for name in names if name in _SEARCH_TOOLS)
    if read_count >= 2 and read_count == len(tool_calls):
        return BatchKind.EXPLORE_READ
    if dir_count >= 1 and dir_count + read_count == len(tool_calls) and read_count <= 1:
        return BatchKind.EXPLORE_DIR
    if search_count >= 1 and search_count == len(tool_calls):
        return BatchKind.SEARCH
    if len(tool_calls) == 1 and read_count == 1:
        return BatchKind.INSPECT
    return BatchKind.MIXED


def _batch_root(tool_calls: Sequence[ToolCall]) -> str | None:
    for tc in tool_calls:
        path = _tool_path(dict(tc.arguments) if tc.arguments else None)
        if path:
            parts = path.replace("\\", "/").strip("/").split("/")
            return parts[0] if parts else path
    return None


def infer_next_phase(
    current: Phase,
    batch: BatchKind,
    *,
    has_tool_error: bool,
) -> Phase:
    if has_tool_error:
        return Phase.RECOVER
    if batch == BatchKind.MUTATE:
        return Phase.CHANGE
    if batch == BatchKind.INSPECT and current == Phase.EXPLORE:
        return Phase.LOCATE
    if batch == BatchKind.EXPLORE_READ and current == Phase.EXPLORE:
        return Phase.LOCATE
    if current == Phase.CHANGE and batch in {BatchKind.SEARCH, BatchKind.INSPECT}:
        return Phase.VERIFY
    return current


def batch_intent_text(
    batch: BatchKind,
    tool_calls: Sequence[ToolCall],
    *,
    locale: str = "zh",
) -> str:
    if locale == "en":
        if batch == BatchKind.EXPLORE_DIR:
            root = _batch_root(tool_calls) or "project root"
            return f"Survey structure under {root}"
        if batch == BatchKind.EXPLORE_READ:
            paths = [
                p
                for tc in tool_calls
                if (p := _tool_path(dict(tc.arguments) if tc.arguments else None))
            ]
            if paths:
                head = ", ".join(_truncate(p, 40) for p in paths[:2])
                suffix = f" and {len(paths) - 2} more" if len(paths) > 2 else ""
                return f"Read {head}{suffix} in parallel"
            return "Read multiple source files in parallel"
        if batch == BatchKind.SEARCH:
            return "Search the codebase for relevant implementations"
        if batch == BatchKind.INSPECT:
            path = _tool_path(dict(tool_calls[0].arguments) if tool_calls[0].arguments else None)
            return f"Inspect {_truncate(path or 'a key file', 48)}"
        if batch == BatchKind.MUTATE:
            return "Apply changes and prepare verification"
        if batch == BatchKind.MIXED:
            return f"Used {len(tool_calls)} tools to continue analysis"
        return "Continue the current task"

    if batch == BatchKind.EXPLORE_DIR:
        root = _batch_root(tool_calls) or "项目目录"
        return f"浏览 {root} 的结构"
    if batch == BatchKind.EXPLORE_READ:
        paths = [
            p
            for tc in tool_calls
            if (p := _tool_path(dict(tc.arguments) if tc.arguments else None))
        ]
        if paths:
            head = ", ".join(_truncate(p, 40) for p in paths[:2])
            suffix = f" 等 {len(paths)} 个文件" if len(paths) > 2 else ""
            return f"并行查看 {head}{suffix}"
        return "并行阅读多个源文件"
    if batch == BatchKind.SEARCH:
        return "搜索代码以定位相关实现"
    if batch == BatchKind.INSPECT:
        path = _tool_path(dict(tool_calls[0].arguments) if tool_calls[0].arguments else None)
        return f"深入阅读 {_truncate(path or '关键文件', 48)}"
    if batch == BatchKind.MUTATE:
        return "实施修改并准备验证"
    if batch == BatchKind.MIXED:
        return f"调用 {len(tool_calls)} 个工具继续分析"
    return "继续推进当前任务"


def extract_confirmed_facts(recent_tool_results: Sequence[str], *, limit: int = 3) -> tuple[str, ...]:
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


def template_narration(
    *,
    locale: str,
    batch: BatchKind,
    tool_calls: Sequence[ToolCall],
) -> str | None:
    """Localized one-liner when Flash is unavailable."""
    text = batch_intent_text(batch, tool_calls, locale=locale)
    if contains_tool_name(text):
        return None
    return _truncate(text, 120)


def validate_plan(plan: NarrationPlan, *, locale: str = "zh") -> bool:
    combined = f"{plan.finding} {plan.next_goal}"
    # Must have at least some content
    if not plan.finding.strip() and not plan.next_goal.strip():
        return False
    if contains_tool_name(combined):
        return False
    # Ignore publish=false — Flash is overly conservative; if it produced
    # meaningful finding/next_goal content, show it regardless.
    # Ignore locale mismatch — English narration is better than template fallback.
    return True


def render_plan(plan: NarrationPlan, *, locale: str = "zh") -> str | None:
    if not validate_plan(plan, locale=locale):
        return None
    return plan.display_text(locale=locale)


def note_published(state: TurnNarrationState, text: str, *, batch: BatchKind, tool_calls: Sequence[ToolCall]) -> None:
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
        f"{body}\n"
        "返回一个 JSON 对象，字段:\n"
        '{"publish": true|false, "phase": "explore|locate|change|verify|recover", '
        '"finding": "本轮发现了什么（简短中文描述）", '
        '"next_goal": "接下来要做什么（简短中文描述）"}\n'
        "规则:\n"
        "- 有新发现或明确进展时 publish=true\n"
        "- finding 描述已确认的事实或定位结果，如「定位到 workflow 调度入口在 orchestrator.py」\n"
        "- next_goal 描述接下来的动作意图，如「深入分析 round-robin 循环逻辑」\n"
        "- 禁止出现工具函数名(read_file/grep_files等)\n"
        "- finding 和 next_goal 必须用中文"
    )
    system_prompt = (
        "你是一个编程助手的进度播报器。根据思考内容和工具调用判断是否有新进展，"
        "如果有则输出简短中文描述。只返回 JSON，不要其他文字。"
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


def _extract_narration_from_text(raw: str) -> NarrationPlan | None:
    """Extract a usable narration when Flash returns prose instead of JSON.

    Takes the first meaningful sentence (up to 120 chars) as the finding.
    """
    text = raw.strip()
    if not text or len(text) < 10:
        return None
    if contains_tool_name(text):
        return None
    # Take first sentence or first 120 chars
    for sep in ("。", ".", "；", "\n"):
        idx = text.find(sep)
        if 10 < idx < 150:
            text = text[:idx]
            break
    text = _truncate(text, 120)
    if not text or len(text) < 10:
        return None
    return NarrationPlan(
        publish=True,
        phase="explore",
        finding=text,
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
        reasoning_effort="none",
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
    """Return gate decision and optional immediate display text (preface path)."""
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
    if decision == "use_preface":
        return "compute", None
    return decision, None
