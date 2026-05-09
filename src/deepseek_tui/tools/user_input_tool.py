"""RequestUserInputTool — pauses execution to ask the user a question.

Mirrors `crates/tui/src/tools/user_input.rs`.

The Engine intercepts this tool name, validates the input, emits a
UserInputRequiredEvent, and blocks until the TUI resolves the future.
The ToolSpec itself always raises — it must never be dispatched directly.
"""

from __future__ import annotations

from typing import Any

from deepseek_tui.tools.base import ToolCapability, ToolError, ToolResult, ToolSpec
from deepseek_tui.tools.context import ToolContext

REQUEST_USER_INPUT_NAME = "request_user_input"


class UserInputQuestion:
    """Validated question structure."""

    __slots__ = ("header", "id", "question", "options")

    def __init__(self, header: str, id: str, question: str, options: list[dict[str, str]]) -> None:
        self.header = header
        self.id = id
        self.question = question
        self.options = options


def validate_user_input_request(input_data: dict[str, Any]) -> list[UserInputQuestion]:
    """Validate and parse the request_user_input input.

    Mirrors Rust UserInputRequest::validate().
    Raises ToolError on invalid input.
    """
    tool_uses = input_data.get("questions")
    if not isinstance(tool_uses, list) or not (1 <= len(tool_uses) <= 3):
        raise ToolError("questions must be an array of 1-3 items")

    questions: list[UserInputQuestion] = []
    for item in tool_uses:
        if not isinstance(item, dict):
            raise ToolError("each question must be an object")
        header = item.get("header", "")
        qid = item.get("id", "")
        question_text = item.get("question", "")
        if not header or not qid or not question_text:
            raise ToolError("header, id, and question are required and must be non-empty")

        options = item.get("options")
        if not isinstance(options, list) or not (2 <= len(options) <= 3):
            raise ToolError("each question must have 2-3 options")

        for opt in options:
            if not isinstance(opt, dict):
                raise ToolError("each option must be an object")
            label = opt.get("label", "")
            description = opt.get("description", "")
            if not label or not description:
                raise ToolError("option label and description are required and must be non-empty")

        questions.append(UserInputQuestion(
            header=header,
            id=qid,
            question=question_text,
            options=options,
        ))

    return questions


class RequestUserInputTool(ToolSpec):
    def name(self) -> str:
        return REQUEST_USER_INPUT_NAME

    def description(self) -> str:
        return (
            "Ask the user a multiple-choice question. "
            "Must be handled by the engine — direct execution is an error."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "header": {"type": "string"},
                            "id": {"type": "string"},
                            "question": {"type": "string"},
                            "options": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "label": {"type": "string"},
                                        "description": {"type": "string"},
                                    },
                                    "required": ["label", "description"],
                                },
                                "minItems": 2,
                                "maxItems": 3,
                            },
                        },
                        "required": ["header", "id", "question", "options"],
                    },
                    "minItems": 1,
                    "maxItems": 3,
                }
            },
            "required": ["questions"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        raise ToolError("request_user_input must be handled by the engine")
