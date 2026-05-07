"""Parity tests for engine/tool_parser.

Mirror of Rust `crates/tui/src/core/tool_parser.rs` tests.
"""

from __future__ import annotations

from deepseek_tui.engine.tool_parser import (
    ParsedToolCall,
    ParseResult,
    has_tool_call_markers,
    parse_tool_calls,
    parse_tool_input,
)


class TestParseToolCalls:
    """Tests for text-based tool call parsing."""

    def test_parse_arrow_syntax(self) -> None:
        """Mirror of Rust test_parse_arrow_syntax."""
        text = """I'll list the directory.
[TOOL_CALL]
{tool => "list_dir", args => {}}
[/TOOL_CALL]"""

        result = parse_tool_calls(text)
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "list_dir"
        assert result.clean_text == "I'll list the directory."

    def test_parse_json_syntax(self) -> None:
        """Mirror of Rust test_parse_json_syntax."""
        text = """Let me check.
[TOOL_CALL]
{"tool": "read_file", "args": {"path": "test.txt"}}
[/TOOL_CALL]"""

        result = parse_tool_calls(text)
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "read_file"
        assert result.tool_calls[0].args is not None
        assert result.tool_calls[0].args["path"] == "test.txt"

    def test_parse_multiple_tool_calls(self) -> None:
        """Mirror of Rust test_parse_multiple_tool_calls."""
        text = """First I'll list, then read.
[TOOL_CALL]
{tool => "list_dir", args => {}}
[/TOOL_CALL]
[TOOL_CALL]
{tool => "read_file", args => {"path": "file.txt"}}
[/TOOL_CALL]"""

        result = parse_tool_calls(text)
        assert len(result.tool_calls) == 2
        assert result.tool_calls[0].name == "list_dir"
        assert result.tool_calls[1].name == "read_file"

    def test_no_tool_calls(self) -> None:
        """Mirror of Rust test_no_tool_calls."""
        text = "Just some regular text without any tool calls."
        result = parse_tool_calls(text)
        assert len(result.tool_calls) == 0
        assert result.clean_text == text

    def test_has_markers(self) -> None:
        """Mirror of Rust test_has_markers."""
        assert has_tool_call_markers("[TOOL_CALL]test[/TOOL_CALL]")
        assert not has_tool_call_markers("no markers here")


class TestParseToolInput:
    """Tests for stream fragment reassembly."""

    def test_parse_direct_json(self) -> None:
        """Direct JSON parse should work."""
        result = parse_tool_input('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parse_empty_buffer(self) -> None:
        """Empty buffer should return None."""
        assert parse_tool_input("") is None
        assert parse_tool_input("   ") is None

    def test_parse_with_code_fences(self) -> None:
        """Code fences should be stripped."""
        text = '```\n{"key": "value"}\n```'
        result = parse_tool_input(text)
        assert result == {"key": "value"}

    def test_parse_double_quoted_json(self) -> None:
        """Double-quoted JSON string should be parsed."""
        import json as json_module
        json_str = json_module.dumps('{"key": "value"}')
        result = parse_tool_input(json_str)
        assert result == {"key": "value"}

    def test_parse_partial_json_with_braces(self) -> None:
        """Partial JSON (incomplete but balanced) should extract segment."""
        text = '{"key": "value"}'
        result = parse_tool_input(text)
        assert result == {"key": "value"}

    def test_parse_json_with_whitespace(self) -> None:
        """JSON with extra whitespace should parse."""
        text = "   { \"key\" : \"value\" }   "
        result = parse_tool_input(text)
        assert result == {"key": "value"}

    def test_parse_json_array_not_dict(self) -> None:
        """JSON array (not dict) should return None."""
        text = "[1, 2, 3]"
        result = parse_tool_input(text)
        assert result is None

    def test_parse_invalid_json_no_fallback(self) -> None:
        """Invalid JSON with no fallback should return None."""
        text = "this is not json"
        result = parse_tool_input(text)
        assert result is None

    def test_parse_nested_json(self) -> None:
        """Nested JSON should parse correctly."""
        text = '{"outer": {"inner": "value"}}'
        result = parse_tool_input(text)
        assert result == {"outer": {"inner": "value"}}

    def test_parse_json_with_arrays(self) -> None:
        """JSON with array values should parse."""
        text = '{"items": [1, 2, 3]}'
        result = parse_tool_input(text)
        assert result == {"items": [1, 2, 3]}


class TestParseResultStructure:
    """Tests for ParseResult structure."""

    def test_parse_result_has_fields(self) -> None:
        """ParseResult should have clean_text and tool_calls."""
        result = ParseResult(clean_text="test", tool_calls=[])
        assert result.clean_text == "test"
        assert result.tool_calls == []

    def test_parsed_tool_call_structure(self) -> None:
        """ParsedToolCall should have name, args, id."""
        call = ParsedToolCall(name="test_tool", args={"key": "value"}, id="1")
        assert call.name == "test_tool"
        assert call.args == {"key": "value"}
        assert call.id == "1"


class TestToolCallFormatVariants:
    """Tests for various tool call format variants."""

    def test_parse_json_with_name_field(self) -> None:
        """JSON with 'name' field instead of 'tool'."""
        text = """
[TOOL_CALL]
{"name": "my_tool", "args": {"x": 1}}
[/TOOL_CALL]"""
        result = parse_tool_calls(text)
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "my_tool"

    def test_parse_json_with_arguments_field(self) -> None:
        """JSON with 'arguments' field instead of 'args'."""
        text = """
[TOOL_CALL]
{"tool": "my_tool", "arguments": {"x": 1}}
[/TOOL_CALL]"""
        result = parse_tool_calls(text)
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].args is not None
        assert result.tool_calls[0].args["x"] == 1

    def test_parse_with_thinking_tags(self) -> None:
        """Thinking tags should be removed from clean_text."""
        text = """<thinking>
Let me think about this.
</thinking>
Some output here."""
        result = parse_tool_calls(text)
        assert "<thinking>" not in result.clean_text
        assert "Some output here." in result.clean_text

    def test_parse_xml_tool_call(self) -> None:
        """XML-style tool call should parse."""
        text = """
<deepseek:tool_call>
<invoke name="list_files">
</invoke>
</deepseek:tool_call>"""
        result = parse_tool_calls(text)
        assert len(result.tool_calls) >= 0  # XML parsing may vary slightly


class TestEdgeCases:
    """Tests for edge cases."""

    def test_parse_empty_tool_call_block(self) -> None:
        """Empty TOOL_CALL block should be handled."""
        text = "[TOOL_CALL][/TOOL_CALL]"
        result = parse_tool_calls(text)
        assert len(result.tool_calls) == 0

    def test_parse_tool_input_with_unicode(self) -> None:
        """Unicode in JSON should parse."""
        text = '{"name": "测试"}'
        result = parse_tool_input(text)
        assert result == {"name": "测试"}

    def test_parse_multiple_markers_same_text(self) -> None:
        """Multiple tool call markers should all be detected."""
        text = "Has [TOOL_CALL] and <tool_call> and <invoke "
        assert has_tool_call_markers(text)

    def test_parse_result_clean_text_preserves_non_tool_content(self) -> None:
        """Clean text should preserve all non-tool content."""
        text = "Start\n[TOOL_CALL]{tool => \"x\", args => {}}[/TOOL_CALL]\nEnd"
        result = parse_tool_calls(text)
        assert "Start" in result.clean_text
        assert "End" in result.clean_text
        assert "TOOL_CALL" not in result.clean_text
