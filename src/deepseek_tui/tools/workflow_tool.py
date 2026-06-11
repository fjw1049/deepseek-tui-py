"""``workflow`` tool declaration."""

from __future__ import annotations

from typing import Any

from deepseek_tui.tools.base import (
    ApprovalRequirement,
    ToolCapability,
    ToolResult,
    ToolSpec,
)
from deepseek_tui.tools.context import ToolContext


class WorkflowTool(ToolSpec):
    """Run a structured multi-agent workflow in one tool call."""

    def name(self) -> str:
        return "workflow"

    def description(self) -> str:
        return (
            "Execute a structured multi-agent workflow from a JSON Workflow IR "
            "(`spec` object). If the user explicitly asks to use workflow, or "
            "wants orchestrated fan-out/fan-in, phased review, or parallel "
            "exploration, call this tool instead of manually coordinating "
            "`agent_spawn` / `agent_wait`. Do not use it for a single simple "
            "task.\n\n"
            "Pass a complete `spec` with `meta`, `policy`, and `phases` (each "
            "phase has `steps`). Step types: `agent` (one spawn), `fanout` "
            "(parallel per item), `pipeline` (per-item stages), `synthesis` "
            "(merge prior outputs via `{{outputs.<step_id>}}` templates).\n\n"
            "Each `agent` step needs `label` + `prompt`. Each `fanout` step "
            "needs `items` and an `agent` object containing `label_template` "
            "and `prompt_template`, for example: `{type:'fanout', items:[...], "
            "agent:{label_template:'inspect {{item}}', prompt_template:'...'}}`. "
            "Use `fanout` for parallel items — do not spawn many separate "
            "agents manually. Include a `synthesis` step when merging branches. "
            "Sub-agents do not inherit implicit repo context; put paths and "
            "tasks in prompts. Failed steps may be omitted — synthesis must "
            "handle missing outputs.\n\n"
            "Prefer `spec` (Workflow IR JSON). Optional `script` (Pi JS with "
            "`export const meta`) requires `spec.phases` — script bodies are not "
            "executed in Python."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "spec": {
                    "type": "object",
                    "description": (
                        "Workflow IR v1: version, meta {name, description}, "
                        "policy, phases[].steps[]"
                    ),
                },
                "script": {
                    "type": "string",
                    "description": (
                        "Optional Pi-style JS workflow script with "
                        "`export const meta = { name, description }`. "
                        "Must be paired with `spec.phases` (meta from script "
                        "overrides spec.meta when both are present)."
                    ),
                },
            },
            "anyOf": [{"required": ["spec"]}, {"required": ["script", "spec"]}],
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.EXECUTES_CODE, ToolCapability.REQUIRES_APPROVAL]

    def approval_requirement(self) -> ApprovalRequirement:
        return ApprovalRequirement.REQUIRED

    async def execute(self, input_data: dict[str, Any], context: ToolContext) -> ToolResult:
        from deepseek_tui.capabilities.workflow import execute_workflow_tool

        return await execute_workflow_tool(input_data, context)
