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

    __slots__ = ("header", "id", "question", "options", "description", "allow_custom")

    def __init__(self, header: str, id: str, question: str, options: list[dict[str, str]],
                 description: str = "", allow_custom: bool = True) -> None:
        self.header = header
        self.id = id
        self.question = question
        self.options = options
        self.description = description
        self.allow_custom = allow_custom


def validate_user_input_request(input_data: dict[str, Any]) -> list[UserInputQuestion]:
    """Validate and parse the request_user_input input.

    Raises ToolError on invalid input.
    """
    tool_uses = input_data.get("questions")
    if not isinstance(tool_uses, list) or not (1 <= len(tool_uses) <= 3):
        raise ToolError("questions must be an array of 1-3 items")

    questions: list[UserInputQuestion] = []
    seen_ids: set[str] = set()
    for item in tool_uses:
        if not isinstance(item, dict):
            raise ToolError("each question must be an object")
        header = item.get("header", "")
        qid = item.get("id", "")
        question_text = item.get("question", "")
        if any(not isinstance(v, str) or not v.strip()
               for v in (header, qid, question_text)):
            raise ToolError("header, id, and question are required and must be non-empty")

        if qid in seen_ids:
            raise ToolError("question ids must be unique")
        seen_ids.add(qid)
        options = item.get("options", [])
        if not isinstance(options, list) or len(options) not in {0, 2, 3, 4}:
            raise ToolError("each question must omit options or have 2-4 options")

        description = item.get("description", "")
        allow_custom = item.get("allow_custom", True)
        if not isinstance(description, str) or not isinstance(allow_custom, bool):
            raise ToolError("description must be a string and allow_custom must be a boolean")
        if not options and not allow_custom:
            raise ToolError("questions without options must allow custom answers")

        for opt in options:
            if not isinstance(opt, dict):
                raise ToolError("each option must be an object")
            label = opt.get("label", "")
            option_description = opt.get("description", "")
            if not isinstance(label, str) or not label.strip() or not isinstance(option_description, str):
                raise ToolError("option label must be non-empty and description must be a string")

        questions.append(UserInputQuestion(
            header=header,
            id=qid,
            question=question_text,
            options=[dict(opt) for opt in options],
            description=description,
            allow_custom=allow_custom,
        ))

    return questions


class RequestUserInputTool(ToolSpec):
    def name(self) -> str:
        return REQUEST_USER_INPUT_NAME

    def description(self) -> str:
        return (
            "Request information, a decision, or a manual browser or desktop action. "
            "Omit options for a free-text answer. For action, supply reason and surface: "
            "surface=browser uses the existing browser takeover UI, which pauses the task, "
            "without a second question card; surface=desktop (when computer use is "
            "available) releases the desktop and asks the user to do one step on their "
            "computer, after which you must observe again. "
            "Never request passwords or verification codes in chat. Use as the only tool call. "
            "Must be handled by the engine — direct execution is an error."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string", "enum": ["information", "decision", "action"],
                    "description": "Defaults to information; action requests manual takeover.",
                },
                "surface": {
                    "type": "string", "enum": ["browser", "desktop"],
                    "description": "Required for action: where the human takes over.",
                },
                "reason": {
                    "type": "string",
                    "description": "For action: blocker and smallest useful human step.",
                },
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
                            "description": {"type": "string", "description": "Optional brief context; do not repeat the question."},
                            "allow_custom": {"type": "boolean", "description": "Defaults to true. Set false for choices only."},
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
                                    "required": ["label"],
                                },
                                "minItems": 2,
                                "maxItems": 4,
                            },
                        },
                        "required": ["header", "id", "question"],
                    },
                    "minItems": 1,
                    "maxItems": 3,
                }
            },
            "anyOf": [
                {"required": ["questions"]},
                {"required": ["kind", "surface", "reason"]},
            ],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    def supports_parallel(self) -> bool:
        return False

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        raise ToolError("request_user_input must be handled by the engine")
