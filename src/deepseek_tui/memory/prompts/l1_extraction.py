"""L1 extraction prompts — adapted from TencentDB ``l1-extraction.ts``."""

from __future__ import annotations

from typing import Any

EXTRACT_MEMORIES_SYSTEM_PROMPT = """你是专业的"情境切分与记忆提取专家"。
你的任务是分析用户的对话，判断情境切换，并从中提取结构化核心记忆
（仅限 persona、episodic、instruction 三类）。

### 任务二：核心记忆提取（Memory Extraction）
结合背景，从【待提取的新消息】中提取核心信息。宁缺毋滥；记忆必须独立完整。

支持类型：persona | episodic | instruction。每条记忆带 priority 分数 0-100。

### 输出格式（JSON）
返回且仅返回一个合法的 JSON 数组。每项包含 scene_name、message_ids、memories。
memories 每项：content, type, priority, source_message_ids, metadata。

不要输出 Markdown 代码块或解释文字。"""


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

    bg_text = "\n".join(_fmt(m) for m in bg) if bg else "(无)"
    new_text = "\n".join(_fmt(m) for m in new_messages) if new_messages else "(无)"
    return (
        f"【上一个情境】\n{previous_scene_name}\n\n"
        f"【背景消息（仅供理解，勿从中提取）】\n{bg_text}\n\n"
        f"【待提取的新消息】\n{new_text}"
    )
