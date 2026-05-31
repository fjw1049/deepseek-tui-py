"""Smart memory search tools (P2) — L1 structured + L0 conversation search."""

from __future__ import annotations

from deepseek_tui.memory.native.provider import NativeMemoryProvider
from deepseek_tui.tools.base import ToolCapability, ToolError, ToolResult, ToolSpec
from deepseek_tui.tools.context import ToolContext

MEMORY_PROVIDER_KEY = "memory_provider"
MEMORY_SEARCH_CALLS_KEY = "memory_search_calls"
MAX_COMBINED_SEARCH_CALLS = 3
HARD_MAX_SEARCH_LIMIT = 10


def _require_provider(context: ToolContext) -> NativeMemoryProvider:
    raw = context.metadata.get(MEMORY_PROVIDER_KEY)
    if not isinstance(raw, NativeMemoryProvider):
        raise ToolError(
            "Smart memory is not active. Set [memory.smart] enabled = true in config."
        )
    return raw


def _workspace(context: ToolContext) -> str:
    return str(context.working_directory.resolve())


def _thread_id(context: ToolContext) -> str | None:
    tid = context.metadata.get("runtime_thread_id")
    return tid if isinstance(tid, str) and tid else None


def _check_search_budget(context: ToolContext) -> None:
    count = context.metadata.get(MEMORY_SEARCH_CALLS_KEY, 0)
    if not isinstance(count, int):
        count = 0
    if count >= MAX_COMBINED_SEARCH_CALLS:
        raise ToolError(
            f"memory_search and conversation_search share a limit of "
            f"{MAX_COMBINED_SEARCH_CALLS} calls per turn. Stop searching."
        )
    context.metadata[MEMORY_SEARCH_CALLS_KEY] = count + 1


def _parse_limit(input_data: dict[str, object], default: int = 5) -> int:
    raw = input_data.get("limit")
    if raw is None:
        return default
    if isinstance(raw, int):
        return min(max(1, raw), HARD_MAX_SEARCH_LIMIT)
    if isinstance(raw, float) and raw == int(raw):
        return min(max(1, int(raw)), HARD_MAX_SEARCH_LIMIT)
    raise ToolError("'limit' must be an integer")


class MemorySearchTool(ToolSpec):
    """Search structured L1 memories (SQLite FTS)."""

    def name(self) -> str:
        return "memory_search"

    def description(self) -> str:
        return (
            "Search structured long-term memories (preferences, events, instructions) "
            "extracted from past conversations. Use when you need user-specific facts "
            "not visible in the current transcript. "
            f"Limit: memory_search and conversation_search share {MAX_COMBINED_SEARCH_CALLS} "
            "calls per turn combined."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keywords describing what to recall.",
                },
                "type": {
                    "type": "string",
                    "enum": ["persona", "episodic", "instruction"],
                    "description": "Optional memory type filter.",
                },
                "limit": {
                    "type": "integer",
                    "description": f"Max results (default 5, max {HARD_MAX_SEARCH_LIMIT}).",
                },
            },
            "required": ["query"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        _check_search_budget(context)
        provider = _require_provider(context)
        query = str(input_data.get("query", "")).strip()
        if not query:
            raise ToolError("'query' is required")
        mem_type = input_data.get("type")
        type_filter = mem_type if isinstance(mem_type, str) and mem_type else None
        limit = _parse_limit(input_data)
        text = await provider.search_memories(
            query,
            workspace=_workspace(context),
            limit=limit,
            mem_type=type_filter,
        )
        return ToolResult(
            success=True,
            content=text,
            metadata={"query": query, "limit": limit, "type": type_filter},
        )


class ConversationSearchTool(ToolSpec):
    """Search raw L0 conversation JSONL archives."""

    def name(self) -> str:
        return "conversation_search"

    def description(self) -> str:
        return (
            "Search raw conversation archives when structured memory_search results "
            "are insufficient. Returns message excerpts with thread/line metadata. "
            f"Limit: memory_search and conversation_search share {MAX_COMBINED_SEARCH_CALLS} "
            "calls per turn combined."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keywords to find in past messages.",
                },
                "limit": {
                    "type": "integer",
                    "description": f"Max hits (default 5, max {HARD_MAX_SEARCH_LIMIT}).",
                },
                "scope": {
                    "type": "string",
                    "enum": ["workspace", "current_thread", "all"],
                    "description": "Search scope. Defaults to workspace.",
                },
            },
            "required": ["query"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        _check_search_budget(context)
        provider = _require_provider(context)
        query = str(input_data.get("query", "")).strip()
        if not query:
            raise ToolError("'query' is required")
        limit = _parse_limit(input_data)
        raw_scope = input_data.get("scope", "workspace")
        scope = raw_scope if isinstance(raw_scope, str) else "workspace"
        if scope not in ("workspace", "current_thread", "all"):
            raise ToolError("'scope' must be one of: workspace, current_thread, all")
        workspace = None if scope == "all" else _workspace(context)
        thread_id = _thread_id(context) if scope == "current_thread" else None
        text = await provider.search_conversations(
            query,
            workspace=workspace,
            thread_id=thread_id,
            limit=limit,
        )
        return ToolResult(
            success=True,
            content=text,
            metadata={"query": query, "limit": limit, "scope": scope},
        )
