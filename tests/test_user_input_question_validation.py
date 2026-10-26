import pytest

from deepseek_tui.tools.registry import ToolError
from deepseek_tui.tools.user_input import validate_user_input_request


def test_optional_context_and_closed_choices():
    question = {"id": "format", "header": "Format", "question": "Which format?",
                "description": "Export format", "allow_custom": False,
                "options": [{"label": "PDF"}, {"label": "Text"}]}
    parsed = validate_user_input_request({"questions": [question]})[0]
    assert parsed.description == "Export format"
    assert parsed.allow_custom is False
    assert parsed.options == question["options"]


def test_free_text_requires_a_way_to_answer():
    question = {"id": "name", "header": "Name", "question": "Your name?"}
    assert validate_user_input_request({"questions": [question]})[0].allow_custom
    with pytest.raises(ToolError, match="without options"):
        validate_user_input_request({"questions": [{**question, "allow_custom": False}]})
