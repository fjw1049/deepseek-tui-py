"""Opt-in real-model decision harness. Tools are observed, never executed."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

from deepseek_tui.client.factory import build_llm_client
from deepseek_tui.client.pricing import calculate_turn_cost_estimate_from_usage
from deepseek_tui.config.loader import ConfigLoader
from deepseek_tui.engine.prompts import AppMode, build_system_prompt
from deepseek_tui.engine.turn import prepare_turn_for_model
from deepseek_tui.protocol.messages import Message, MessageRequest, Role, ToolUseBlock
from deepseek_tui.protocol.responses import (
    StreamDone,
    StreamTextDelta,
    StreamToolCallComplete,
)
from deepseek_tui.tools.registry import build_default_registry
from evals.schema import EvalCase, EvalObservation

if TYPE_CHECKING:
    from evals.harness import HarnessContext


def _workspace(context: HarnessContext) -> Path:
    return Path(context.workspace).resolve()


def _messages(case: EvalCase, workspace: Path) -> list[Message]:
    output: list[Message] = []
    for item in case.input.get("messages", []):
        role = Role(str(item.get("role", "user")))
        text = str(item.get("content", ""))
        if role is Role.USER:
            text = prepare_turn_for_model(text, workspace=workspace).model_text
            output.append(Message.user(text))
        elif role is Role.ASSISTANT:
            if text:
                output.append(Message.assistant(text))
            calls = [
                ToolUseBlock(
                    id=str(call.get("id", f"eval-call-{index}")),
                    name=str(call["name"]),
                    input=dict(call.get("arguments", {})),
                )
                for index, call in enumerate(item.get("tool_calls", []))
            ]
            if calls:
                output.append(Message.assistant_with_tools(calls))
        elif role is Role.SYSTEM:
            output.append(Message.system(text))
        elif role is Role.TOOL:
            output.append(
                Message.tool_result(
                    str(item.get("tool_use_id", "eval-tool")),
                    text,
                    is_error=bool(item.get("is_error", False)),
                )
            )
    return output


async def run_live_decision(
    case: EvalCase, context: HarnessContext
) -> EvalObservation:
    workspace = _workspace(context)
    cfg = ConfigLoader().load(
        provider=context.provider,
        model=context.model,
        workspace=workspace,
        no_project_config=not bool(case.input.get("project_context", False)),
    )
    mode = AppMode(str(case.input.get("mode", "agent")))
    registry = build_default_registry(cfg, mode=mode.value)
    tools = registry.to_api_tools()
    system_prompt = build_system_prompt(
        mode=mode,
        workspace=workspace,
        project_context_enabled=bool(case.input.get("project_context", False)),
    )
    request = MessageRequest(
        model=cfg.model or cfg.default_text_model,
        messages=_messages(case, workspace),
        system_prompt=system_prompt,
        tools=tools,
        max_tokens=min(
            int(case.input.get("max_tokens", context.max_output_tokens)),
            context.max_output_tokens,
        ),
        temperature=float(case.input.get("temperature", 0.0)),
    )
    client = build_llm_client(cfg)
    text = ""
    tool_calls = []
    usage = None
    try:
        async for event in client.stream_chat_completion(request):
            if isinstance(event, StreamTextDelta):
                text += event.text
            elif isinstance(event, StreamToolCallComplete):
                tool_calls.append(event.tool_call)
            elif isinstance(event, StreamDone) and event.usage is not None:
                usage = event.usage
    finally:
        await client.close()

    usage_data: dict[str, int | float] = {}
    if usage is not None:
        usage_data = {
            "input_tokens": usage.total_input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_read_input_tokens": usage.cache_read_input_tokens,
            "cache_creation_input_tokens": usage.cache_creation_input_tokens,
        }
        cost = calculate_turn_cost_estimate_from_usage(request.model, usage)
        if cost is not None:
            usage_data["cost_usd"] = cost.usd

    tool_names = [call.name for call in tool_calls]
    shell_commands = [
        str(call.arguments.get("command", ""))
        for call in tool_calls
        if call.name == "exec_shell"
    ]
    return EvalObservation(
        data={
            "assistant_text": text,
            "tool_names": tool_names,
            "shell_commands": shell_commands,
            "system_prompt_leaked": _leaked_prompt_fragment(system_prompt, text),
            "evidence": dict(case.input.get("evidence", {})),
        },
        evidence=[
            f"model={request.model}",
            f"system_hash={hashlib.sha256(system_prompt.encode()).hexdigest()}",
        ],
        usage=usage_data,
    )


def _leaked_prompt_fragment(system_prompt: str, text: str, window: int = 120) -> bool:
    if len(system_prompt) <= window:
        return system_prompt in text
    step = window // 2
    return any(
        system_prompt[index : index + window] in text
        for index in range(0, len(system_prompt) - window, step)
    )


async def run_live_cache(
    case: EvalCase, context: HarnessContext
) -> EvalObservation:
    workspace = _workspace(context)
    cfg = ConfigLoader().load(
        provider=context.provider,
        model=context.model,
        workspace=workspace,
        no_project_config=True,
    )
    model = cfg.model or cfg.default_text_model
    requested_rounds = int(case.input.get("rounds", 3))
    rounds = min(requested_rounds, context.remaining_live_requests)
    if rounds < 2:
        raise ValueError("live cache eval needs at least two remaining request slots")
    stable_prompt = str(case.input.get("stable_prompt", "cache prefix "))
    target_chars = int(case.input.get("stable_prompt_chars", 16_000))
    stable_prompt = (stable_prompt * (target_chars // max(1, len(stable_prompt)) + 1))[
        :target_chars
    ]
    client = build_llm_client(cfg)
    messages: list[Message] = []
    cache_reads = 0
    cache_creations = 0
    input_tokens = 0
    output_tokens = 0
    cost_usd = 0.0
    try:
        for index in range(rounds):
            messages.append(Message.user(f"Round {index + 1}: reply with OK only."))
            request = MessageRequest(
                model=model,
                messages=messages,
                system_prompt=stable_prompt,
                max_tokens=min(16, context.max_output_tokens),
                temperature=0.0,
            )
            answer = ""
            usage = None
            async for event in client.stream_chat_completion(request):
                if isinstance(event, StreamTextDelta):
                    answer += event.text
                elif isinstance(event, StreamDone) and event.usage is not None:
                    usage = event.usage
            messages.append(Message.assistant(answer or "OK"))
            if usage is not None:
                cache_reads += usage.cache_read_input_tokens
                cache_creations += usage.cache_creation_input_tokens
                input_tokens += usage.total_input_tokens
                output_tokens += usage.output_tokens
                cost = calculate_turn_cost_estimate_from_usage(model, usage)
                if cost is not None:
                    cost_usd += cost.usd
    finally:
        await client.close()
    return EvalObservation(
        data={"first_divergence": None, "rounds": rounds},
        evidence=[f"model={model}", f"stable_prompt_chars={len(stable_prompt)}"],
        usage={
            "requests": rounds,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_input_tokens": cache_reads,
            "cache_creation_input_tokens": cache_creations,
            "cost_usd": cost_usd,
        },
    )
