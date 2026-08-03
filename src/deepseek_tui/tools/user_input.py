"""User input tool.

Formerly also hosted ``retrieve_tool_result``, which was retired once
large-output truncation moved to the spillover mechanism (read the
spilled file back with ``read_file``/``grep_files``).
"""

from __future__ import annotations



# RequestUserInputTool — pauses execution to ask the user a question.
#
# The Engine intercepts this tool name, validates the input, emits a
# UserInputRequiredEvent, and blocks until the TUI resolves the future.
# The ToolSpec itself always raises — it must never be dispatched directly.
#
from typing import Any

from deepseek_tui.tools.registry import ToolCapability, ToolError, ToolResult, ToolSpec
from deepseek_tui.tools.registry import ToolContext

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
        if not isinstance(options, list) or not (2 <= len(options) <= 4):
            raise ToolError("each question must have 2-4 options")

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
                    "description": (
                        "1-3 questions rendered together as one selectable "
                        "card. Bundle every pending decision into a single "
                        "call instead of asking in succession."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "header": {
                                "type": "string",
                                "description": (
                                    "Short card title (a few words), e.g. "
                                    "'Database choice'."
                                ),
                            },
                            "id": {
                                "type": "string",
                                "description": (
                                    "Unique id for this question within "
                                    "the call (snake_case)."
                                ),
                            },
                            "question": {
                                "type": "string",
                                "description": (
                                    "The question text, one sentence, in "
                                    "the conversation language."
                                ),
                            },
                            "options": {
                                "type": "array",
                                "description": (
                                    "2-4 mutually exclusive choices. Put "
                                    "your recommended option first."
                                ),
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "label": {
                                            "type": "string",
                                            "description": (
                                                "Short option label shown "
                                                "on the button."
                                            ),
                                        },
                                        "description": {
                                            "type": "string",
                                            "description": (
                                                "One line on what picking "
                                                "this option implies."
                                            ),
                                        },
                                    },
                                    "required": ["label", "description"],
                                },
                                "minItems": 2,
                                "maxItems": 4,
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
