"""RLM turn loop driver.

Mirrors ``crates/tui/src/rlm/turn.rs`` (964 LOC). The driver:

1. Stages ``context`` into the REPL namespace (no temp file — we're
   in-process so the string is just a dict entry).
2. For up to :data:`MAX_RLM_ITERATIONS` iterations, asks the root LLM
   for a ``repl`` block, executes it in :class:`ReplRuntime`, and feeds
   metadata back into the next request.
3. Terminates on ``FINAL(...)``, exhaustion, or repeated NoCode rounds.

Sub-LLM helpers (``llm_query`` etc.) are wired through async callbacks
the caller supplies. The driver is the only thing that bridges the
sync ``exec()`` world with the async LLM client.
"""

from __future__ import annotations

import asyncio
import enum
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from deepseek_tui.client.base import LLMClient
from deepseek_tui.protocol.messages import Message, Role, TextBlock
from deepseek_tui.protocol.requests import MessageRequest
from deepseek_tui.protocol.responses import (
    StreamDone,
    StreamError,
    StreamTextDelta,
    Usage,
)
from deepseek_tui.tools.rlm.prompt import rlm_system_prompt
from deepseek_tui.tools.rlm.repl import ReplRuntime, build_sub_llm_helpers

_LOG = logging.getLogger(__name__)

MAX_RLM_ITERATIONS: int = 25
MAX_CONSECUTIVE_NO_CODE: int = 3
ROOT_MAX_TOKENS: int = 4096
ROOT_TEMPERATURE: float = 0.3
STDOUT_METADATA_PREVIEW_LEN: int = 800
PROMPT_PREVIEW_LEN: int = 500
# Rust intentionally removed the fixed wall-clock cap (turn_timeout() → None)
# to allow long-running RLM turns to complete. We follow suit.
TURN_TIMEOUT_SECS: float | None = None
MAX_HISTORY_MESSAGES: int = 20


class RlmTermination(str, enum.Enum):
    """Mirror Rust ``RlmTermination`` (turn.rs:48)."""

    FINAL = "final"
    NO_CODE = "no_code"
    EXHAUSTED = "exhausted"
    ERROR = "error"


@dataclass(slots=True)
class RlmRoundTrace:
    """Mirror Rust ``RlmRoundTrace`` (turn.rs:65)."""

    round: int
    code_summary: str
    stdout_preview: str
    had_error: bool
    rpc_count: int
    elapsed_ms: int


@dataclass(slots=True)
class RlmUsage:
    """Accumulated token usage across root + child LLM calls."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    def add(self, usage: Usage | None) -> None:
        if usage is None:
            return
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.cache_read_input_tokens += usage.cache_read_input_tokens
        self.cache_creation_input_tokens += usage.cache_creation_input_tokens


@dataclass(slots=True)
class RlmTurnResult:
    """Mirror Rust ``RlmTurnResult`` (turn.rs:76)."""

    answer: str
    iterations: int
    duration_secs: float
    error: str | None
    termination: RlmTermination
    trace: list[RlmRoundTrace] = field(default_factory=list)
    total_rpcs: int = 0
    usage: RlmUsage = field(default_factory=RlmUsage)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def run_rlm_turn(
    *,
    client: LLMClient,
    model: str,
    prompt: str,
    root_prompt: str | None,
    child_model: str,
    max_depth: int,
) -> RlmTurnResult:
    """Run a full RLM turn.

    Mirror Rust ``run_rlm_turn_with_root`` (turn.rs:115). ``client`` is
    used for *both* the root LLM call and the sub-LLM bridge. Recursion
    into ``rlm_query`` is bounded by ``max_depth``; once it hits zero
    the helper degrades to a plain ``llm_query``.
    """
    start = time.monotonic()
    helpers_runtime_ref: list[ReplRuntime] = [None]  # type: ignore[list-item]
    usage_acc = RlmUsage()

    sync_run = _make_sync_run(asyncio.get_running_loop())

    async def _llm_one(
        p: str, m: str | None, mt: int | None, s: str | None
    ) -> str:
        text, usage = await _unary_completion(
            client,
            model=m or child_model,
            prompt=p,
            system=s,
            max_tokens=mt,
        )
        usage_acc.add(usage)
        return text

    async def _llm_batch(prompts: list[str], m: str | None) -> list[str]:
        return await _gather_strings(
            [_llm_one(p, m, None, None) for p in prompts]
        )

    async def _rlm_one(p: str, m: str | None) -> str:
        if max_depth <= 0:
            return await _llm_one(p, m, None, None)
        sub = await run_rlm_turn(
            client=client,
            model=model,
            prompt=p,
            root_prompt=None,
            child_model=child_model,
            max_depth=max_depth - 1,
        )
        usage_acc.add(
            Usage(
                input_tokens=sub.usage.input_tokens,
                output_tokens=sub.usage.output_tokens,
                cache_read_input_tokens=sub.usage.cache_read_input_tokens,
                cache_creation_input_tokens=sub.usage.cache_creation_input_tokens,
            )
        )
        return sub.answer or (sub.error or "")

    async def _rlm_batch(prompts: list[str], m: str | None) -> list[str]:
        return await _gather_strings([_rlm_one(p, m) for p in prompts])

    helpers = build_sub_llm_helpers(
        helpers_runtime_ref,
        sync_run=sync_run,
        llm_one=_llm_one,
        llm_batch=_llm_batch,
        rlm_one=_rlm_one,
        rlm_batch=_rlm_batch,
    )

    runtime = ReplRuntime.spawn(prompt, helpers)
    helpers_runtime_ref[0] = runtime

    system = rlm_system_prompt()
    messages: list[Message] = [
        _build_metadata_message(prompt, root_prompt, 0, None, None)
    ]

    trace: list[RlmRoundTrace] = []
    total_rpcs = 0
    consecutive_no_code = 0

    for iteration in range(MAX_RLM_ITERATIONS):
        if TURN_TIMEOUT_SECS is not None and time.monotonic() - start > TURN_TIMEOUT_SECS:
            return RlmTurnResult(
                answer="",
                iterations=iteration,
                duration_secs=time.monotonic() - start,
                error=f"RLM turn timed out after {TURN_TIMEOUT_SECS:.0f}s",
                termination=RlmTermination.ERROR,
                trace=trace,
                total_rpcs=total_rpcs,
                usage=usage_acc,
            )

        try:
            response_text, root_usage = await _request_root_completion(
                client, model=model, system=system, messages=messages
            )
            usage_acc.add(root_usage)
        except Exception as exc:  # noqa: BLE001
            _LOG.exception("RLM root LLM call failed")
            return RlmTurnResult(
                answer="",
                iterations=iteration + 1,
                duration_secs=time.monotonic() - start,
                error=f"Root LLM call failed: {exc}",
                termination=RlmTermination.ERROR,
                trace=trace,
                total_rpcs=total_rpcs,
                usage=usage_acc,
            )

        # Top-level FINAL detection.
        final_val = parse_text_final(response_text)
        if final_val is not None:
            if total_rpcs == 0:
                consecutive_no_code += 1
                if consecutive_no_code >= MAX_CONSECUTIVE_NO_CODE:
                    return RlmTurnResult(
                        answer=final_val,
                        iterations=iteration + 1,
                        duration_secs=time.monotonic() - start,
                        error=None,
                        termination=RlmTermination.NO_CODE,
                        trace=trace,
                        total_rpcs=total_rpcs,
                        usage=usage_acc,
                    )
                messages.append(_assistant(response_text))
                messages.append(_user(_NO_RPC_REMINDER))
                continue
            return RlmTurnResult(
                answer=final_val,
                iterations=iteration + 1,
                duration_secs=time.monotonic() - start,
                error=None,
                termination=RlmTermination.FINAL,
                trace=trace,
                total_rpcs=total_rpcs,
                usage=usage_acc,
            )

        code = extract_repl_code(response_text)
        if code is None:
            consecutive_no_code += 1
            if consecutive_no_code >= MAX_CONSECUTIVE_NO_CODE:
                return RlmTurnResult(
                    answer=response_text,
                    iterations=iteration + 1,
                    duration_secs=time.monotonic() - start,
                    error=(
                        "RLM: model failed to emit ```repl after "
                        f"{MAX_CONSECUTIVE_NO_CODE} consecutive rounds"
                    ),
                    termination=RlmTermination.NO_CODE,
                    trace=trace,
                    total_rpcs=total_rpcs,
                    usage=usage_acc,
                )
            messages.append(_assistant(response_text))
            messages.append(_user(_NO_FENCE_REMINDER))
            continue

        consecutive_no_code = 0
        round_result = await _run_round_offthread(runtime, code)
        total_rpcs += round_result.rpc_count

        stdout_preview = _truncate(round_result.stdout.strip(), STDOUT_METADATA_PREVIEW_LEN)
        trace.append(
            RlmRoundTrace(
                round=iteration + 1,
                code_summary=_summarize_code(code),
                stdout_preview=stdout_preview,
                had_error=round_result.has_error,
                rpc_count=round_result.rpc_count,
                elapsed_ms=int(round_result.elapsed * 1000),
            )
        )

        if round_result.final_value is not None:
            return RlmTurnResult(
                answer=round_result.final_value,
                iterations=iteration + 1,
                duration_secs=time.monotonic() - start,
                error=None,
                termination=RlmTermination.FINAL,
                trace=trace,
                total_rpcs=total_rpcs,
                usage=usage_acc,
            )

        messages.append(_assistant(f"```repl\n{code}\n```"))
        messages.append(
            _build_metadata_message(prompt, root_prompt, iteration + 1, code, stdout_preview)
        )

        if len(messages) > MAX_HISTORY_MESSAGES:
            kept = [messages[0]]
            kept.extend(messages[-(MAX_HISTORY_MESSAGES - 1) :])
            messages = kept

    return RlmTurnResult(
        answer="",
        iterations=MAX_RLM_ITERATIONS,
        duration_secs=time.monotonic() - start,
        error=f"RLM loop exhausted after {MAX_RLM_ITERATIONS} iterations without FINAL",
        termination=RlmTermination.EXHAUSTED,
        trace=trace,
        total_rpcs=total_rpcs,
        usage=usage_acc,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_REPL_FENCE_RE = re.compile(
    r"```(?:repl|python|py)\r?\n(?P<code>.*?)\r?\n```",
    re.DOTALL,
)
_TEXT_FINAL_RE = re.compile(r"^\s*FINAL\((?P<arg>.*)\)\s*$", re.MULTILINE | re.DOTALL)


def extract_repl_code(text: str) -> str | None:
    """Return the first ``repl``/``python`` fenced block, if any.

    Mirror Rust ``extract_repl_code`` (turn.rs:658).
    """
    match = _REPL_FENCE_RE.search(text)
    if match is None:
        return None
    return match.group("code")


def parse_text_final(text: str) -> str | None:
    """Return the inner string of a top-level ``FINAL(...)`` if present.

    Mirror Rust ``parse_text_final``. Recognises:

        FINAL("answer")
        FINAL('answer')
        FINAL(answer_var)         → falls through (caller must run code)
    """
    match = _TEXT_FINAL_RE.search(text)
    if match is None:
        return None
    arg = match.group("arg").strip()
    if not arg:
        return None
    if (arg.startswith('"') and arg.endswith('"')) or (
        arg.startswith("'") and arg.endswith("'")
    ):
        return arg[1:-1]
    return None


_NO_RPC_REMINDER = (
    "You called FINAL(...) without ever running a ```repl block. "
    "That defeats the recursive language model — you're guessing from "
    "the preview alone. Emit a ```repl block now that uses `llm_query`, "
    "`llm_query_batched`, or `rlm_query` against `context` to actually "
    "compute the answer."
)
_NO_FENCE_REMINDER = (
    "Reminder: emit Python inside a ```repl … ``` fence. Use `llm_query` "
    "/ `llm_query_batched` / `rlm_query` to process `context` and call "
    "`FINAL(value)` when done."
)


def _summarize_code(code: str) -> str:
    """Mirror Rust ``summarize_code`` (turn.rs:634)."""
    lines = code.splitlines()
    if len(lines) <= 8:
        return code
    head = "\n".join(lines[:4])
    tail = "\n".join(lines[-4:])
    return f"{len(lines)} lines:\n{head}\n…\n{tail}"


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _build_metadata_message(
    prompt: str,
    root_prompt: str | None,
    iteration: int,
    previous_code: str | None,
    previous_stdout: str | None,
) -> Message:
    """Mirror Rust ``build_metadata_message`` (turn.rs:563)."""
    parts: list[str] = [
        f"## REPL state (round {iteration})",
        "",
    ]
    if root_prompt and root_prompt.strip():
        parts.extend(
            [
                "**Original task** (re-shown every round)",
                f"> {_truncate(root_prompt.strip(), 600)}",
                "",
            ]
        )
    parts.extend(
        [
            "**`context`** — the long input lives in the REPL only",
            f"- Length: {len(prompt)} chars",
            f'- Preview: "{_truncate(prompt, PROMPT_PREVIEW_LEN)}"',
            "",
            "**REPL helpers** (use inside ```repl blocks)",
            "- `context` / `ctx`                       — the full input string",
            "- `len(context)` / `context[a:b]` / `context.splitlines()` — slice it",
            "- `llm_query(prompt, model=None)`        — one-shot child LLM",
            "- `llm_query_batched([p1, p2, ...])`     — concurrent fan-out",
            "- `rlm_query(prompt, model=None)`        — recursive sub-RLM",
            "- `rlm_query_batched([p1, p2, ...])`     — concurrent recursive sub-RLMs",
            "- `chunk_context(max_chars=20000, overlap=0)` — full-coverage chunks",
            "- `chunk_coverage(chunks)`              — coverage report for chunk_context output",
            "- `SHOW_VARS()`                          — list user variables",
            "- `repl_set(name, value)` / `repl_get(name)` — explicit store",
            "- `FINAL(value)`                         — end the loop with this answer",
            "- `FINAL_VAR(name)`                      — end the loop with a variable's value",
            "",
        ]
    )
    if iteration > 0:
        parts.append("**Previous round**")
        if previous_code is not None:
            parts.append(f"- Code: {_summarize_code(previous_code)}")
        if previous_stdout is not None:
            cleaned = previous_stdout.strip()
            parts.append(
                f'- Stdout preview: "{cleaned}"' if cleaned else "- Stdout: (empty)"
            )
    return _user("\n".join(parts))


def _assistant(text: str) -> Message:
    return Message(role=Role.ASSISTANT, content=[TextBlock(text=text)])


def _user(text: str) -> Message:
    return Message(role=Role.USER, content=[TextBlock(text=text)])


async def _request_root_completion(
    client: LLMClient,
    *,
    model: str,
    system: str,
    messages: list[Message],
) -> tuple[str, Usage | None]:
    request = MessageRequest(
        model=model,
        messages=list(messages),
        system_prompt=system,
        max_tokens=ROOT_MAX_TOKENS,
        temperature=ROOT_TEMPERATURE,
        top_p=0.9,
        stream=True,
    )
    parts: list[str] = []
    usage: Usage | None = None
    async for event in client.stream_with_retry(request):
        if isinstance(event, StreamTextDelta):
            parts.append(event.text)
        elif isinstance(event, StreamError) and not event.retryable:
            raise RuntimeError(event.message)
        elif isinstance(event, StreamDone):
            usage = event.usage
    return "".join(parts).strip(), usage


async def _unary_completion(
    client: LLMClient,
    *,
    model: str,
    prompt: str,
    system: str | None = None,
    max_tokens: int | None = None,
) -> tuple[str, Usage | None]:
    """One-shot completion driven by streaming + concat."""
    request = MessageRequest(
        model=model,
        messages=[_user(prompt)],
        system_prompt=system,
        max_tokens=max_tokens or 4096,
        stream=True,
    )
    parts: list[str] = []
    usage: Usage | None = None
    async for event in client.stream_with_retry(request):
        if isinstance(event, StreamTextDelta):
            parts.append(event.text)
        elif isinstance(event, StreamError) and not event.retryable:
            raise RuntimeError(event.message)
        elif isinstance(event, StreamDone):
            usage = event.usage
    return "".join(parts).strip(), usage


async def _gather_strings(awaitables: list[Awaitable[str]]) -> list[str]:
    return list(await asyncio.gather(*awaitables, return_exceptions=False))


def _make_sync_run(
    loop: asyncio.AbstractEventLoop,
) -> Callable[[Awaitable[Any]], Any]:
    """Build a callable that drives an awaitable to completion.

    The sub-agent's helpers are sync (they live inside ``exec()``), but
    the bridge dispatchers are async. The user code runs in
    :func:`asyncio.to_thread` (a worker thread), so we can block-wait
    on the *running* loop via ``run_coroutine_threadsafe``. Reusing the
    caller's loop is critical — ``httpx.AsyncClient`` is loop-bound, so
    sub-LLM calls have to dispatch where the client was created.
    """

    def _run(coro: Awaitable[Any]) -> Any:
        future = asyncio.run_coroutine_threadsafe(_ensure_coro(coro), loop)
        return future.result()

    return _run


async def _ensure_coro(awaitable: Awaitable[Any]) -> Any:
    return await awaitable


async def _run_round_offthread(runtime: ReplRuntime, code: str) -> Any:
    """Execute the round body off the asyncio thread.

    User code is sync and may call sub-LLM helpers, which themselves
    block waiting on cross-thread futures. Running it in
    :func:`asyncio.to_thread` keeps the loop responsive and avoids the
    deadlock that would happen if the helpers tried to schedule on
    *this* thread's loop.
    """
    return await asyncio.to_thread(runtime.run, code)
