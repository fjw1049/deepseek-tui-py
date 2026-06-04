"""Workflow runtime constants."""

from __future__ import annotations

PREVIEW_MAX_PER_STEP = 2000
PREVIEW_MAX_FANOUT_ITEM = 800
FULL_TEXT_MAX = 32_768
DEFAULT_WALL_CLOCK_SECONDS = 600
DEFAULT_CONCURRENCY = 4
DEFAULT_MAX_AGENTS = 10
MAX_FANOUT_ITEMS = 16
WAIT_TIMEOUT_MS = 3_600_000

# analysis_only — forced read-only tool allowlist
ANALYSIS_ONLY_TOOLS: frozenset[str] = frozenset(
    {
        "read_file",
        "list_dir",
        "grep_files",
        "file_search",
        "git_status",
        "git_diff",
        "git_log",
        "git_show",
        "git_blame",
        "diagnostics",
        "project_map",
        "retrieve_tool_result",
        "checklist_list",
        "todo_list",
        "web_search",
        "fetch_url",
    }
)
