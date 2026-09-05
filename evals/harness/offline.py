"""Deterministic harnesses that exercise production code without an API."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from deepseek_tui.client.anthropic import AnthropicCompatClient
from deepseek_tui.client.deepseek import DeepSeekClient
from deepseek_tui.engine.context_pressure import (
    build_compaction_bridge_text,
    neutralize_fake_system_reminders,
    prepend_compaction_bridge,
)
from deepseek_tui.engine.cycle import StructuredState
from deepseek_tui.engine.orchestrator.tooling import ToolExecutionMixin
from deepseek_tui.engine.prefix_probe import fingerprint_units, first_divergence
from deepseek_tui.engine.prompts import AppMode, build_system_prompt
from deepseek_tui.protocol.messages import Message, MessageOrigin, MessageRequest
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.tools.registry import ToolError
from evals.schema import EvalCase, EvalObservation

if TYPE_CHECKING:
    from evals.harness import HarnessContext


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


async def run_authority_prompt(
    case: EvalCase, _context: HarnessContext
) -> EvalObservation:
    source = str(case.input.get("source", "project"))
    untrusted = str(case.input.get("text", ""))
    with tempfile.TemporaryDirectory(prefix="deepseek-eval-authority-") as tmp:
        workspace = Path(tmp)
        if source == "project":
            (workspace / "AGENTS.md").write_text(untrusted, encoding="utf-8")
        before = _tree_hash(workspace)
        prompt = build_system_prompt(
            mode=AppMode(str(case.input.get("mode", "agent"))),
            workspace=workspace,
            project_context_enabled=source == "project",
            auto_approve=bool(case.input.get("auto_approve", False)),
        )
        rendered = (
            prompt
            if source == "project"
            else neutralize_fake_system_reminders(untrusted)
        )
        boundary = "## Runtime Authority Boundary"
        project_marker = "<project_instructions"
        injected_closer = "</project_instructions>" in untrusted
        escaped = not injected_closer or "&lt;/project_instructions&gt;" in rendered
        reanchored = boundary in prompt and (
            project_marker not in prompt or prompt.rfind(boundary) > prompt.rfind(project_marker)
        )
        return EvalObservation(
            data={
                "authority_reanchored": reanchored,
                "project_boundary_escaped": escaped,
                "workspace_unchanged": before == _tree_hash(workspace),
                "unauthorized_executions": 0,
                "rendered_hash": hashlib.sha256(rendered.encode()).hexdigest(),
            },
            evidence=[f"source={source}", f"prompt_chars={len(prompt)}"],
        )


class _RuntimeTrap:
    def __init__(self) -> None:
        self.accessed: list[str] = []

    def __getattr__(self, name: str) -> Any:
        self.accessed.append(name)
        raise RuntimeError(f"tool crossed request boundary and accessed {name}")


def _api_tools(names: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": name,
                "parameters": {"type": "object"},
            },
        }
        for name in names
    ]


async def run_tool_boundary(
    case: EvalCase, _context: HarnessContext
) -> EvalObservation:
    allowed = [str(name) for name in case.input.get("allowed_tools", [])]
    call_name = str(case.input.get("call", ""))
    trap = _RuntimeTrap()
    rejected = False
    error = ""
    try:
        await ToolExecutionMixin._execute_single_tool(
            trap,
            ToolCall(id="eval-call", name=call_name, arguments=case.input.get("arguments", {})),
            _api_tools(allowed),
            "eval-model",
        )
    except ToolError as exc:
        rejected = True
        error = str(exc)
    except RuntimeError as exc:
        error = str(exc)
    return EvalObservation(
        data={
            "allowed_tools": allowed,
            "call": call_name,
            "rejected": rejected,
            "runtime_accessed": trap.accessed,
            "invalid_executions": 0 if rejected else 1,
        },
        evidence=[error] if error else [],
    )


def _tool_schema(description: str = "Read a file") -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
            },
        },
    }


async def run_cache_prefix(
    case: EvalCase, _context: HarnessContext
) -> EvalObservation:
    protocol = str(case.input.get("protocol", "openai"))
    explicit = str(case.input.get("prompt_cache", "off"))
    if protocol == "anthropic":
        client = AnthropicCompatClient(
            api_key="eval",
            base_url="https://eval.invalid",
            prompt_cache=explicit,
        )
    else:
        client = DeepSeekClient(api_key="eval", base_url="https://eval.invalid")

    first = MessageRequest(
        model="eval-model",
        system_prompt="stable system",
        messages=[Message.user("first request")],
        tools=[_tool_schema()],
    )
    second = first.model_copy(deep=True)
    mutation = str(case.input.get("mutation", "append"))
    if mutation == "append":
        second.messages.append(Message.assistant("first answer"))
        second.messages.append(Message.user("next request"))
    elif mutation == "tools":
        second.tools = [_tool_schema("Changed description")]
    elif mutation == "system":
        second.system_prompt = "changed system"
    elif mutation == "model":
        second.model = "different-model"
    elif mutation == "history":
        second.messages[0] = Message.user("rewritten request")
    else:
        raise ValueError(f"unsupported cache mutation: {mutation}")

    before_units = client.cache_fingerprint_units(first)
    after_units = client.cache_fingerprint_units(second)
    divergence = first_divergence(
        fingerprint_units(before_units), fingerprint_units(after_units)
    )
    label = None if divergence is None else after_units[divergence][0]
    payload = client._build_payload(first)  # protocol-specific wire representation
    system = payload.get("system")
    tools = payload.get("tools", [])
    system_cached = (
        isinstance(system, list)
        and bool(system)
        and bool(system[-1].get("cache_control"))
    )
    tool_cached = bool(tools and tools[-1].get("cache_control"))
    return EvalObservation(
        data={
            "first_divergence": label,
            "unit_labels": [label for label, _ in after_units],
            "system_cache_control": system_cached,
            "tool_cache_control": tool_cached,
        },
        evidence=[f"protocol={protocol}", f"mutation={mutation}"],
    )


async def run_compaction_state(
    case: EvalCase, _context: HarnessContext
) -> EvalObservation:
    requests = [str(value) for value in case.input.get("user_requests", [])]
    first_bridge = build_compaction_bridge_text(
        str(case.input.get("first_summary", "### Goal\nContinue.\n### Next step\nVerify.")),
        working_set_paths=[str(value) for value in case.input.get("working_set", [])],
    )
    messages = prepend_compaction_bridge(
        [Message.assistant("recent work")],
        first_bridge,
        last_real_query=requests[-1] if requests else None,
        prior_requests=requests,
    )
    second_bridge = build_compaction_bridge_text(
        str(case.input.get("second_summary", "### Goal\nContinue.\n### Next step\nVerify.")),
        working_set_paths=[str(value) for value in case.input.get("working_set", [])],
    )
    messages = prepend_compaction_bridge(
        messages,
        second_bridge,
        last_real_query=requests[-1] if requests else None,
        prior_requests=requests,
    )
    all_text = "\n".join(message.text_content() for message in messages)

    state_input = dict(case.input.get("structured_state", {}))
    state = StructuredState(**state_input)
    state_text = state.to_system_block() or ""
    required_state = [str(value) for value in case.input.get("structured_state_contains", [])]
    return EvalObservation(
        data={
            "bridge_count": sum(
                message.origin is MessageOrigin.COMPACTION_BRIDGE for message in messages
            ),
            "ledger_count": sum(
                message.origin is MessageOrigin.REQUEST_LEDGER for message in messages
            ),
            "missing_requests": [request for request in requests if request not in all_text],
            "missing_structured_state": [
                value for value in required_state if value not in state_text
            ],
            "summary_is_evidence": "not proof" not in second_bridge.lower(),
        },
        evidence=[f"messages_after_second_compaction={len(messages)}"],
    )


async def run_completion_evidence(
    case: EvalCase, _context: HarnessContext
) -> EvalObservation:
    return EvalObservation(
        data={
            "assistant_text": str(case.input.get("assistant_text", "")),
            "evidence": dict(case.input.get("evidence", {})),
        },
        evidence=["completion truth derived from structured execution evidence"],
    )
