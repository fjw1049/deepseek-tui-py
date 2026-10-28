"""Evidence-backed delivery for UI tasks and the browser's task focus, owned by the Engine."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from deepseek_tui.surfaces import surface_tools
from deepseek_tui.tools.registry import ToolCapability, ToolContext, ToolError, ToolResult, ToolSpec

FINALIZATION_TIMEOUT_SECONDS = 60
# A round after computer use carries screenshots, which take the vision helper longer.
CUA_FINALIZATION_TIMEOUT_SECONDS = 180
CUA_EVIDENCE_HINT = " After computer use, a cua_observe result is the evidence to cite."
FINALIZATION_MAX_TOKENS = 4096

CONTROL_TOOLS = {"finish_task", "request_task_tools"}
# Every UI surface stays usable in the phase, so one task can span web and desktop.
FOCUS_TOOLS = CONTROL_TOOLS | surface_tools() | {
    "request_user_input",
    "checklist",
    "read_file",
    "file_search",
    "grep_files",
    "exec_shell",
    "CreateGoal",
    "GetGoal",
    "UpdateGoal",
    "SetGoalBudget",
}


@dataclass
class TaskDelivery:
    # A UI task is under way: the turn ends through finish_task.
    active: bool = False
    # The task also narrows the tool set (surfaces with focus=True).
    focused: bool = False
    browser_used: bool = False
    extra_tools: set[str] = field(default_factory=set)
    evidence: set[str] = field(default_factory=set)
    cua_used: bool = False
    # Computer-use code ran; observing alone needs no verification contract.
    cua_acted: bool = False
    cua_verification_target: dict[str, str] | None = None
    cua_observation_evidence: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Evidence predating an uncertain desktop action cannot verify its outcome.
    cua_failed_evidence: set[str] | None = None
    outcome: dict[str, Any] | None = None
    # A stop without a tool call first gets one round, with all tools, to take its next step.
    continue_nudged: bool = False
    stop_reminded: bool = False
    finalization_rounds: int = 0
    catalog: set[str] = field(default_factory=set)

    def remember_evidence(self, reference: str, metadata: dict[str, Any]) -> None:
        self.evidence.add(reference)
        observation = metadata.get("cua_observation")
        if isinstance(observation, dict) and metadata.get("cua_verifies_target", False):
            self.cua_observation_evidence[reference] = observation

    def finalizing(self) -> frozenset[str]:
        # finish_task requires a fresh observation after computer use; keep the read-only
        # observation tool, or that completion could never be supplied.
        return frozenset({"finish_task", "cua_observe"} if self.cua_used else {"finish_task"})

    def finalization_exhausted(self) -> bool:
        # Allow one failed observation, its retry, and the final submission.
        return self.finalization_rounds >= (3 if self.cua_used else 1)

    def allows(self, name: str) -> bool:
        if self.active and self.stop_reminded:
            return name in self.finalizing()
        return not self.focused or name in FOCUS_TOOLS | self.extra_tools

    def tools(self, catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # Advertise the same capabilities that execution permits.
        if self.active and self.stop_reminded:
            allowed = self.finalizing()
            return [t for t in catalog if (t.get("function") or t)["name"] in allowed]
        if self.focused:
            return [t for t in catalog if self.allows((t.get("function") or t)["name"])]
        names = {(t.get("function") or t)["name"] for t in catalog}
        # Where a UI surface is offered, the controls stay listed: adding them at the first UI
        # call changed the tool list mid-task and voided the prefix cache twice per task.
        if self.active or names & surface_tools():
            return list(catalog)
        return [t for t in catalog if (t.get("function") or t)["name"] not in CONTROL_TOOLS]


def _state(context: ToolContext) -> TaskDelivery:
    state = context.metadata.get("task_delivery")
    if not isinstance(state, TaskDelivery) or not state.active:
        raise ToolError(
            "No UI task is open in this turn. Answer the user directly in text, without "
            "finish_task or request_task_tools."
        )
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
                "names": {
                    "type": "array", "items": {"type": "string"}, "maxItems": 8,
                    "description": "Tool names to enable for this task; [] lists eligible tools.",
                },
                "reason": {
                    "type": "string", "minLength": 1,
                    "description": "Concrete task dependency that needs these tools.",
                },
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
            "Only for a turn that operated a UI surface (browser_use or cua_js); otherwise "
            "answer directly. Submit the actual final answer for the whole user task, not an "
            "intermediate step. "
            "Call alone. status=completed requires evidence and no remaining work. "
            "Use partial/blocked with concrete remaining items when unable to finish. Evidence "
            "references must copy evidence_ref from successful tool results, never action_id "
            "or observation_id. Explain "
            "what those results establish in answer; dispatch alone is not business success. "
            "After running cua_js, cite a fresh cua_observe result and provide verification "
            "linking each claim to supporting evidence; state the limitations in answer. "
            "Report only observed facts, not untested internal behavior. "
            "The Engine delivers answer verbatim after its existing stop checks."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string", "enum": ["completed", "partial", "blocked"],
                    "description": "completed needs evidence and no remaining work.",
                },
                "answer": {
                    "type": "string", "minLength": 1,
                    "description": "The actual final answer for the user, delivered verbatim.",
                },
                "evidence": {
                    "type": "array", "items": {"type": "string"},
                    "description": "tool:<tool_call_id> references to successful task results.",
                },
                "remaining": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Unfinished work or blockers; required for partial/blocked.",
                },
                "verification": {
                    "type": "array",
                    "description": "Required for completed tasks that ran cua_js. Match each "
                        "conclusion to observed evidence. Disclose incomplete reads and "
                        "untested behavior; one successful example cannot verify all rules.",
                    "items": {"type": "object", "properties": {
                        "claim": {"type": "string", "minLength": 1},
                        "evidence": {"type": "array", "items": {"type": "string"}},
                        "limitations": {"type": "array", "items": {"type": "string"}},
                    }, "required": ["claim", "evidence", "limitations"]},
                },
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
                "Unknown evidence reference; copy evidence_ref, not action_id or observation_id. "
                "Available references: " + json.dumps(sorted(state.evidence)) +
                ". Choose only results supporting the answer; "
                "use partial/blocked for unverified work."
                + (CUA_EVIDENCE_HINT if state.cua_used else "")
            )
        browser = context.metadata.get("browser_service") if state.browser_used else None
        thread_id = str(context.metadata.get("runtime_thread_id"))
        run = getattr(browser, "runs", {}).get(thread_id)
        # Closing/recovering a browser must not erase an unresolved submission.
        browser_state = (
            browser.state(thread_id) if callable(getattr(browser, "state", None)) else {}
        )
        unresolved = browser_state.get("unresolved") or (run.unresolved if run else {})
        if run and run.assistance:
            raise ToolError("Wait for the user to return control before finishing")
        if run and run.owner != "agent" and status == "completed":
            # Reporting the blocker must stay possible while the user holds the browser.
            raise ToolError(
                "The user controls the browser; report partial/blocked or request control first"
            )
        if status == "completed":
            if (browser_state.get("dialog") or browser_state.get("file_chooser")
                    or (run and (getattr(run, "pending_action", None)
                                 or getattr(run, "pending_input", None)))):
                raise ToolError(
                    "Resolve the pending browser interaction before claiming completion")
            if not evidence or remaining:
                raise ToolError("Completed requires evidence and no remaining work."
                                + (CUA_EVIDENCE_HINT if state.cua_used and not evidence else ""))
            if state.cua_used:
                observations = set(evidence) & state.cua_observation_evidence.keys()
                if not observations:
                    raise ToolError("Completion needs a fresh cua_observe observation of the "
                                    "operated target after the last CUA code execution.")
                if all(any(not c["matched"] for c in
                           state.cua_observation_evidence[ref].get("expectations", []))
                       for ref in observations):
                    raise ToolError("The expected result is not verified. Inspect again or "
                                    "report partial/blocked with the remaining work.")
                session = context.metadata.get("cua_session")
                if session and (session.unresolved or session.outside_change
                                or session.reset_reason):
                    raise ToolError("Computer-use state is unresolved or changed. Inspect with "
                                    "cua_observe; report partial/blocked until resolved.")
                if state.cua_acted:
                    checks = input_data.get("verification")
                    if not isinstance(checks, list) or not checks:
                        raise ToolError("Supply verification linking each conclusion to its "
                                        "observed evidence, including limitations, or report "
                                        "partial/blocked.")
                    for check in checks:
                        if not isinstance(check, dict):
                            raise ToolError("Each verification must be an object")
                        claim, refs, limits = (
                            check.get(k) for k in ("claim", "evidence", "limitations"))
                        if (not isinstance(claim, str) or not claim.strip()
                                or not isinstance(refs, list) or not refs
                                or any(not isinstance(ref, str) or ref not in evidence
                                       for ref in refs)
                                or not isinstance(limits, list)
                                or any(not isinstance(s, str) or not s.strip() for s in limits)):
                            raise ToolError("Verification needs a claim, its limitations, and "
                                            "supporting references selected in evidence.")
                        if any(not state.cua_observation_evidence[ref].get("complete", False)
                               for ref in refs if ref in observations) and not limits:
                            raise ToolError("An incomplete observation needs explicit limitations "
                                            "in the answer; it cannot establish a complete result.")
                    if not any(observations.intersection(check["evidence"]) for check in checks):
                        raise ToolError("Verification must use the fresh observation evidence.")
            if (state.cua_failed_evidence is not None
                    and not (set(evidence) - state.cua_failed_evidence)):
                raise ToolError(
                    "CUA outcome needs verification after the failed call. Observe or check "
                    "the actual result, cite fresh evidence, or report partial/blocked. "
                    "Resetting the connection does not verify the outcome."
                )
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
        if state.cua_acted and status == "completed":
            state.outcome["verification"] = input_data["verification"]
        return ToolResult(
            True,
            json.dumps(state.outcome, ensure_ascii=False),
            metadata={"task_outcome": state.outcome},
        )
