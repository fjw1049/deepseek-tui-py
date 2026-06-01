"""L2 scene blocks — markdown files + JSON index (lite TencentDB parity)."""

from __future__ import annotations

import hashlib
import inspect
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deepseek_tui.client.base import LLMClient
from deepseek_tui.memory.native.agent_loop import run_memory_subagent_loop
from deepseek_tui.memory.native.backup import BackupManager
from deepseek_tui.protocol.messages import Message
from deepseek_tui.protocol.requests import MessageRequest
from deepseek_tui.protocol.responses import StreamTextDelta
from deepseek_tui.tools.base import ToolCapability, ToolError, ToolResult, ToolSpec
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.registry import ToolRegistry

SCENE_EXTRACTION_SYSTEM_PROMPT = """# Memory Consolidation Architect

你是记忆整合架构师，负责把 L1 原子记忆整合为 L2 场景叙事文件。

核心规则：
- 默认 UPDATE 现有场景，而不是 CREATE。
- 达到场景数量上限时，必须先 MERGE 相似场景，再处理新记忆。
- 每次批处理最多新增 1 个场景。
- 删除场景只能输出 delete_scene 操作，宿主会写入 [DELETED] 并清理。
- 重要人格变化可以输出 request_persona_update。
- 场景文件正文必须是 Markdown，并建议包含 META 块：created、updated、summary、heat。

严格输出 JSON 对象，不要输出解释文字：
{
  "operations": [
    {"action": "write_scene", "filename": "场景.md", "content": "完整 markdown"},
    {"action": "delete_scene", "filename": "旧场景.md"},
    {"action": "request_persona_update", "reason": "原因"}
  ]
}
"""

SCENE_TOOL_AGENT_SYSTEM_PROMPT = """# Memory Consolidation Architect

你是 L2 场景文件整理 agent。当前工作目录已经被限制为 scene_blocks/。

可用工具：
- read(path)：读取已有场景 Markdown。
- write(path, content)：创建、整体重写或用 [DELETED] 软删除场景 Markdown。
- edit(path, edits)：局部替换，edits 为 [{"oldText": "...", "newText": "..."}]。

规则：
- 所有 path 必须是相对文件名，且必须是 .md。
- 只能读取用户消息中列出的已有场景文件。
- 默认 UPDATE 现有场景，而不是 CREATE。
- 达到场景数量上限时，必须先 MERGE 相似场景。
- 每次批处理最多新增 1 个场景。
- 删除场景只能 write(path, "[DELETED]")。
- 禁止创建 REPORT、SUMMARY、ARCHIVE、BATCH、CONSOLIDATION 等报告类文件。
- 完成文件操作后，用简短文本总结。若需要触发 persona 更新，输出：
[PERSONA_UPDATE_REQUEST]
reason: 具体原因
[/PERSONA_UPDATE_REQUEST]
"""

_JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\}")
_META_RE = re.compile(r"-----META-START-----(.*?)-----META-END-----", re.S)
_PERSONA_BLOCK_RE = re.compile(
    r"\[PERSONA_UPDATE_REQUEST\]\s*(?:reason:\s*)?(.+?)\s*\[/PERSONA_UPDATE_REQUEST\]",
    re.S,
)
_PERSONA_INLINE_RE = re.compile(r"PERSONA_UPDATE_REQUEST:\s*(.+?)(?:\n|$)")
_REPORT_PREFIX_RE = re.compile(
    r"^(?:BATCH|REPORT|CONSOLIDATION|INTEGRATION|ARCHIVE|SUMMARY)[_-]",
    re.I,
)

def _safe_filename(name: str) -> str:
    slug = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", name.strip())[:80]
    return slug or "scene"


def _workspace_key(workspace: str) -> str:
    return hashlib.sha256(workspace.encode("utf-8")).hexdigest()[:12]


@dataclass(slots=True)
class SceneIndexEntry:
    name: str
    filename: str
    workspace: str | None
    updated_at: int
    summary: str = ""
    heat: int = 0


@dataclass(slots=True)
class SceneExtractionResult:
    scenes_processed: int = 0
    latest_cursor: str = ""
    persona_update_reason: str = ""
    used_fallback: bool = False


class SceneStore:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._blocks_dir = data_dir / "scene_blocks"
        self._index_path = data_dir / ".metadata" / "scene_index.json"
        self._blocks_dir.mkdir(parents=True, exist_ok=True)
        self._index_path.parent.mkdir(parents=True, exist_ok=True)

    def record_scenes(
        self,
        scenes: list[dict[str, Any]],
        *,
        workspace: str,
    ) -> int:
        """Upsert scene blocks from L1 extraction JSON."""
        index = self._load_index()
        written = 0
        now = int(time.time() * 1000)
        for scene in scenes:
            name = str(scene.get("scene_name", "") or "").strip()
            if not name:
                continue
            filename = f"{_workspace_key(workspace)}_{_safe_filename(name)}.md"
            path = self._blocks_dir / filename
            memories = scene.get("memories") or []
            lines = [f"# {name}", "", f"workspace: {workspace}", ""]
            if isinstance(memories, list):
                for mem in memories:
                    if isinstance(mem, dict) and mem.get("content"):
                        lines.append(f"- {mem['content']}")
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            entry = SceneIndexEntry(
                name=name,
                filename=filename,
                workspace=workspace,
                updated_at=now,
                summary=_summarize_scene_memories(memories),
                heat=1,
            )
            index = [e for e in index if e.filename != filename]
            index.append(entry)
            written += 1
        if written:
            self._save_index(index)
        return written

    def navigation_markdown(self, *, workspace: str | None, limit: int = 8) -> str:
        index = self._load_index()
        if workspace:
            index = [e for e in index if e.workspace == workspace or e.workspace is None]
        if not index:
            return ""
        index.sort(key=lambda e: e.updated_at, reverse=True)
        lines = ["## Scene navigation (L2)", ""]
        for entry in index[:limit]:
            path = self._blocks_dir / entry.filename
            lines.append(f"### {entry.name}")
            lines.append(f"Path: {path.resolve()}")
            lines.append("")
        return "\n".join(lines).strip()

    async def extract_with_llm(
        self,
        client: LLMClient,
        *,
        model: str,
        scenes: list[dict[str, Any]],
        workspace: str,
        max_scenes: int = 15,
    ) -> SceneExtractionResult:
        """LLM-guided L2 consolidation using host-executed structured ops."""
        if not scenes:
            return SceneExtractionResult()
        prompt = self._build_extraction_prompt(
            scenes,
            workspace=workspace,
            max_scenes=max_scenes,
        )
        BackupManager(self._data_dir).backup_directory(self._blocks_dir, "scene_blocks")
        tool_result = await self._extract_with_tool_agent(
            client,
            model=model,
            prompt=prompt,
            workspace=workspace,
        )
        if tool_result is not None:
            return SceneExtractionResult(
                scenes_processed=tool_result.scenes_processed,
                latest_cursor=_latest_scene_cursor(scenes),
                persona_update_reason=tool_result.persona_update_reason,
            )

        request = MessageRequest(
            model=model,
            messages=[Message.user(prompt)],
            system_prompt=SCENE_EXTRACTION_SYSTEM_PROMPT,
            max_tokens=4096,
        )
        chunks: list[str] = []
        try:
            stream = client.stream_with_retry(request)
            if not hasattr(stream, "__aiter__"):
                if inspect.isawaitable(stream):
                    await stream
                written = self.record_scenes(scenes, workspace=workspace)
                return SceneExtractionResult(
                    scenes_processed=written,
                    latest_cursor=_latest_scene_cursor(scenes),
                    used_fallback=True,
                )
            async for event in stream:
                if isinstance(event, StreamTextDelta):
                    chunks.append(event.text)
        except Exception:
            written = self.record_scenes(scenes, workspace=workspace)
            return SceneExtractionResult(
                scenes_processed=written,
                latest_cursor=_latest_scene_cursor(scenes),
                used_fallback=True,
            )

        operations = _parse_scene_operations("".join(chunks))
        if not operations:
            written = self.record_scenes(scenes, workspace=workspace)
            return SceneExtractionResult(
                scenes_processed=written,
                latest_cursor=_latest_scene_cursor(scenes),
                used_fallback=True,
            )
        processed = 0
        persona_reason = ""
        for op in operations:
            action = str(op.get("action", "") or "")
            if action == "request_persona_update":
                persona_reason = str(op.get("reason", "") or "").strip()
                continue
            filename = str(op.get("filename", "") or "").strip()
            if action == "write_scene":
                content = str(op.get("content", "") or "").strip()
                if self._write_scene_file(filename, content, workspace=workspace):
                    processed += 1
                continue
            if action == "delete_scene":
                if self._delete_scene_file(filename):
                    processed += 1
        self._sync_index_from_files(workspace=workspace)
        return SceneExtractionResult(
            scenes_processed=processed,
            latest_cursor=_latest_scene_cursor(scenes),
            persona_update_reason=persona_reason,
        )

    async def _extract_with_tool_agent(
        self,
        client: LLMClient,
        *,
        model: str,
        prompt: str,
        workspace: str,
    ) -> SceneExtractionResult | None:
        registry = ToolRegistry()
        registry.register(_SceneReadTool())
        registry.register(_SceneWriteTool())
        registry.register(_SceneEditTool())
        allowed = [entry.filename for entry in self._load_index() if entry.workspace == workspace]
        context = ToolContext(
            working_directory=self._blocks_dir,
            timeout_ms=30_000,
            metadata={
                "allowed_scene_files": allowed,
                "scene_write_count": 0,
            },
        )
        try:
            result = await run_memory_subagent_loop(
                client,
                model=model,
                system_prompt=SCENE_TOOL_AGENT_SYSTEM_PROMPT,
                user_prompt=prompt.replace("请输出结构化 JSON 操作。", "请使用工具整理场景文件。"),
                registry=registry,
                context=context,
                max_steps=8,
                max_tokens=4096,
            )
        except Exception:
            return None
        write_count = int(context.metadata.get("scene_write_count", 0) or 0)
        if result.tool_calls <= 0:
            return None
        self._sync_index_from_files(workspace=workspace)
        return SceneExtractionResult(
            scenes_processed=write_count,
            persona_update_reason=_parse_persona_update_signal(result.final_text),
        )

    def _build_extraction_prompt(
        self,
        scenes: list[dict[str, Any]],
        *,
        workspace: str,
        max_scenes: int,
    ) -> str:
        index = self._load_index()
        if workspace:
            index = [e for e in index if e.workspace == workspace]
        summaries = self._scene_summaries(index)
        existing_files = [e.filename for e in index]
        warning = _scene_count_warning(len(index), max_scenes)
        payload = json.dumps(scenes, ensure_ascii=False, indent=2)
        return (
            f"## Workspace\n{workspace}\n\n"
            f"## Max Scenes\n{max_scenes}\n\n"
            f"## Scene Count Warning\n{warning or '无'}\n\n"
            "## Existing Scene Blocks Summary\n"
            f"{summaries or '(无已有场景)'}\n\n"
            "## Existing Scene Files Allowed\n"
            f"{json.dumps(existing_files, ensure_ascii=False)}\n\n"
            "## New L1 Scene Memories\n"
            f"{payload}\n\n"
            "请输出结构化 JSON 操作。"
        )

    def _scene_summaries(self, entries: list[SceneIndexEntry]) -> str:
        lines: list[str] = [f"当前场景总数: {len(entries)}"]
        for entry in entries:
            lines.append(
                f"- {entry.filename}: {entry.summary or entry.name} "
                f"(heat={entry.heat}, updated_at={entry.updated_at})"
            )
        return "\n".join(lines)

    def _safe_scene_path(self, filename: str) -> Path | None:
        if not filename or "/" in filename or "\\" in filename:
            return None
        path = (self._blocks_dir / filename).resolve()
        blocks = self._blocks_dir.resolve()
        if path.parent != blocks or path.suffix != ".md":
            return None
        return path

    def _write_scene_file(self, filename: str, content: str, *, workspace: str) -> bool:
        path = self._safe_scene_path(filename)
        if path is None or not content:
            return False
        if content.strip() == "[DELETED]":
            return self._delete_scene_file(filename)
        path.write_text(content.rstrip() + "\n", encoding="utf-8")
        return True

    def _delete_scene_file(self, filename: str) -> bool:
        path = self._safe_scene_path(filename)
        if path is None:
            return False
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        return True

    def _sync_index_from_files(self, *, workspace: str) -> None:
        now = int(time.time() * 1000)
        existing_index = self._load_index()
        owned_by_other: dict[str, SceneIndexEntry] = {
            e.filename: e for e in existing_index if e.workspace != workspace
        }
        entries: list[SceneIndexEntry] = []
        for path in sorted(self._blocks_dir.glob("*.md")):
            if path.name in owned_by_other:
                continue
            try:
                raw = path.read_text(encoding="utf-8")
            except OSError:
                continue
            if raw.strip() == "[DELETED]":
                try:
                    path.unlink()
                except OSError:
                    pass
                continue
            meta = _parse_scene_meta(raw)
            name = path.stem
            entries.append(
                SceneIndexEntry(
                    name=name,
                    filename=path.name,
                    workspace=workspace,
                    updated_at=now,
                    summary=str(meta.get("summary", "") or name),
                    heat=int(meta.get("heat", 0) or 0),
                )
            )
        self._save_index(list(owned_by_other.values()) + entries)

    def _load_index(self) -> list[SceneIndexEntry]:
        if not self._index_path.is_file():
            return []
        try:
            raw = json.loads(self._index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(raw, list):
            return []
        out: list[SceneIndexEntry] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            out.append(
                SceneIndexEntry(
                    name=str(item.get("name", "")),
                    filename=str(item.get("filename", "")),
                    workspace=item.get("workspace"),
                    updated_at=int(item.get("updated_at", 0)),
                    summary=str(item.get("summary", "") or ""),
                    heat=int(item.get("heat", 0) or 0),
                )
            )
        return out

    def _save_index(self, entries: list[SceneIndexEntry]) -> None:
        payload = [
            {
                "name": e.name,
                "filename": e.filename,
                "workspace": e.workspace,
                "updated_at": e.updated_at,
                "summary": e.summary,
                "heat": e.heat,
            }
            for e in entries
        ]
        self._index_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _parse_scene_operations(raw: str) -> list[dict[str, Any]]:
    match = _JSON_OBJECT_RE.search(raw.strip())
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    ops = data.get("operations") if isinstance(data, dict) else None
    if not isinstance(ops, list):
        return []
    return [op for op in ops if isinstance(op, dict)]


def _parse_scene_meta(raw: str) -> dict[str, Any]:
    match = _META_RE.search(raw)
    if not match:
        return {}
    out: dict[str, Any] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        out[key.strip()] = value.strip()
    return out


def _summarize_scene_memories(memories: object) -> str:
    if not isinstance(memories, list):
        return ""
    parts: list[str] = []
    for mem in memories[:3]:
        if isinstance(mem, dict) and mem.get("content"):
            parts.append(str(mem["content"]))
    return " / ".join(parts)[:160]


def _latest_scene_cursor(scenes: list[dict[str, Any]]) -> str:
    timestamps: list[str] = []
    for scene in scenes:
        memories = scene.get("memories") if isinstance(scene, dict) else None
        if not isinstance(memories, list):
            continue
        for mem in memories:
            if not isinstance(mem, dict):
                continue
            metadata = mem.get("metadata") if isinstance(mem.get("metadata"), dict) else {}
            for key in ("activity_end_time", "activity_start_time"):
                value = metadata.get(key)
                if value:
                    timestamps.append(str(value))
    return max(timestamps) if timestamps else str(int(time.time() * 1000))


def _scene_count_warning(scene_count: int, max_scenes: int) -> str:
    if scene_count >= max_scenes:
        return f"当前场景数量 {scene_count} 已达到上限 {max_scenes}，必须先 MERGE。"
    if scene_count == max_scenes - 1:
        return "距离场景上限只差 1 个，本次只能 UPDATE 现有场景，不能 CREATE。"
    if scene_count >= max_scenes - 3:
        return "场景数量接近上限，建议优先 UPDATE 或 MERGE。"
    return ""


class _ScenePathMixin:
    def _resolve_scene_path(self, input_data: dict[str, object], context: ToolContext) -> Path:
        filename = str(input_data.get("path", "") or "").strip()
        if not filename:
            raise ToolError("path is required")
        if "/" in filename or "\\" in filename or filename.startswith("."):
            raise ToolError("path must be a relative scene filename, not a directory path")
        if not filename.endswith(".md"):
            raise ToolError("scene path must end with .md")
        if _REPORT_PREFIX_RE.match(filename):
            raise ToolError("report/summary/archive scene files are not allowed")
        return context.resolve_path(filename)


class _SceneReadTool(_ScenePathMixin, ToolSpec):
    def name(self) -> str:
        return "read"

    def description(self) -> str:
        return "Read an existing scene Markdown file."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        path = self._resolve_scene_path(input_data, context)
        allowed_raw = context.metadata.get("allowed_scene_files") or []
        allowed = [str(x) for x in allowed_raw] if isinstance(allowed_raw, list) else []
        if allowed and path.name not in allowed:
            raise ToolError("read is limited to existing scene files listed in the prompt")
        return ToolResult(success=True, content=path.read_text(encoding="utf-8"))


class _SceneWriteTool(_ScenePathMixin, ToolSpec):
    def name(self) -> str:
        return "write"

    def description(self) -> str:
        return "Write a complete scene Markdown file, or write [DELETED] to delete."

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
        path = self._resolve_scene_path(input_data, context)
        content = str(input_data.get("content", "") or "")
        if not content:
            raise ToolError("content is required")
        path.write_text(content.rstrip() + "\n", encoding="utf-8")
        context.metadata["scene_write_count"] = int(
            context.metadata.get("scene_write_count", 0) or 0
        ) + 1
        return ToolResult(success=True, content="ok", metadata={"path": str(path)})


class _SceneEditTool(_ScenePathMixin, ToolSpec):
    def name(self) -> str:
        return "edit"

    def description(self) -> str:
        return "Apply one or more exact text replacements to a scene Markdown file."

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
        path = self._resolve_scene_path(input_data, context)
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
        path.write_text(content, encoding="utf-8")
        context.metadata["scene_write_count"] = int(
            context.metadata.get("scene_write_count", 0) or 0
        ) + 1
        return ToolResult(
            success=True,
            content=f"replaced {replacements} occurrence(s)",
            metadata={"path": str(path), "replacements": replacements},
        )


def _parse_persona_update_signal(text: str) -> str:
    match = _PERSONA_BLOCK_RE.search(text)
    if match:
        return match.group(1).strip()
    match = _PERSONA_INLINE_RE.search(text)
    if match:
        return match.group(1).strip()
    return ""
