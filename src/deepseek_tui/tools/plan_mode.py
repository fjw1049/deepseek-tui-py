"""Plan-mode enter/exit tools (engine-intercepted).

Mirrors Claude ``EnterPlanMode`` / ``ExitPlanMode`` and Grok
``enter_plan_mode`` / ``exit_plan_mode``: the model proposes the transition;
the engine asks the user, then switches interaction mode.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from deepseek_tui.config.paths import DOT_DEEPSEEK, user_thread_plan_path
from deepseek_tui.tools.registry import ToolCapability, ToolError, ToolResult, ToolSpec

ENTER_PLAN_MODE_NAME = "enter_plan_mode"
EXIT_PLAN_MODE_NAME = "exit_plan_mode"

ENTER_QUESTION_ID = "enter_plan"
EXIT_QUESTION_ID = "exit_plan"

ENTER_APPROVE_VALUE = "enter"
ENTER_DECLINE_VALUE = "stay"

EXIT_ACCEPT_AGENT = "accept_agent"
EXIT_ACCEPT_YOLO = "accept_yolo"
EXIT_REVISE = "revise"
EXIT_LEAVE = "exit_plan"


def _locale(locale: str | None) -> str:
    return "en" if (locale or "").strip().lower() == "en" else "zh"


def enter_plan_questions(locale: str | None = None) -> list[dict[str, object]]:
    if _locale(locale) == "en":
        return [
            {
                "header": "Plan mode",
                "id": ENTER_QUESTION_ID,
                "question": (
                    "Enter read-only plan mode to explore the codebase and "
                    "design an approach before implementing?"
                ),
                "options": [
                    {
                        "label": "Enter plan mode",
                        "description": (
                            "Switch to read-only planning. No edits until "
                            "you approve a plan."
                        ),
                        "value": ENTER_APPROVE_VALUE,
                    },
                    {
                        "label": "Stay in agent",
                        "description": (
                            "Keep implementing without entering plan mode."
                        ),
                        "value": ENTER_DECLINE_VALUE,
                    },
                ],
            }
        ]
    return [
        {
            "header": "规划模式",
            "id": ENTER_QUESTION_ID,
            "question": (
                "进入只读规划模式，先摸清代码库并设计实现方案，再动手改代码？"
            ),
            "options": [
                {
                    "label": "进入规划模式",
                    "description": "切换为只读规划；在你批准计划前不会改动代码。",
                    "value": ENTER_APPROVE_VALUE,
                },
                {
                    "label": "留在代理模式",
                    "description": "不进入规划，继续按当前方式实现。",
                    "value": ENTER_DECLINE_VALUE,
                },
            ],
        }
    ]


def exit_plan_questions(locale: str | None = None) -> list[dict[str, object]]:
    if _locale(locale) == "en":
        return [
            {
                "header": "Plan ready",
                "id": EXIT_QUESTION_ID,
                "question": (
                    "The plan is ready for review. What should happen next?"
                ),
                "options": [
                    {
                        "label": "Accept plan (Agent)",
                        "description": (
                            "Leave plan mode and implement with approvals."
                        ),
                        "value": EXIT_ACCEPT_AGENT,
                    },
                    {
                        "label": "Accept plan (YOLO)",
                        "description": (
                            "Leave plan mode and implement with auto-approve."
                        ),
                        "value": EXIT_ACCEPT_YOLO,
                    },
                    {
                        "label": "Revise plan",
                        "description": "Stay in plan mode and refine the plan.",
                        "value": EXIT_REVISE,
                    },
                    {
                        "label": "Exit without implementing",
                        "description": (
                            "Return to agent mode without starting work."
                        ),
                        "value": EXIT_LEAVE,
                    },
                ],
            }
        ]
    return [
        {
            "header": "计划已就绪",
            "id": EXIT_QUESTION_ID,
            "question": "计划已写好，接下来怎么做？",
            "options": [
                {
                    "label": "接受计划（代理）",
                    "description": "退出规划模式，按需批准后开始实现。",
                    "value": EXIT_ACCEPT_AGENT,
                },
                {
                    "label": "接受计划（YOLO）",
                    "description": "退出规划模式，自动批准工具调用并开始实现。",
                    "value": EXIT_ACCEPT_YOLO,
                },
                {
                    "label": "修改计划",
                    "description": "留在规划模式，继续完善计划。",
                    "value": EXIT_REVISE,
                },
                {
                    "label": "退出且不实现",
                    "description": "回到代理模式，暂不开始动手。",
                    "value": EXIT_LEAVE,
                },
            ],
        }
    ]


def _answer_token(answer: dict[str, Any]) -> str:
    for key in ("value", "label", "selected_option"):
        raw = answer.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return ""


def parse_enter_plan_response(response: dict[str, Any]) -> bool | None:
    """Return True/False for approve/decline, or None if dismissed/unknown."""
    answers = response.get("answers")
    if not isinstance(answers, list) or not answers:
        return None
    for answer in answers:
        if not isinstance(answer, dict):
            continue
        qid = str(answer.get("question_id") or answer.get("id") or "")
        if qid and qid != ENTER_QUESTION_ID:
            continue
        token = _answer_token(answer).lower()
        if token in {
            ENTER_APPROVE_VALUE,
            "enter plan mode",
            "enter",
            "进入规划模式",
            "进入",
        }:
            return True
        if token in {
            ENTER_DECLINE_VALUE,
            "stay in agent",
            "stay",
            "decline",
            "no",
            "留在代理模式",
            "留在",
        }:
            return False
        if ("enter" in token and "plan" in token) or "进入" in token:
            return True
        if "stay" in token or "agent" in token or "留在" in token or "代理" in token:
            return False
    return None


def parse_exit_plan_response(response: dict[str, Any]) -> str | None:
    """Return an EXIT_* outcome string, or None if dismissed/unknown."""
    answers = response.get("answers")
    if not isinstance(answers, list) or not answers:
        return None
    for answer in answers:
        if not isinstance(answer, dict):
            continue
        qid = str(answer.get("question_id") or answer.get("id") or "")
        if qid and qid != EXIT_QUESTION_ID:
            continue
        raw = _answer_token(answer)
        token = raw.lower().replace(" ", "_")
        compact = token.replace("(", "").replace(")", "")
        if raw in {
            EXIT_ACCEPT_AGENT,
            EXIT_ACCEPT_YOLO,
            EXIT_REVISE,
            EXIT_LEAVE,
        }:
            return raw
        if token in {EXIT_ACCEPT_AGENT, "accept_agent"} or (
            "accept" in compact
            and "yolo" not in compact
            and ("agent" in compact or "代理" in raw)
        ):
            return EXIT_ACCEPT_AGENT
        if token in {EXIT_ACCEPT_YOLO, "accept_yolo"} or (
            ("accept" in compact or "接受" in raw) and "yolo" in compact
        ):
            return EXIT_ACCEPT_YOLO
        if token in {EXIT_REVISE, "revise"} or "revise" in compact or "修改" in raw:
            return EXIT_REVISE
        if token in {EXIT_LEAVE, "exit_plan", "exit"} or (
            "without implementing" in token.replace("_", " ")
            or "不实现" in raw
            or ("退出" in raw and "接受" not in raw)
        ):
            return EXIT_LEAVE
        if "接受" in raw and "yolo" not in compact:
            return EXIT_ACCEPT_AGENT
    return None


APPROVED_PLAN_MARKER = "The approved plan file is at"


def runtime_thread_id(metadata: dict[str, Any] | None) -> str | None:
    raw = (metadata or {}).get("runtime_thread_id")
    if not isinstance(raw, str):
        return None
    tid = raw.strip()
    if not tid:
        return None
    try:
        user_thread_plan_path(tid)
    except ValueError:
        return None
    return tid


def resolve_plan_file_path(
    working_directory: Any, metadata: dict[str, Any] | None
) -> Path | None:
    """Workbench: ``~/.deepseek/threads/plans/{id}.md``. TUI: workspace plan.md.

    A present-but-invalid thread id does not fall back to the workspace file.
    """
    raw = (metadata or {}).get("runtime_thread_id")
    if isinstance(raw, str) and raw.strip():
        tid = runtime_thread_id(metadata)
        if tid is None:
            return None
        return user_thread_plan_path(tid)
    if working_directory is None:
        return None
    return Path(working_directory) / DOT_DEEPSEEK / "plan.md"


def plan_file_has_content(path: Path | None) -> bool:
    if path is None:
        return False
    try:
        return path.is_file() and bool(path.read_text(encoding="utf-8").strip())
    except OSError:
        return False


def plan_file_exists(working_directory: Any, metadata: dict[str, Any] | None) -> bool:
    """True when a plan has been written this session or on this conversation's file."""
    meta = metadata or {}
    plan_text = meta.get("plan_text") or meta.get("plan")
    if isinstance(plan_text, str) and plan_text.strip():
        return True
    steps = meta.get("plan_steps")
    if isinstance(steps, list) and steps:
        return True
    return plan_file_has_content(resolve_plan_file_path(working_directory, meta))


def build_approved_plan_reminder_body(plan_path: Path) -> str:
    return (
        f"{APPROVED_PLAN_MARKER} {plan_path}.\n"
        "If this plan is relevant to current work and not complete, "
        "continue executing it.\n"
        "If you do not have the current plan content in visible context, "
        "read that file. Never stop because inline plan content was "
        "compacted — the file is the source of truth.\n"
        "Do not mention this reminder to the user."
    )


def is_approved_plan_reminder(message: Any) -> bool:
    text = message.text_content() if hasattr(message, "text_content") else ""
    return APPROVED_PLAN_MARKER in (text or "")


def sync_approved_plan_reminder(
    messages: list[Any],
    *,
    mode: str,
    working_directory: Any,
    metadata: dict[str, Any] | None,
) -> None:
    """Keep a path-only approved-plan pointer after leaving plan mode.

    Workbench only. While still in plan mode, or when the thread has no
    approved plan, drop leftovers. Otherwise inject once until compaction
    replaces history. Never embeds the plan body.
    """
    if runtime_thread_id(metadata) is None:
        return
    approved = bool((metadata or {}).get("approved_plan"))
    if (mode or "").strip() == "plan" or not approved:
        kept = [m for m in messages if not is_approved_plan_reminder(m)]
        if len(kept) != len(messages):
            messages[:] = kept
        return
    if any(is_approved_plan_reminder(m) for m in messages):
        return
    path = resolve_plan_file_path(working_directory, metadata)
    if not plan_file_has_content(path):
        return
    from deepseek_tui.engine import reminders

    messages.append(
        reminders.reminder_message(
            reminders.APPROVED_PLAN, build_approved_plan_reminder_body(path)
        )
    )


class EnterPlanModeTool(ToolSpec):
    def name(self) -> str:
        return ENTER_PLAN_MODE_NAME

    def description(self) -> str:
        return (
            "Proactively enter read-only plan mode before a non-trivial "
            "implementation. Use when the task has multiple valid approaches, "
            "architectural trade-offs, multi-file changes, or unclear "
            "requirements. Requires user consent. Do not use for trivial "
            "one-line fixes or pure research questions."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, object], context: Any) -> ToolResult:
        raise ToolError("enter_plan_mode must be handled by the engine")


class ExitPlanModeTool(ToolSpec):
    def name(self) -> str:
        return EXIT_PLAN_MODE_NAME

    def description(self) -> str:
        return (
            "Signal that the plan is finished and request user approval. "
            "Call only in plan mode after writing the plan with "
            "update_plan. Do not use request_user_input to ask whether the "
            "plan is okay — this tool is that approval request. Do not use "
            "for pure research tasks that do not produce an implementation plan."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, object], context: Any) -> ToolResult:
        raise ToolError("exit_plan_mode must be handled by the engine")
