"""Task-scoped browser focus and evidence-backed delivery, owned by the Engine."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from deepseek_tui.tools.registry import ToolCapability, ToolContext, ToolError, ToolResult, ToolSpec

FINALIZATION_TIMEOUT_SECONDS = 60
FINALIZATION_MAX_TOKENS = 4096

CONTROL_TOOLS = {"finish_task", "request_task_tools"}
FOCUS_TOOLS = CONTROL_TOOLS | {
    "browser_use",
    "request_user_input",
    "checklist",
    "CreateGoal",
    "GetGoal",
    "UpdateGoal",
    "SetGoalBudget",
}


@dataclass
class TaskDelivery:
    active: bool = False
    extra_tools: set[str] = field(default_factory=set)
    evidence: set[str] = field(default_factory=set)
    outcome: dict[str, Any] | None = None
    stop_reminded: bool = False
    finalization_attempted: bool = False
    draft_answer: str = ""
    catalog: set[str] = field(default_factory=set)

    def allows(self, name: str) -> bool:
        if self.active and self.stop_reminded:
            return name == "finish_task"
        return not self.active or name in FOCUS_TOOLS | self.extra_tools

    def tools(self, catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            t
            for t in catalog
            if self.allows((t.get("function") or t)["name"])
            and (self.active or (t.get("function") or t)["name"] not in CONTROL_TOOLS)
        ]


def _state(context: ToolContext) -> TaskDelivery:
    state = context.metadata.get("task_delivery")
    if not isinstance(state, TaskDelivery) or not state.active:
        raise ToolError("No active browser task")
    return state


class RequestTaskToolsTool(ToolSpec):
    def name(self) -> str:
        return "request_task_tools"

    def description(self) -> str:
        return (
            "Extend the current task's focused tool set with only the named capabilities needed "
            "for its next stage, e.g. reading a downloaded report. Explain the task dependency. "
            "Use names=[] to list eligible tools. This does not grant authorization, bypass "
            "approval, or override the user's source/method restrictions. Call alone; new tools "
            "are available on the next round."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "names": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
                "reason": {"type": "string", "minLength": 1},
            },
            "required": ["names", "reason"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    def supports_parallel(self) -> bool:
        return False

    async def execute(self, input_data: dict[str, Any], context: ToolContext) -> ToolResult:
        state = _state(context)
        names, reason = input_data.get("names"), input_data.get("reason")
        if (
            not isinstance(names, list)
            or len(names) > 8
            or any(not isinstance(n, str) for n in names)
            or not isinstance(reason, str)
            or not reason.strip()
        ):
            raise ToolError("Supply up to 8 tool names and a non-empty task dependency reason")
        unknown = set(names) - state.catalog
        if unknown:
            raise ToolError(
                "Tools unavailable under the current profile: " + ", ".join(sorted(unknown))
            )
        state.extra_tools.update(names)
        payload = {
            "enabled": sorted(state.extra_tools),
            "reason": reason,
            "eligible": sorted(state.catalog - FOCUS_TOOLS) if not names else [],
            "authorization": "Existing task scope, sandbox and approval policies still apply.",
        }
        return ToolResult(True, json.dumps(payload, ensure_ascii=False))


class FinishTaskTool(ToolSpec):
    def name(self) -> str:
        return "finish_task"

    def description(self) -> str:
        return (
            "Submit the actual final answer for the whole user task, not an intermediate browser "
            "step. Call alone. status=completed requires evidence and no remaining work. "
            "Use partial/blocked with concrete remaining items when unable to finish. Evidence "
            "references are tool:<tool_call_id> from successful results in this task. Explain "
            "what those results establish in answer; dispatch alone is not business success. "
            "The Engine delivers answer verbatim after its existing stop checks."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["completed", "partial", "blocked"]},
                "answer": {"type": "string", "minLength": 1},
                "evidence": {"type": "array", "items": {"type": "string"}},
                "remaining": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["status", "answer", "evidence", "remaining"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    def supports_parallel(self) -> bool:
        return False

    async def execute(self, input_data: dict[str, Any], context: ToolContext) -> ToolResult:
        state = _state(context)
        status, answer = input_data.get("status"), input_data.get("answer")
        evidence, remaining = input_data.get("evidence"), input_data.get("remaining")
        if (
            not isinstance(status, str)
            or status not in {"completed", "partial", "blocked"}
            or not isinstance(answer, str)
            or not answer.strip()
        ):
            raise ToolError("Supply a final status and a non-empty actual answer")
        if any(
            not isinstance(v, list) or any(not isinstance(x, str) or not x.strip() for x in v)
            for v in (evidence, remaining)
        ):
            raise ToolError("evidence and remaining must be arrays of non-empty strings")
        if set(evidence) - state.evidence:
            raise ToolError(
                "Unknown evidence reference; use tool:<id> from a successful task result"
            )
        browser = context.metadata.get("browser_service")
        thread_id = str(context.metadata.get("runtime_thread_id"))
        run = getattr(browser, "runs", {}).get(thread_id)
        # Closing/recovering a browser must not erase an unresolved submission.
        browser_state = (
            browser.state(thread_id) if callable(getattr(browser, "state", None)) else {}
        )
        unresolved = browser_state.get("unresolved") or (run.unresolved if run else {})
        if run and (run.assistance or run.owner != "agent"):
            raise ToolError("Wait for the user to return control before finishing")
        if status == "completed":
            if not evidence or remaining:
                raise ToolError("Completed requires evidence and no remaining work")
            if unresolved:
                raise ToolError(
                    "Unresolved browser operations prevent claiming completion; "
                    "inspect or report partial"
                )
        elif not remaining:
            raise ToolError("Partial/blocked requires concrete remaining work or blockers")
        state.outcome = {
            "status": status,
            "answer": answer,
            "evidence": evidence,
            "remaining": remaining,
        }
        return ToolResult(
            True,
            json.dumps(state.outcome, ensure_ascii=False),
            metadata={"task_outcome": state.outcome},
        )
