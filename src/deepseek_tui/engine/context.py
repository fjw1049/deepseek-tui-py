"""Context management for turn loop.

Mirrors `crates/tui/src/core/engine/context.rs`
"""

from __future__ import annotations

from deepseek_tui.protocol.messages import Message

# Context window budget calculation
# DeepSeek chat model: 128k total context
# Reserve 16k for output tokens
MODEL_CONTEXT_WINDOWS = {
    "deepseek-chat": 128000,
    "deepseek-reasoner": 128000,
}


def context_input_budget(model: str, max_output_tokens: int) -> int | None:
    """Calculate input token budget for a model.

    Args:
        model: Model name
        max_output_tokens: Max tokens reserved for output

    Returns:
        Input token budget, or None if model unknown
    """
    total = MODEL_CONTEXT_WINDOWS.get(model)
    if total is None:
        return None
    return total - max_output_tokens


def estimated_input_tokens(messages: list[Message]) -> int:
    """Rough estimate of input tokens from message list.

    Uses ~4 characters per token as heuristic.
    """
    import json

    total_chars = 0
    for m in messages:
        total_chars += len(json.dumps(m.model_dump()))
    return max(1, total_chars // 4)
