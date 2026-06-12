"""L1 memory layer — fact extraction and deduplication.

Consolidates native/l1_*.py and prompts/l1_extraction.py.
"""

from __future__ import annotations



# ======================================================================
# From native/l1_extractor.py
# ======================================================================

"""L1 memory extraction via LLM."""


import inspect
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from deepseek_tui.client.base import LLMClient
from deepseek_tui.memory.coordinator import sanitize_memory_text
from deepseek_tui.memory.store import MemoryStore
from deepseek_tui.protocol.messages import Message
from deepseek_tui.protocol.messages import MessageRequest
from deepseek_tui.protocol.responses import StreamTextDelta

logger = logging.getLogger(__name__)

_JSON_ARRAY_RE = re.compile(r"\[[\s\S]*\]")
_SYMBOL_ONLY_RE = re.compile(r"^[^\w\s\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]{1,5}$")
_QUESTION_ONLY_RE = re.compile(r"^[?？]+$")


def _parse_extraction_response(raw: str) -> list[dict[str, Any]]:
    text = raw.strip()
    if not text:
        return []
    match = _JSON_ARRAY_RE.search(text)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, dict)]


def _priority_to_confidence(priority: Any) -> float:
    try:
        p = float(priority)
    except (TypeError, ValueError):
        return 0.0
    if p < 0:
        return 1.0
    return max(0.0, min(1.0, p / 100.0))


def should_extract_l1(text: str) -> bool:
    """Strict L1 quality gate; L0 remains the permissive evidence archive."""
    cleaned = sanitize_memory_text(text)
    if not cleaned:
        return False
    if cleaned.startswith("/"):
        return False
    if _SYMBOL_ONLY_RE.match(cleaned):
        return False
    if _QUESTION_ONLY_RE.match(cleaned):
        return False
    return True


def _clean_message_for_l1(message: dict[str, Any]) -> dict[str, Any] | None:
    content = sanitize_memory_text(str(message.get("content", "") or ""))
    if not should_extract_l1(content):
        return None
    cleaned = dict(message)
    cleaned["content"] = content
    return cleaned


@dataclass(slots=True)
class ExtractionResult:
    inserted: int = 0
    scenes: list[dict[str, Any]] | None = None
    committed_scenes: list[dict[str, Any]] | None = None
    last_scene_name: str | None = None


class L1Extractor:
    def __init__(
        self,
        client: LLMClient,
        store: MemoryStore,
        *,
        model: str,
        confidence_min: float,
        max_per_session: int,
        insert_memory: Callable[..., Awaitable[str | None]] | None = None,
    ) -> None:
        self._client = client
        self._store = store
        self._model = model
        self._confidence_min = confidence_min
        self._max_per_session = max_per_session
        self._insert_memory = insert_memory

    async def extract_and_store(
        self,
        thread_id: str,
        new_messages: list[dict[str, Any]],
        *,
        workspace: str,
        background_messages: list[dict[str, Any]] | None = None,
        previous_scene_name: str = "无",
    ) -> ExtractionResult:
        if not new_messages:
            return ExtractionResult()

        qualified_messages = [
            cleaned
            for msg in new_messages
            if (cleaned := _clean_message_for_l1(msg)) is not None
        ]
        if not qualified_messages:
            logger.debug("l1_extraction_skipped_quality_gate thread_id=%s", thread_id)
            return ExtractionResult()
        qualified_background = [
            cleaned
            for msg in (background_messages or [])
            if (cleaned := _clean_message_for_l1(msg)) is not None
        ]

        user_prompt = format_extraction_user_prompt(
            qualified_messages,
            background_messages=qualified_background,
            previous_scene_name=previous_scene_name,
        )
        request = MessageRequest(
            model=self._model,
            messages=[Message.user(user_prompt)],
            system_prompt=EXTRACT_MEMORIES_SYSTEM_PROMPT,
            max_tokens=2048,
        )
        chunks: list[str] = []
        try:
            stream = self._client.stream_with_retry(request)
            if not hasattr(stream, "__aiter__"):
                if inspect.isawaitable(stream):
                    await stream
                return ExtractionResult()
            async for event in stream:
                if isinstance(event, StreamTextDelta):
                    chunks.append(event.text)
        except Exception:
            logger.exception("l1_extraction_llm_failed thread_id=%s", thread_id)
            return ExtractionResult()

        scenes = _parse_extraction_response("".join(chunks))
        scene_names: list[str] = []
        pending: list[PendingMemory] = []
        for scene in scenes:
            scene_name = str(scene.get("scene_name", "") or "").strip()
            if scene_name:
                scene_names.append(scene_name)
            memories = scene.get("memories") or []
            if not isinstance(memories, list):
                continue
            for mem in memories:
                if not isinstance(mem, dict):
                    continue
                content = str(mem.get("content", "") or "").strip()
                mem_type = str(mem.get("type", "episodic") or "episodic")
                if mem_type not in ("persona", "episodic", "instruction"):
                    mem_type = "episodic"
                raw_priority = mem.get("priority")
                confidence = _priority_to_confidence(raw_priority)
                if confidence < self._confidence_min:
                    continue
                try:
                    priority = int(float(raw_priority))
                except (TypeError, ValueError):
                    priority = int(round(confidence * 100))
                source_ids_raw = mem.get("source_message_ids") or []
                source_message_ids = (
                    [str(x) for x in source_ids_raw]
                    if isinstance(source_ids_raw, list)
                    else []
                )
                metadata_raw = mem.get("metadata") or {}
                metadata = metadata_raw if isinstance(metadata_raw, dict) else {}
                timestamps: list[str] = []
                for key in ("activity_start_time", "activity_end_time"):
                    value = metadata.get(key)
                    if value:
                        timestamps.append(str(value))
                pending.append(
                    PendingMemory(
                        record_id=f"new_{len(pending)}",
                        content=content,
                        type=mem_type,
                        priority=priority,
                        scene_name=scene_name,
                        source_message_ids=source_message_ids,
                        metadata=metadata,
                        timestamps=timestamps,
                        confidence=confidence,
                    )
                )
                if len(pending) >= self._max_per_session:
                    break
            if len(pending) >= self._max_per_session:
                break

        decisions = await batch_dedup(
            self._client,
            model=self._model,
            store=self._store,
            memories=pending,
            workspace=workspace,
        )
        inserted = 0
        committed_scene_names: set[str] = set()
        for memory in pending:
            decision = decisions.get(memory.record_id)
            if decision and decision.action == "skip":
                continue
            final_content = (
                decision.merged_content
                if decision and decision.action in ("update", "merge") and decision.merged_content
                else memory.content
            )
            final_type = (
                decision.merged_type
                if decision and decision.action in ("update", "merge") and decision.merged_type
                else memory.type
            )
            final_priority = (
                decision.merged_priority
                if decision and decision.action in ("update", "merge")
                and decision.merged_priority is not None
                else memory.priority
            )
            final_timestamps = (
                decision.merged_timestamps
                if decision and decision.action in ("update", "merge")
                and decision.merged_timestamps is not None
                else memory.timestamps
            )
            action = decision.action if decision else "store"
            target_ids = decision.target_ids if decision else []
            if self._insert_memory is not None:
                mem_id = await self._insert_memory(
                    content=final_content,
                    mem_type=final_type,
                    workspace=workspace,
                    thread_id=thread_id,
                    confidence=_priority_to_confidence(final_priority),
                    priority=final_priority,
                    scene_name=memory.scene_name,
                    source_message_ids=memory.source_message_ids,
                    metadata=memory.metadata,
                    timestamps=final_timestamps,
                    session_key=thread_id,
                    session_id="",
                    action=action,
                    target_ids=target_ids,
                )
            else:
                if action in ("update", "merge") and target_ids:
                    self._store.delete_memories(target_ids)
                mem_id = self._store.insert_memory(
                    content=final_content,
                    mem_type=final_type,
                    workspace=workspace,
                    thread_id=thread_id,
                    confidence=_priority_to_confidence(final_priority),
                    priority=final_priority,
                    scene_name=memory.scene_name,
                    source_message_ids=memory.source_message_ids,
                    metadata=memory.metadata,
                    timestamps=final_timestamps,
                    session_key=thread_id,
                    session_id="",
                    allow_duplicate=action in ("update", "merge"),
                )
            if mem_id:
                inserted += 1
                if memory.scene_name:
                    committed_scene_names.add(memory.scene_name)
        committed = [
            s for s in scenes
            if str(s.get("scene_name", "") or "").strip() in committed_scene_names
        ] if committed_scene_names else None
        return ExtractionResult(
            inserted=inserted,
            scenes=scenes,
            committed_scenes=committed,
            last_scene_name=scene_names[-1] if scene_names else None,
        )


# ======================================================================
# From native/l1_dedup.py
# ======================================================================

"""L1 batch conflict detection for TencentDB-style memory decisions."""
# ruff: noqa: E501


import inspect
import json
import re
from dataclasses import dataclass
from typing import Any

from deepseek_tui.client.base import LLMClient
from deepseek_tui.memory.store import MemoryRow, MemoryStore
from deepseek_tui.protocol.messages import Message
from deepseek_tui.protocol.messages import MessageRequest
from deepseek_tui.protocol.responses import StreamTextDelta

CONFLICT_DETECTION_SYSTEM_PROMPT = """你是记忆冲突检测器。批量比较多条【新记忆】与【统一候选记忆池】中的已有记忆，逐条决定如何处理。

## 核心规则
- 不同 type（persona / episodic / instruction）的记忆如果语义上描述同一事实/事件，可以合并。
- 一条新记忆可以同时替换/合并候选池中的多条已有记忆，通过 target_ids 数组指定。
- merge/update 时必须给出 merged_content、merged_type、merged_priority、merged_timestamps。

## 动作
- store：视为新信息，新增当前记忆。
- skip：已有记忆更好，新记忆无增量或更模糊，忽略当前记忆。
- update：同一事实/事件，新记忆更具体、更晚或纠错，以新记忆为主覆盖旧记忆。
- merge：同一事实或同一演化过程，多条记忆互补，合并成更完整记忆。

严格输出 JSON 数组，每个元素对应一条新记忆：
[
  {
    "record_id": "新记忆 record_id",
    "action": "store|update|skip|merge",
    "target_ids": ["旧记忆 id"],
    "merged_content": "merge/update 后的最终文本",
    "merged_type": "persona|episodic|instruction",
    "merged_priority": 85,
    "merged_timestamps": ["ISO time"]
  }
]"""

_JSON_ARRAY_RE = re.compile(r"\[[\s\S]*\]")
_ACTIONS = {"store", "update", "merge", "skip"}
_TYPES = {"persona", "episodic", "instruction"}


@dataclass(slots=True)
class PendingMemory:
    record_id: str
    content: str
    type: str
    priority: int
    scene_name: str
    source_message_ids: list[str]
    metadata: dict[str, Any]
    timestamps: list[str]
    confidence: float


@dataclass(slots=True)
class DedupDecision:
    record_id: str
    action: str = "store"
    target_ids: list[str] | None = None
    merged_content: str | None = None
    merged_type: str | None = None
    merged_priority: int | None = None
    merged_timestamps: list[str] | None = None


@dataclass(slots=True)
class CandidateMatch:
    new_memory: PendingMemory
    candidates: list[MemoryRow]


def find_candidate_matches(
    store: MemoryStore,
    memories: list[PendingMemory],
    *,
    workspace: str | None,
    top_k: int = 5,
) -> list[CandidateMatch]:
    matches: list[CandidateMatch] = []
    for memory in memories:
        hits = store.search_memories(
            memory.content,
            workspace=workspace,
            limit=top_k,
            score_threshold=0.0,
        )
        matches.append(CandidateMatch(memory, [row for row, _ in hits]))
    return matches


def format_batch_conflict_prompt(matches: list[CandidateMatch]) -> str:
    pool: dict[str, MemoryRow] = {}
    related: dict[str, list[str]] = {}
    for match in matches:
        ids: list[str] = []
        for candidate in match.candidates:
            pool[candidate.id] = candidate
            ids.append(candidate.id)
        related[match.new_memory.record_id] = ids

    pool_payload = [
        {
            "record_id": row.id,
            "content": row.content,
            "type": row.type,
            "priority": row.priority,
            "scene_name": row.scene_name,
            "timestamps": row.timestamps or [],
        }
        for row in pool.values()
    ]
    new_payload = [
        {
            "record_id": match.new_memory.record_id,
            "content": match.new_memory.content,
            "type": match.new_memory.type,
            "priority": match.new_memory.priority,
            "scene_name": match.new_memory.scene_name,
            "related_candidate_ids": related.get(match.new_memory.record_id, []),
        }
        for match in matches
    ]
    return (
        "## 统一候选记忆池\n"
        f"{json.dumps(pool_payload, ensure_ascii=False, indent=2)}\n\n"
        "## 待判断的新记忆\n"
        f"{json.dumps(new_payload, ensure_ascii=False, indent=2)}\n\n"
        "请逐条判断并输出决策 JSON 数组。候选为空的新记忆直接 action=store。"
    )


def _parse_decisions(raw: str, valid_ids: set[str]) -> dict[str, DedupDecision]:
    match = _JSON_ARRAY_RE.search(raw.strip())
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, list):
        return {}
    out: dict[str, DedupDecision] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        record_id = str(item.get("record_id", "") or "")
        if record_id not in valid_ids:
            continue
        action = str(item.get("action", "store") or "store")
        if action not in _ACTIONS:
            action = "store"
        target_raw = item.get("target_ids") or []
        target_ids = [str(x) for x in target_raw] if isinstance(target_raw, list) else []
        merged_type = item.get("merged_type")
        if merged_type is not None and str(merged_type) not in _TYPES:
            merged_type = None
        priority_raw = item.get("merged_priority")
        try:
            merged_priority = int(float(priority_raw)) if priority_raw is not None else None
        except (TypeError, ValueError):
            merged_priority = None
        timestamps_raw = item.get("merged_timestamps") or []
        merged_timestamps = (
            [str(x) for x in timestamps_raw] if isinstance(timestamps_raw, list) else None
        )
        out[record_id] = DedupDecision(
            record_id=record_id,
            action=action,
            target_ids=target_ids,
            merged_content=str(item.get("merged_content", "") or "") or None,
            merged_type=str(merged_type) if merged_type is not None else None,
            merged_priority=merged_priority,
            merged_timestamps=merged_timestamps,
        )
    return out


async def batch_dedup(
    client: LLMClient,
    *,
    model: str,
    store: MemoryStore,
    memories: list[PendingMemory],
    workspace: str | None,
    top_k: int = 5,
) -> dict[str, DedupDecision]:
    if not memories:
        return {}
    matches = find_candidate_matches(store, memories, workspace=workspace, top_k=top_k)
    if not any(match.candidates for match in matches):
        return {m.record_id: DedupDecision(record_id=m.record_id) for m in memories}

    request = MessageRequest(
        model=model,
        messages=[Message.user(format_batch_conflict_prompt(matches))],
        system_prompt=CONFLICT_DETECTION_SYSTEM_PROMPT,
        max_tokens=2048,
    )
    chunks: list[str] = []
    try:
        stream = client.stream_with_retry(request)
        if not hasattr(stream, "__aiter__"):
            if inspect.isawaitable(stream):
                await stream
            return {m.record_id: DedupDecision(record_id=m.record_id) for m in memories}
        async for event in stream:
            if isinstance(event, StreamTextDelta):
                chunks.append(event.text)
    except Exception:
        return {m.record_id: DedupDecision(record_id=m.record_id) for m in memories}

    parsed = _parse_decisions("".join(chunks), {m.record_id for m in memories})
    return {
        m.record_id: parsed.get(m.record_id, DedupDecision(record_id=m.record_id))
        for m in memories
    }


# ======================================================================
# From prompts/l1_extraction.py
# ======================================================================

"""L1 extraction prompts — adapted from TencentDB ``l1-extraction.ts``."""
# ruff: noqa: E501


from typing import Any

EXTRACT_MEMORIES_SYSTEM_PROMPT = """你是专业的"情境切分与记忆提取专家"。
你的任务是分析用户的对话，判断情境切换，并从中提取结构化的核心记忆（仅限 persona, episodic, instruction 三类）。

### 任务一：情境切分（Scene Segmentation）
分析【待提取的新消息】，结合【上一个情境】，判断并输出当前对话的情境。
- 继承：无明显切换，沿用上一个情境。
- 切换条件：用户发出明确指令（如"换话题"）、意图转变、或提出独立新目标。
- 一段对话可能只有一个情境，也可能有多个情境（话题多次切换时）。
- 命名规则："我（AI）在和xxx（用户身份）做xxx（目标活动）"（中文，30-50字，单句，全局唯一）。

---

### 任务二：核心记忆提取（Memory Extraction）
结合背景和当前情境，仅从【待提取的新消息】中提取核心信息。

【通用提取原则】
1. 宁缺毋滥：过滤琐碎闲聊、临时性指令和一次性操作（如"这次、本单"）；剔除不可靠的边缘信息。
2. 独立完整：记忆必须"跳出当前对话依然成立"，无上下文也能看懂。提取主体必须以"用户（姓名）"或"AI"为核心。
3. 归纳合并：强关联或因果关系的多条消息，必须合并为一条完整记忆，不可碎片化。

【支持提取的三大类型】（必须严格遵守类型规则）

1. 个性化记忆 (type: "persona")
   - 定义：用户的稳定属性、偏好、技能、价值观、习惯（如住所、职业、饮食禁忌）。
   - 提取句式："用户（[姓名]）喜欢/是/擅长..."
   - 打分 (priority)：80-100（健康/禁忌/核心特质）；50-70（一般喜好/技能）；<50（模糊次要，可丢弃）。
   - 触发词：喜欢、习惯、经常、我这个人...

2. 客观事件记忆 (type: "episodic")
   - 定义：客观发生的动作、决定、计划或达成结果。绝不包含纯主观感受。
   - 提取句式："用户（[姓名]）在 [最好是精确绝对时间] 于 [地点] [做了某事（可以包含起因、经过、结果）]"。
   - 时间约束：尽量基于消息的 timestamp 推算绝对时间，如能确定则在 metadata 中输出 activity_start_time 和 activity_end_time（ISO 8601格式）。无法确定时可省略。
   - 打分 (priority)：80-100（重要事件/计划）；60-70（一般完整活动）；<60（琐碎事项，直接丢弃）。

3. 全局指令记忆 (type: "instruction")
   - 定义：用户对 AI 提出的长期行为规则、格式偏好、语气控制。
   - 提取句式："用户要求/希望 AI 以后回答时..."
   - 触发词：以后都、从现在开始、记住、必须。
   - 打分 (priority)：-1（极其严格的全局死命令）；90-100（核心行为规则）；70-80（重要要求）；<70（临时要求，直接丢弃）。

---

### 不应该提取的内容
- 琐碎闲聊、问候；临时性的纯工具性请求（如"这次帮我翻译一下"）
- 一次性操作指令（如"这次、本单"相关）
- 重复的内容；AI助手自身的行为或输出
- 不属于以上3类的信息
- 纯主观感受（不带客观事件的情绪表达）

---

### 任务三：输出格式规范（JSON）
返回且仅返回一个合法的 JSON 数组。数组的每一项是一个情境，包含该情境的消息范围和抽取到的记忆：

[
  {
    "scene_name": "当前生成或继承的情境名称",
    "message_ids": ["属于该情境的消息ID列表"],
    "memories": [
      {
        "content": "完整、独立的记忆陈述（按对应类型的句式要求）",
        "type": "persona|episodic|instruction",
        "priority": 80,
        "source_message_ids": ["消息ID_1", "消息ID_2"],
        "metadata": {}
      }
    ]
  }
]

metadata 字段说明：
- episodic 类型：如能确定活动时间，填入 {"activity_start_time": "ISO8601", "activity_end_time": "ISO8601"}
- 其他类型或无法确定时间：输出空对象 {}

如果整段对话无有意义的记忆，也要输出情境分割结果，memories 为空数组。

请严格按上述 JSON 数组格式输出，不要输出任何额外的 Markdown 代码块修饰符（如 ```json）或解释文本。"""


def format_extraction_user_prompt(
    new_messages: list[dict[str, Any]],
    *,
    background_messages: list[dict[str, Any]] | None = None,
    previous_scene_name: str = "无",
) -> str:
    bg = background_messages or []

    def _fmt(m: dict[str, Any]) -> str:
        mid = m.get("id", "")
        role = m.get("role", "user")
        ts = m.get("timestamp", "")
        content = m.get("content", "")
        return f"[{mid}] [{role}] [{ts}]: {content}"

    bg_text = "\n\n".join(_fmt(m) for m in bg) if bg else "无"
    new_text = "\n\n".join(_fmt(m) for m in new_messages) if new_messages else "无"
    return f"""【上一个情境】：{previous_scene_name}

【背景对话】（仅供理解上下文推断关系/时间，严禁从中提取记忆）：
{bg_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【待提取的新消息】（务必结合 timestamp 推算时间，只从这里提取记忆！）：
{new_text}"""
