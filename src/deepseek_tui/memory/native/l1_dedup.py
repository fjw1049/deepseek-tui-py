"""L1 batch conflict detection for TencentDB-style memory decisions."""
# ruff: noqa: E501

from __future__ import annotations

import inspect
import json
import re
from dataclasses import dataclass
from typing import Any

from deepseek_tui.client.base import LLMClient
from deepseek_tui.memory.native.store import MemoryRow, MemoryStore
from deepseek_tui.protocol.messages import Message
from deepseek_tui.protocol.requests import MessageRequest
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
