"""L3 memory layer — persona/relationship extraction.

Consolidates native/l3_persona.py and persona_trigger.py.
L3 persona — aggregate persona-type L1 rows into persona.md.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from typing import Any

from deepseek_tui.memory.coordinator import escape_memory_xml_tags
from deepseek_tui.memory.pipeline import run_memory_subagent_loop
from deepseek_tui.memory.store import BackupManager
from deepseek_tui.memory.store import MemoryStore
from deepseek_tui.protocol.messages import Message
from deepseek_tui.protocol.messages import MessageRequest
from deepseek_tui.protocol.responses import StreamTextDelta
from deepseek_tui.tools.registry import ToolCapability, ToolError, ToolResult, ToolSpec
from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.tools.registry import ToolRegistry

PERSONA_SYNTHESIS_SYSTEM_PROMPT = """你是用户画像生成器。根据结构化 persona 记忆，
生成一份稳定、可注入 system prompt 的用户画像。

要求：
- 只总结长期稳定的偏好、习惯、技能、身份、工作方式和对 AI 的长期要求。
- 不要写临时任务进展，不要编造未出现的信息。
- 用 Markdown 输出，标题使用 "# Persona"。
- 内容要简洁、分层，适合未来对话直接注入。"""

PERSONA_TOOL_AGENT_SYSTEM_PROMPT = """# Persona Architect

你是 L3 用户画像生成 agent。当前工作目录已经被限制为 persona 文件所在目录。

可用工具：
- write(path, content)：整体写入 persona 文件。
- edit(path, edits)：局部替换 persona 文件。

规则：
- 只能操作提示中指定的 persona 文件名。
- 首次生成或大幅重写时使用 write。
- 局部增量更新时使用 edit。
- 只写最终 persona Markdown，不要写分析过程。
- persona 内容必须来自提供的 L1 persona 记忆，不要编造。
- 内容控制在 2000 字符内。
"""


def _workspace_key(workspace: str) -> str:
    return hashlib.sha256(workspace.encode("utf-8")).hexdigest()[:16]


def persona_path_for_workspace(persona_path: Path, *, workspace: str | None) -> Path:
    if not workspace:
        return persona_path
    return persona_path.parent / "persona" / f"{_workspace_key(workspace)}.md"


def persona_paths_for_workspace(
    persona_path: Path, *, workspace: str | None
) -> list[Path]:
    if not workspace:
        return [persona_path]
    return [persona_path_for_workspace(persona_path, workspace=workspace), persona_path]


def refresh_persona_from_store(
    store: MemoryStore,
    persona_path: Path,
    *,
    workspace: str | None = None,
    limit: int = 40,
) -> bool:
    """Rebuild ``persona.md`` from L1 persona memories. Returns True if written."""
    rows = store.list_memories_by_type("persona", workspace=workspace, limit=limit)
    if not rows:
        return False
    target_path = persona_path_for_workspace(persona_path, workspace=workspace)
    lines = ["# Persona (auto-generated from L1 memories)", ""]
    for row in rows:
        lines.append(f"- {escape_memory_xml_tags(row.content)}")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    BackupManager(persona_path.parent).backup_file(target_path, "persona")
    target_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


def _persona_rows_payload(
    store: MemoryStore, *, workspace: str | None, limit: int
) -> list[dict[str, Any]]:
    rows = store.list_memories_by_type("persona", workspace=workspace, limit=limit)
    return [
        {
            "id": row.id,
            "content": row.content,
            "priority": row.priority,
            "scene_name": row.scene_name,
            "timestamps": row.timestamps or [],
        }
        for row in rows
    ]


async def refresh_persona_with_llm(
    client: Any,
    store: MemoryStore,
    persona_path: Path,
    *,
    model: str,
    workspace: str | None = None,
    limit: int = 40,
    enabled: bool = True,
    scene_summary: str = "",
) -> bool:
    """Generate L3 persona with an LLM, falling back to deterministic aggregation."""
    payload = _persona_rows_payload(store, workspace=workspace, limit=limit)
    if not payload:
        return False
    if not enabled:
        return refresh_persona_from_store(
            store,
            persona_path,
            workspace=workspace,
            limit=limit,
        )

    target_path = persona_path_for_workspace(persona_path, workspace=workspace)
    existing = ""
    if target_path.is_file():
        try:
            existing = target_path.read_text(encoding="utf-8").strip()
        except OSError:
            existing = ""
    scene_section = (
        f"## 当前 L2 场景概览\n{scene_summary}\n\n"
        if scene_summary else ""
    )
    prompt = (
        "## 已有 Persona\n"
        f"{existing or '无'}\n\n"
        f"{scene_section}"
        "## persona 类型 L1 记忆\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        f"## 目标文件\n{target_path.name}\n\n"
        "请生成更新后的 persona.md 内容。"
    )
    if await _refresh_persona_with_tool_agent(
        client,
        model=model,
        target_path=target_path,
        prompt=prompt,
    ):
        return True
    request = MessageRequest(
        model=model,
        messages=[Message.user(prompt)],
        system_prompt=PERSONA_SYNTHESIS_SYSTEM_PROMPT,
        max_tokens=2048,
    )
    chunks: list[str] = []
    try:
        stream = client.stream_with_retry(request)
        if not hasattr(stream, "__aiter__"):
            if inspect.isawaitable(stream):
                await stream
            return refresh_persona_from_store(
                store,
                persona_path,
                workspace=workspace,
                limit=limit,
            )
        async for event in stream:
            if isinstance(event, StreamTextDelta):
                chunks.append(event.text)
    except Exception:
        return refresh_persona_from_store(
            store,
            persona_path,
            workspace=workspace,
            limit=limit,
        )
    content = escape_memory_xml_tags("".join(chunks).strip())
    if not content:
        return refresh_persona_from_store(
            store,
            persona_path,
            workspace=workspace,
            limit=limit,
        )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    BackupManager(persona_path.parent).backup_file(target_path, "persona")
    target_path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return True


async def _refresh_persona_with_tool_agent(
    client: Any,
    *,
    model: str,
    target_path: Path,
    prompt: str,
) -> bool:
    registry = ToolRegistry()
    registry.register(_PersonaWriteTool())
    registry.register(_PersonaEditTool())
    context = ToolContext(
        working_directory=target_path.parent,
        timeout_ms=30_000,
        metadata={
            "persona_target": target_path.name,
            "persona_write_count": 0,
        },
    )
    try:
        result = await run_memory_subagent_loop(
            client,
            model=model,
            system_prompt=PERSONA_TOOL_AGENT_SYSTEM_PROMPT,
            user_prompt=prompt,
            registry=registry,
            context=context,
            max_steps=6,
            max_tokens=2048,
        )
    except Exception:
        return False
    if result.tool_calls <= 0:
        return False
    return int(context.metadata.get("persona_write_count", 0) or 0) > 0


class _PersonaPathMixin:
    def _resolve_persona_path(self, input_data: dict[str, object], context: ToolContext) -> Path:
        target = str(context.metadata.get("persona_target", "") or "")
        path_name = str(input_data.get("path", "") or "").strip()
        if not path_name:
            raise ToolError("path is required")
        if path_name != target:
            raise ToolError(f"only {target} may be modified")
        if "/" in path_name or "\\" in path_name or not path_name.endswith(".md"):
            raise ToolError("persona path must be a relative .md filename")
        return context.resolve_path(path_name)


class _PersonaWriteTool(_PersonaPathMixin, ToolSpec):
    def name(self) -> str:
        return "write"

    def description(self) -> str:
        return "Write the complete persona Markdown file."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        path = self._resolve_persona_path(input_data, context)
        content = str(input_data.get("content", "") or "").strip()
        if not content:
            raise ToolError("content is required")
        BackupManager(path.parent).backup_file(path, "persona")
        path.write_text(content.rstrip() + "\n", encoding="utf-8")
        context.metadata["persona_write_count"] = int(
            context.metadata.get("persona_write_count", 0) or 0
        ) + 1
        return ToolResult(success=True, content="ok", metadata={"path": str(path)})


class _PersonaEditTool(_PersonaPathMixin, ToolSpec):
    def name(self) -> str:
        return "edit"

    def description(self) -> str:
        return "Apply exact text replacements to the persona Markdown file."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "edits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "oldText": {"type": "string"},
                            "newText": {"type": "string"},
                        },
                        "required": ["oldText", "newText"],
                    },
                },
            },
            "required": ["path", "edits"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        path = self._resolve_persona_path(input_data, context)
        edits = input_data.get("edits")
        if not isinstance(edits, list) or not edits:
            raise ToolError("edits must be a non-empty list")
        content = path.read_text(encoding="utf-8")
        replacements = 0
        for edit in edits:
            if not isinstance(edit, dict):
                raise ToolError("each edit must be an object")
            old_text = str(edit.get("oldText", "") or "")
            new_text = str(edit.get("newText", "") or "")
            if not old_text:
                raise ToolError("oldText is required")
            count = content.count(old_text)
            if count == 0:
                raise ToolError("oldText not found")
            content = content.replace(old_text, new_text)
            replacements += count
        BackupManager(path.parent).backup_file(path, "persona")
        path.write_text(content, encoding="utf-8")
        context.metadata["persona_write_count"] = int(
            context.metadata.get("persona_write_count", 0) or 0
        ) + 1
        return ToolResult(
            success=True,
            content=f"replaced {replacements} occurrence(s)",
            metadata={"path": str(path), "replacements": replacements},
        )


# Persona generation trigger logic aligned with TencentDB memory.

from dataclasses import dataclass
from pathlib import Path

from deepseek_tui.memory.store import CheckpointManager


@dataclass(slots=True)
class PersonaTriggerResult:
    should: bool
    reason: str = ""


class PersonaTrigger:
    def __init__(
        self,
        data_dir: Path,
        *,
        interval: int,
        workspace: str | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._checkpoint = CheckpointManager(data_dir)
        self._interval = max(1, interval)
        self._workspace = workspace

    def should_generate(self) -> PersonaTriggerResult:
        checkpoint = self._checkpoint.read()
        if checkpoint.request_persona_update:
            reason = checkpoint.persona_update_reason or "Agent requested persona update"
            return PersonaTriggerResult(True, f"主动请求: {reason}")

        if (
            checkpoint.scenes_processed > 0
            and checkpoint.last_persona_at == 0
            and self._has_scene_files()
        ):
            return PersonaTriggerResult(True, "首次冷启动：首次提取完成且有场景文件")

        if (
            checkpoint.last_persona_at > 0
            and self._has_scene_files()
            and not self._has_persona_body()
        ):
            return PersonaTriggerResult(True, "恢复：persona.md 正文丢失或为空，需要重新生成")

        if checkpoint.scenes_processed == 1 and checkpoint.memories_since_last_persona > 0:
            return PersonaTriggerResult(True, "首次 Scene Block 提取完成")

        if checkpoint.memories_since_last_persona >= self._interval:
            return PersonaTriggerResult(
                True,
                (
                    "达到阈值: "
                    f"{checkpoint.memories_since_last_persona} >= {self._interval}"
                ),
            )

        return PersonaTriggerResult(False)

    def _has_scene_files(self) -> bool:
        blocks_dir = self._data_dir / "scene_blocks"
        try:
            return any(path.suffix == ".md" for path in blocks_dir.iterdir())
        except OSError:
            return False

    def _has_persona_body(self) -> bool:
        persona_path = persona_path_for_workspace(
            self._data_dir / "persona.md",
            workspace=self._workspace,
        )
        try:
            raw = persona_path.read_text(encoding="utf-8")
        except OSError:
            return False
        body = _strip_scene_navigation(raw).strip()
        return bool(body)


def _strip_scene_navigation(raw: str) -> str:
    marker = "## Scene navigation"
    idx = raw.find(marker)
    if idx >= 0:
        return raw[:idx]
    return raw
