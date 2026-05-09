"""Tests for engine core modules: context, dispatch, tool_execution, tool_catalog.

Covers the four new engine modules added to mirror Rust's
context.rs, dispatch.rs, tool_execution.rs, tool_catalog.rs.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import pytest

from deepseek_tui.engine.context import (
    COMPACTION_SUMMARY_MARKER,
    CONTEXT_HEADROOM_TOKENS,
    TURN_MAX_OUTPUT_TOKENS,
    WORKING_SET_SUMMARY_MARKER,
    append_working_set_summary,
    compact_tool_result_for_context,
    context_input_budget,
    estimate_input_tokens_conservative,
    extract_compaction_summary_prompt,
    is_context_length_error_message,
    remove_working_set_summary,
    summarize_text,
    summarize_text_head_tail,
    turn_response_headroom_tokens,
)
from deepseek_tui.engine.dispatch import (
    ToolExecutionPlan,
    caller_allowed_for_tool,
    format_tool_error,
    parse_parallel_tool_calls,
    parse_tool_input,
    should_force_update_plan_first,
    should_parallelize_tool_batch,
    should_stop_after_plan_tool,
)
from deepseek_tui.engine.tool_catalog import (
    TOOL_SEARCH_BM25_NAME,
    TOOL_SEARCH_REGEX_NAME,
    discover_tools_with_bm25_like,
    discover_tools_with_regex,
    edit_distance,
    execute_tool_search,
    is_tool_search_tool,
    missing_tool_error_message,
    should_default_defer_tool,
    suggest_tool_names,
)
from deepseek_tui.engine.tool_execution import emit_tool_audit
from deepseek_tui.tools.base import ToolError, ToolResult

# ===== context.py tests =====


class TestSummarizeText:
    def test_short_text_unchanged(self) -> None:
        assert summarize_text("hello", 10) == "hello"

    def test_long_text_truncated(self) -> None:
        result = summarize_text("hello world", 8)
        assert result.endswith("...")
        assert len(result) <= 8

    def test_head_tail_short_unchanged(self) -> None:
        assert summarize_text_head_tail("hello", 100) == "hello"

    def test_head_tail_long_keeps_both_ends(self) -> None:
        text = "A" * 500 + "B" * 500
        result = summarize_text_head_tail(text, 200)
        assert "A" in result
        assert "B" in result
        assert "truncated" in result


class TestContextConstants:
    def test_turn_max_output_tokens(self) -> None:
        assert TURN_MAX_OUTPUT_TOKENS == 262_144

    def test_headroom_tokens(self) -> None:
        assert CONTEXT_HEADROOM_TOKENS == 1024

    def test_response_headroom(self) -> None:
        assert turn_response_headroom_tokens() == TURN_MAX_OUTPUT_TOKENS + CONTEXT_HEADROOM_TOKENS


class TestContextBudget:
    def test_budget_for_known_model(self) -> None:
        budget = context_input_budget("deepseek-chat", 4096)
        assert budget is not None
        assert budget > 0

    def test_budget_returns_none_when_exhausted(self) -> None:
        budget = context_input_budget("deepseek-chat", 999_999)
        assert budget is None


class TestCompactToolResult:
    def test_empty_content_returns_empty(self) -> None:
        result = ToolResult(success=True, content="   ")
        assert compact_tool_result_for_context("deepseek-chat", "read_file", result) == ""

    def test_short_content_unchanged(self) -> None:
        result = ToolResult(success=True, content="ok")
        assert compact_tool_result_for_context("deepseek-chat", "read_file", result) == "ok"

    def test_large_noisy_tool_compacted(self) -> None:
        big_output = "x" * 200_000
        result = ToolResult(success=True, content=big_output)
        compacted = compact_tool_result_for_context("deepseek-chat", "exec_shell", result)
        assert len(compacted) < len(big_output)
        assert "compacted" in compacted


class TestSystemPromptManagement:
    def test_extract_compaction_summary_returns_none_when_absent(self) -> None:
        assert extract_compaction_summary_prompt("no marker here") is None

    def test_extract_compaction_summary_returns_prompt(self) -> None:
        prompt = f"Some text\n{COMPACTION_SUMMARY_MARKER}\nSummary"
        assert extract_compaction_summary_prompt(prompt) == prompt

    def test_remove_working_set_summary(self) -> None:
        prompt = f"Base prompt\n{WORKING_SET_SUMMARY_MARKER}\nExtra"
        result = remove_working_set_summary(prompt)
        assert result is not None
        assert WORKING_SET_SUMMARY_MARKER not in result

    def test_append_working_set_summary(self) -> None:
        result = append_working_set_summary("base", "## Repo Working Set\nfiles")
        assert result is not None
        assert "base" in result
        assert "files" in result


class TestContextLengthError:
    def test_detects_context_length_error(self) -> None:
        assert is_context_length_error_message("context length exceeded")
        assert is_context_length_error_message("Too Many Tokens")
        assert is_context_length_error_message("reduce the length of messages")

    def test_normal_message_not_flagged(self) -> None:
        assert not is_context_length_error_message("tool execution failed")


class TestTokenEstimation:
    def test_estimate_returns_positive(self) -> None:
        from deepseek_tui.protocol.messages import Message
        msgs = [Message.user("hello world")]
        tokens = estimate_input_tokens_conservative(msgs, "system prompt")
        assert tokens > 0


# ===== dispatch.py tests =====


class TestParseToolInput:
    def test_parse_valid_json(self) -> None:
        result = parse_tool_input('{"path": "/tmp/file.txt"}')
        assert result == {"path": "/tmp/file.txt"}

    def test_parse_empty_returns_none(self) -> None:
        assert parse_tool_input("") is None
        assert parse_tool_input("   ") is None

    def test_parse_with_code_fences(self) -> None:
        buf = '```json\n{"key": "value"}\n```'
        result = parse_tool_input(buf)
        assert result == {"key": "value"}

    def test_parse_double_encoded(self) -> None:
        inner = json.dumps({"a": 1})
        outer = json.dumps(inner)
        result = parse_tool_input(outer)
        assert result == {"a": 1}

    def test_parse_with_prefix_text(self) -> None:
        buf = 'Some text before {"action": "run"} after'
        result = parse_tool_input(buf)
        assert result == {"action": "run"}


class TestParseParallelToolCalls:
    def test_parse_valid_parallel(self) -> None:
        data = {
            "tool_uses": [
                {"recipient_name": "functions.read_file", "parameters": {"path": "/a"}},
                {"recipient_name": "tools.grep_files", "parameters": {"pattern": "x"}},
            ]
        }
        calls = parse_parallel_tool_calls(data)
        assert len(calls) == 2
        assert calls[0] == ("read_file", {"path": "/a"})
        assert calls[1] == ("grep_files", {"pattern": "x"})

    def test_parse_empty_raises(self) -> None:
        with pytest.raises(ToolError):
            parse_parallel_tool_calls({"tool_uses": []})


class TestCallerPolicy:
    def test_direct_caller_allowed_by_default(self) -> None:
        assert caller_allowed_for_tool(None, None)

    def test_direct_caller_in_list(self) -> None:
        assert caller_allowed_for_tool(None, ["direct"])

    def test_non_direct_caller_blocked(self) -> None:
        assert not caller_allowed_for_tool("subagent", ["direct"])


class TestFormatToolError:
    def test_timeout_error(self) -> None:
        msg = format_tool_error(Exception("timeout"), "exec_shell")
        assert "timed out" in msg

    def test_generic_error(self) -> None:
        msg = format_tool_error(Exception("something broke"), "read_file")
        assert "something broke" in msg


class TestDispatchPolicy:
    def test_parallelize_all_read_only(self) -> None:
        plans = [
            ToolExecutionPlan(
                index=0, id="1", name="a", input={},
                read_only=True, supports_parallel=True,
            ),
            ToolExecutionPlan(
                index=1, id="2", name="b", input={},
                read_only=True, supports_parallel=True,
            ),
        ]
        assert should_parallelize_tool_batch(plans)

    def test_no_parallelize_with_write(self) -> None:
        plans = [
            ToolExecutionPlan(
                index=0, id="1", name="a", input={},
                read_only=False, supports_parallel=True,
            ),
        ]
        assert not should_parallelize_tool_batch(plans)

    def test_stop_after_plan_tool(self) -> None:
        assert should_stop_after_plan_tool("plan", "update_plan", True)
        assert not should_stop_after_plan_tool("agent", "update_plan", True)
        assert not should_stop_after_plan_tool("plan", "update_plan", False)

    def test_force_update_plan_first(self) -> None:
        assert should_force_update_plan_first("plan", "give me a quick plan")
        assert not should_force_update_plan_first("agent", "give me a quick plan")
        assert not should_force_update_plan_first(
            "plan", "inspect the repo and give me a quick plan"
        )


# ===== tool_execution.py tests =====


class TestEmitToolAudit:
    def test_no_op_without_env_var(self) -> None:
        old = os.environ.pop("DEEPSEEK_TOOL_AUDIT_LOG", None)
        try:
            emit_tool_audit({"event": "test"})
        finally:
            if old is not None:
                os.environ["DEEPSEEK_TOOL_AUDIT_LOG"] = old

    def test_writes_jsonl_to_file(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        old = os.environ.get("DEEPSEEK_TOOL_AUDIT_LOG")
        try:
            os.environ["DEEPSEEK_TOOL_AUDIT_LOG"] = path
            emit_tool_audit({"event": "tool.result", "tool_name": "read_file"})
            emit_tool_audit({"event": "tool.result", "tool_name": "write_file"})
            content = Path(path).read_text()
            lines = [ln for ln in content.strip().split("\n") if ln]
            assert len(lines) == 2
            first = json.loads(lines[0])
            assert first["tool_name"] == "read_file"
        finally:
            if old is not None:
                os.environ["DEEPSEEK_TOOL_AUDIT_LOG"] = old
            else:
                os.environ.pop("DEEPSEEK_TOOL_AUDIT_LOG", None)
            os.unlink(path)


# ===== tool_catalog.py tests =====


class TestToolDeferral:
    def test_always_active_not_deferred(self) -> None:
        assert not should_default_defer_tool("read_file", "agent")
        assert not should_default_defer_tool("grep_files", "agent")
        assert not should_default_defer_tool("diagnostics", "agent")

    def test_shell_not_deferred_in_agent(self) -> None:
        assert not should_default_defer_tool("exec_shell", "agent")

    def test_unknown_tool_deferred(self) -> None:
        assert should_default_defer_tool("some_obscure_tool", "agent")

    def test_yolo_mode_never_defers(self) -> None:
        assert not should_default_defer_tool("some_obscure_tool", "yolo")


class TestToolSearch:
    CATALOG: list[dict[str, Any]] = [
        {"function": {"name": "read_file", "description": "Read a file", "parameters": {}}},
        {"function": {"name": "write_file", "description": "Write content", "parameters": {}}},
        {"function": {"name": "grep_files", "description": "Search files", "parameters": {}}},
    ]

    def test_regex_search(self) -> None:
        results = discover_tools_with_regex(self.CATALOG, r"read|write")
        assert "read_file" in results
        assert "write_file" in results

    def test_bm25_search(self) -> None:
        results = discover_tools_with_bm25_like(self.CATALOG, "read file")
        assert "read_file" in results

    def test_regex_invalid_raises(self) -> None:
        with pytest.raises(ToolError):
            discover_tools_with_regex(self.CATALOG, "[invalid")


class TestEditDistance:
    def test_identical_strings(self) -> None:
        assert edit_distance("abc", "abc") == 0

    def test_single_edit(self) -> None:
        assert edit_distance("abc", "abd") == 1

    def test_empty_string(self) -> None:
        assert edit_distance("", "abc") == 3


class TestSuggestToolNames:
    CATALOG: list[dict[str, Any]] = [
        {"function": {"name": "read_file", "description": "", "parameters": {}}},
        {"function": {"name": "write_file", "description": "", "parameters": {}}},
        {"function": {"name": "grep_files", "description": "", "parameters": {}}},
    ]

    def test_suggests_similar(self) -> None:
        suggestions = suggest_tool_names(self.CATALOG, "read_fil")
        assert "read_file" in suggestions

    def test_no_suggestion_for_unrelated(self) -> None:
        suggestions = suggest_tool_names(self.CATALOG, "zzzzzzzzzzz")
        assert len(suggestions) == 0


class TestMissingToolMessage:
    def test_with_suggestions(self) -> None:
        catalog: list[dict[str, Any]] = [
            {"function": {"name": "read_file", "description": "", "parameters": {}}},
        ]
        msg = missing_tool_error_message("read_fil", catalog)
        assert "read_file" in msg
        assert "Did you mean" in msg

    def test_without_suggestions(self) -> None:
        msg = missing_tool_error_message("zzzzz", [])
        assert "not available" in msg


class TestIsToolSearchTool:
    def test_identifies_search_tools(self) -> None:
        assert is_tool_search_tool(TOOL_SEARCH_REGEX_NAME)
        assert is_tool_search_tool(TOOL_SEARCH_BM25_NAME)
        assert not is_tool_search_tool("read_file")


class TestExecuteToolSearch:
    CATALOG: list[dict[str, Any]] = [
        {"function": {"name": "read_file", "description": "Read a file", "parameters": {}}},
        {"function": {"name": "write_file", "description": "Write content", "parameters": {}}},
    ]

    def test_regex_search_activates_tools(self) -> None:
        active: set[str] = set()
        result = execute_tool_search(
            TOOL_SEARCH_REGEX_NAME, {"query": "read"}, self.CATALOG, active
        )
        assert result.success
        assert "read_file" in active

    def test_bm25_search_activates_tools(self) -> None:
        active: set[str] = set()
        result = execute_tool_search(
            TOOL_SEARCH_BM25_NAME, {"query": "write file"}, self.CATALOG, active
        )
        assert result.success
        assert "write_file" in active

    def test_missing_query_raises(self) -> None:
        with pytest.raises(ToolError):
            execute_tool_search(TOOL_SEARCH_REGEX_NAME, {}, [], set())
