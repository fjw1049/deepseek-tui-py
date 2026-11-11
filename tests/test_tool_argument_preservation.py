import pytest

from deepseek_tui.client.streaming import parse_json_object
from deepseek_tui.engine.dispatch import repair as legacy_repair
from deepseek_tui.engine.tool_arguments import repair
from deepseek_tui.tools.file import WriteFileTool
from deepseek_tui.tools.registry import ToolContext


@pytest.mark.parametrize("value", [",}", ",]", "text, }end", '\\",}'])
def test_repair_preserves_literal_delimiters(value):
    import json

    raw = '{"content": ' + json.dumps(value) + ",}"
    assert repair(raw) == {"content": value}
    assert legacy_repair is repair


async def test_streamed_repaired_arguments_write_exact_file_content(tmp_path):
    raw = '{"path":"report.txt","content":"literal ,} and ,]",}'
    args = parse_json_object(raw)
    await WriteFileTool().execute(args, ToolContext(working_directory=tmp_path))
    assert (tmp_path / "report.txt").read_text() == "literal ,} and ,]"
