"""Runtime Language Model — REPL, tool wrapper, turn execution.

Consolidates rlm/ package.
"""

from __future__ import annotations



# ======================================================================
# From rlm/repl.py
# ======================================================================

"""In-process Python REPL for the RLM turn loop.

Replaces ``crates/tui/src/repl/runtime.rs`` (877 LOC) with a pure-Python
``exec()`` runtime (~150 LOC). Trades subprocess isolation for
simplicity — see :mod:`deepseek_tui.tools.rlm` for the rationale.

Key design points:

- A single ``namespace`` dict survives across :meth:`ReplRuntime.run`
  calls. Imports, local variables, and even open file handles persist
  exactly the way Rust's long-lived ``python3 -u`` did.
- ``__builtins__`` is replaced with a *restricted* dict that omits the
  most obviously hostile builtins (``open`` is allowed because the
  RLM's whole point is letting the sub-agent slice & dice files).
- ``FINAL(value)`` and ``FINAL_VAR(name)`` raise an internal sentinel
  exception so we can bail out of the round body without scanning
  stdout for sentinels (which is what Rust did via ``__RLM_FINAL__``).
- Sub-LLM helpers are injected into the namespace as plain functions.
  Their ``rpc_count`` is updated on the runtime instance so the driver
  can observe whether the sub-agent actually engaged.
"""


import contextlib
import io
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

# Builtins the sub-agent should not touch. We keep this list short and
# behavioural rather than exhaustive — the security boundary is the
# *parent process trust*, not exec()-isolation, and the RLM contract
# says the sub-agent is collaborating, not adversarial.
_FORBIDDEN_BUILTINS: frozenset[str] = frozenset(
    {
        "compile",
        "eval",
        "exec",
        "exit",
        "quit",
        "input",  # blocking on stdin would hang the loop forever
        "breakpoint",
    }
)


def _build_restricted_builtins() -> dict[str, Any]:
    """Return a copy of ``builtins`` with hostile entries dropped.

    Mirror Rust ``repl/sandbox.rs`` purpose without the OS layer.
    """
    import builtins

    out: dict[str, Any] = {}
    for name in dir(builtins):
        if name in _FORBIDDEN_BUILTINS or name.startswith("__"):
            continue
        out[name] = getattr(builtins, name)
    out["__name__"] = "__rlm__"
    return out


class _RlmFinal(Exception):  # noqa: N818 — sentinel, not an error type.
    """Raised by ``FINAL`` / ``FINAL_VAR`` to break out of a round."""

    def __init__(self, value: str) -> None:
        super().__init__(value)
        self.value = value


@dataclass(slots=True)
class ReplRound:
    """Result of executing one ```repl block.

    Mirror Rust ``ReplRound`` (runtime.rs:33).
    """

    stdout: str
    full_stdout: str
    stderr: str
    has_error: bool
    final_value: str | None
    rpc_count: int
    elapsed: float


# Default cap on how much stdout the driver pipes back into the next-round
# metadata message. Larger output is preserved on ``ReplRound.full_stdout``.
DEFAULT_STDOUT_LIMIT: int = 8192


@dataclass(slots=True)
class ReplRuntime:
    """Long-lived in-process Python REPL.

    Mirror Rust ``PythonRuntime`` (runtime.rs:135). The runtime owns the
    user namespace, the helper bindings, and the ``rpc_count`` counter.
    Construct via :meth:`spawn` (so future async setup hooks have a place
    to live without changing callers).
    """

    namespace: dict[str, Any] = field(default_factory=dict)
    rpc_count: int = 0
    stdout_limit: int = DEFAULT_STDOUT_LIMIT
    started_at: float = field(default_factory=time.monotonic)

    @classmethod
    def spawn(
        cls,
        context: str,
        helpers: dict[str, Callable[..., Any]],
        *,
        stdout_limit: int = DEFAULT_STDOUT_LIMIT,
    ) -> ReplRuntime:
        """Create a runtime with ``context`` and helper bindings preloaded.

        Mirror Rust ``PythonRuntime::spawn_with_context`` (runtime.rs:174).
        ``helpers`` is the dict of sub-LLM helpers (``llm_query``, …) the
        driver wires up; we splice them into the user namespace untouched.
        """
        ns: dict[str, Any] = {
            "__builtins__": _build_restricted_builtins(),
            "context": context,
            "ctx": context,
        }
        ns.update(helpers)
        ns["FINAL"] = _make_final(ns)
        ns["FINAL_VAR"] = _make_final_var(ns)
        ns["SHOW_VARS"] = _make_show_vars(ns)
        ns["repl_set"] = _make_repl_set(ns)
        ns["repl_get"] = _make_repl_get(ns)
        ns["chunk_context"] = _make_chunk_context(ns)
        ns["chunk_coverage"] = chunk_coverage
        return cls(namespace=ns, stdout_limit=stdout_limit)

    def run(self, code: str) -> ReplRound:
        """Execute one round of code in the REPL.

        Mirror Rust ``PythonRuntime::run`` (runtime.rs:264). Captures
        stdout and stderr, traps ``_RlmFinal``, returns the round trace.
        """
        self.rpc_count = 0
        rpc_count_before = 0
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        final_value: str | None = None
        had_error = False
        started = time.monotonic()

        # Resolve helper rpc-counter hook: the helpers bump this attribute
        # via :meth:`bump_rpc`, so we read the diff after exec.
        rpc_count_before = self.rpc_count

        with (
            contextlib.redirect_stdout(stdout_buf),
            contextlib.redirect_stderr(stderr_buf),
        ):
            try:
                exec(code, self.namespace)  # noqa: S102 — by-design RLM contract.
            except _RlmFinal as final:
                final_value = final.value
            except SystemExit as exc:  # exit()/quit() — treat as round error.
                had_error = True
                stderr_buf.write(f"SystemExit({exc.code!r})\n")
            except BaseException as exc:  # noqa: BLE001
                had_error = True
                import traceback

                stderr_buf.write("".join(traceback.format_exception(exc)))

        full_stdout = stdout_buf.getvalue()
        stdout = (
            full_stdout
            if len(full_stdout) <= self.stdout_limit
            else full_stdout[: self.stdout_limit] + "\n…[truncated]"
        )

        return ReplRound(
            stdout=stdout,
            full_stdout=full_stdout,
            stderr=stderr_buf.getvalue(),
            has_error=had_error,
            final_value=final_value,
            rpc_count=self.rpc_count - rpc_count_before,
            elapsed=time.monotonic() - started,
        )

    def bump_rpc(self, count: int = 1) -> None:
        """Record that helper RPCs were issued.

        Helpers call this so the round trace knows whether the sub-agent
        engaged with ``context`` via a sub-LLM call (paper requirement).
        """
        self.rpc_count += max(0, count)


# ---------------------------------------------------------------------------
# REPL helper factories
# ---------------------------------------------------------------------------


def _make_final(_ns: dict[str, Any]) -> Callable[[Any], None]:
    def _final(value: Any) -> None:
        text = value if isinstance(value, str) else repr(value)
        raise _RlmFinal(text)

    return _final


def _make_final_var(ns: dict[str, Any]) -> Callable[[str], None]:
    def _final_var(name: str) -> None:
        if name not in ns:
            raise NameError(f"FINAL_VAR: undefined variable {name!r}")
        value = ns[name]
        raise _RlmFinal(value if isinstance(value, str) else repr(value))

    return _final_var


def _make_show_vars(ns: dict[str, Any]) -> Callable[[], dict[str, str]]:
    def _show() -> dict[str, str]:
        names = sorted(
            n
            for n, v in ns.items()
            if not n.startswith("_")
            and n not in {"context", "ctx"}
            and not callable(v)
        )
        return {n: type(ns[n]).__name__ for n in names}

    return _show


def _make_repl_set(ns: dict[str, Any]) -> Callable[[str, Any], None]:
    def _set(name: str, value: Any) -> None:
        if not name.isidentifier():
            raise ValueError(f"repl_set: not a valid identifier: {name!r}")
        ns[name] = value

    return _set


def _make_repl_get(ns: dict[str, Any]) -> Callable[[str], Any]:
    def _get(name: str) -> Any:
        if name not in ns:
            raise NameError(f"repl_get: undefined variable {name!r}")
        return ns[name]

    return _get


def _make_chunk_context(ns: dict[str, Any]) -> Callable[..., list[dict[str, Any]]]:
    def _chunk_context(max_chars: int = 20_000, overlap: int = 0) -> list[dict[str, Any]]:
        text = str(ns.get("context") or ns.get("ctx") or "")
        if max_chars <= 0:
            raise ValueError("max_chars must be positive")
        overlap = max(0, min(overlap, max_chars - 1))
        chunks: list[dict[str, Any]] = []
        start = 0
        index = 0
        while start < len(text):
            end = min(len(text), start + max_chars)
            chunk_text = text[start:end]
            chunks.append(
                {
                    "index": index,
                    "start": start,
                    "end": end,
                    "text": chunk_text,
                }
            )
            if end >= len(text):
                break
            start = end - overlap if overlap else end
            index += 1
        return chunks

    return _chunk_context


def chunk_coverage(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize coverage for chunks produced by ``chunk_context()``."""
    if not chunks:
        return {"chunks": 0, "chars_covered": 0, "ranges": []}
    ranges = [(c.get("start", 0), c.get("end", 0)) for c in chunks]
    chars = sum(int(c.get("end", 0)) - int(c.get("start", 0)) for c in chunks)
    return {
        "chunks": len(chunks),
        "chars_covered": chars,
        "ranges": ranges,
    }


# ---------------------------------------------------------------------------
# Sub-LLM helper builders (sync wrappers around async dispatchers)
# ---------------------------------------------------------------------------


def build_sub_llm_helpers(
    runtime_ref: list[ReplRuntime],
    *,
    sync_run: Callable[[Awaitable[Any]], Any],
    llm_one: Callable[[str, str | None, int | None, str | None], Awaitable[str]],
    llm_batch: Callable[[list[str], str | None], Awaitable[list[str]]],
    rlm_one: Callable[[str, str | None], Awaitable[str]],
    rlm_batch: Callable[[list[str], str | None], Awaitable[list[str]]],
) -> dict[str, Callable[..., Any]]:
    """Wire helpers as synchronous functions backed by async dispatchers.

    The sub-agent's code is plain ``exec()``'d Python, so the helpers
    must be sync. ``sync_run`` runs an awaitable to completion in a way
    that's safe from inside the driver loop (the driver passes its own
    "run from outside the loop" callback so the bridge is reentrant).
    """

    def _llm_query(
        prompt: str,
        model: str | None = None,
        max_tokens: int | None = None,
        system: str | None = None,
    ) -> str:
        runtime_ref[0].bump_rpc()
        result = sync_run(llm_one(prompt, model, max_tokens, system))
        return str(result)

    def _llm_query_batched(
        prompts: list[str], model: str | None = None
    ) -> list[str]:
        runtime_ref[0].bump_rpc(len(prompts))
        result = sync_run(llm_batch(list(prompts), model))
        return list(result)

    def _rlm_query(prompt: str, model: str | None = None) -> str:
        runtime_ref[0].bump_rpc()
        result = sync_run(rlm_one(prompt, model))
        return str(result)

    def _rlm_query_batched(prompts: list[str], model: str | None = None) -> list[str]:
        runtime_ref[0].bump_rpc(len(prompts))
        result = sync_run(rlm_batch(list(prompts), model))
        return list(result)

    return {
        "llm_query": _llm_query,
        "llm_query_batched": _llm_query_batched,
        "rlm_query": _rlm_query,
        "rlm_query_batched": _rlm_query_batched,
    }


# ======================================================================
# From rlm/tool.py
# ======================================================================

"""``rlm`` tool adapter.

Mirror Rust ``crates/tui/src/tools/rlm.rs`` (406 LOC). Validates input,
loads ``file_path`` (preferred) or ``content`` into ``context``, then
dispatches to :func:`run_rlm_turn`. Returns the synthesized answer +
trace summary as the tool result.
"""


from typing import Any

from deepseek_tui.client.base import LLMClient
from deepseek_tui.tools.registry import (
    ApprovalRequirement,
    ToolCapability,
    ToolError,
    ToolResult,
    ToolSpec,
)
from deepseek_tui.tools.registry import ToolContext

DEFAULT_CHILD_MODEL: str = "deepseek-v4-flash"
DEFAULT_MAX_DEPTH: int = 1
MAX_INLINE_CONTENT_CHARS: int = 200_000


class RlmTool(ToolSpec):
    """The ``rlm`` tool — recursive language model over a long input.

    Mirror Rust ``RlmTool`` (rlm.rs:35).
    """

    def __init__(self, client: LLMClient | None, root_model: str) -> None:
        self._client = client
        self._root_model = root_model

    def name(self) -> str:
        return "rlm"

    def description(self) -> str:
        return (
            "Specialty tool for processing long inputs that don't fit in your "
            "own context window. Loads the input into a sandboxed Python REPL "
            "as `PROMPT`; a sub-agent writes Python that chunks the input and "
            "calls in-REPL helpers (`llm_query`, `llm_query_batched`, "
            "`rlm_query`, `rlm_query_batched`) to process it, then returns a "
            "synthesized answer. \n\n"
            "Use this tool when the input is genuinely large or when a Python "
            "map-reduce pass plus child LLM calls is the right shape: whole "
            "files, long transcripts, multi-document corpora, bulk semantic "
            "classification, or decomposition/critique work. For exact counts "
            "or structured aggregates, compute them directly in Python inside "
            "the REPL and report the deterministic result instead of asking a "
            "child LLM to guess. For whole-input map-reduce, use the REPL "
            "helpers `chunk_context()` and `chunk_coverage()` so the result "
            "states what was covered. \n\n"
            "Provide `task` (what to do) plus exactly one of `file_path` "
            "(workspace-relative, preferred — keeps the long input out of "
            "your context entirely) or `content` (inline, capped at 200k "
            "chars). The Python helpers (`llm_query`, `rlm_query`, etc.) live "
            "INSIDE the REPL — they are not separately-callable tools. \n\n"
            "Returns the final synthesized answer plus an RLM report showing "
            "input size, iterations, duration, sub-LLM calls, and trace summary."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["task"],
            "properties": {
                "task": {
                    "type": "string",
                    "description": (
                        'What to do with the input (e.g. "Summarize the security '
                        'model", "Extract all API endpoints", "Categorize each '
                        'row by sentiment"). The sub-agent uses this as its '
                        "objective."
                    ),
                },
                "file_path": {
                    "type": "string",
                    "description": (
                        "Workspace-relative path to a file to load as PROMPT. "
                        "Preferred — keeps the long input out of your context. "
                        "Mutually exclusive with `content`."
                    ),
                },
                "content": {
                    "type": "string",
                    "description": (
                        "Inline content to load as PROMPT. Use only when the "
                        "input isn't a file you can point at. Capped at 200k "
                        "chars."
                    ),
                },
                "max_depth": {
                    "type": "integer",
                    "description": (
                        "Recursion budget for `sub_rlm()` calls. 0 disables "
                        "recursion; default 1 matches paper experiments."
                    ),
                },
            },
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.NETWORK, ToolCapability.EXECUTES_CODE]

    def approval_requirement(self) -> ApprovalRequirement:
        return ApprovalRequirement.AUTO

    def supports_parallel(self) -> bool:
        return True

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        if self._client is None:
            raise ToolError("rlm_process requires an active DeepSeek client")

        task = (input_data.get("task") or "").strip()
        if not task:
            raise ToolError("rlm: `task` is empty")

        file_path = input_data.get("file_path")
        content = input_data.get("content")
        if file_path and content:
            raise ToolError("rlm: pass `file_path` OR `content`, not both")
        if not file_path and not content:
            raise ToolError("rlm: requires `file_path` (preferred) or `content`")

        if file_path:
            resolved = context.resolve_path(str(file_path))
            try:
                body = resolved.read_text(encoding="utf-8")
            except OSError as exc:
                raise ToolError(f"rlm: read {resolved}: {exc}") from exc
        else:
            body_str = str(content)
            char_count = sum(1 for _ in body_str)
            if char_count > MAX_INLINE_CONTENT_CHARS:
                raise ToolError(
                    f"rlm: inline `content` is {char_count} chars "
                    f"(cap {MAX_INLINE_CONTENT_CHARS}). Pass `file_path` "
                    "for larger inputs."
                )
            body = body_str

        if not body.strip():
            raise ToolError("rlm: input is empty after loading")

        input_chars = sum(1 for _ in body)
        input_lines = len(body.splitlines()) if body else 0

        # Pin child calls to Flash — model-generated args must not escalate cost.
        child_model = DEFAULT_CHILD_MODEL
        max_depth = int(input_data.get("max_depth", DEFAULT_MAX_DEPTH))

        progress_cb = context.metadata.get("rlm_progress_cb")
        result = await run_rlm_turn(
            client=self._client,
            model=self._root_model,
            prompt=body,
            root_prompt=task,
            child_model=child_model,
            max_depth=max_depth,
            on_progress=progress_cb if callable(progress_cb) else None,
        )

        if result.error:
            raise ToolError(
                f"rlm: {result.error} (iterations={result.iterations}, "
                f"termination={result.termination.value})"
            )
        if not result.answer.strip():
            raise ToolError(
                f"rlm: empty answer (termination={result.termination.value}, "
                f"iterations={result.iterations})"
            )

        footer = _termination_footer(result.termination, result.iterations)
        trace_summary = _trace_summary(result.trace)
        report = (
            "RLM report:\n"
            f"- input: {input_lines} line(s), {input_chars} char(s)\n"
            f"- iterations: {result.iterations}\n"
            f"- duration: {int(result.duration_secs * 1000)}ms\n"
            f"- sub-LLM RPCs: {result.total_rpcs}\n"
            f"- termination: {result.termination.value}\n\n"
            "Answer:\n"
        )
        text = f"{report}{result.answer}{footer}{trace_summary}"

        usage = result.usage
        metadata = {
            "iterations": result.iterations,
            "duration_ms": int(result.duration_secs * 1000),
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "child_input_tokens": usage.input_tokens,
            "child_output_tokens": usage.output_tokens,
            "child_prompt_cache_hit_tokens": usage.cache_read_input_tokens,
            "child_prompt_cache_miss_tokens": usage.cache_creation_input_tokens,
            "child_model": child_model,
            "termination": result.termination.value,
            "max_depth": max_depth,
            "context_chars": input_chars,
            "context_lines": input_lines,
            "total_rpcs": result.total_rpcs,
            "trace": [
                {
                    "round": t.round,
                    "rpc_count": t.rpc_count,
                    "elapsed_ms": t.elapsed_ms,
                    "had_error": t.had_error,
                    "code_summary": t.code_summary,
                    "stdout_preview": t.stdout_preview,
                }
                for t in result.trace
            ],
        }
        return ToolResult(success=True, content=text, metadata=metadata)


def _termination_footer(termination: RlmTermination, iterations: int) -> str:
    if termination == RlmTermination.FINAL:
        return ""
    if termination == RlmTermination.NO_CODE:
        return (
            f"\n\n[warning: sub-agent failed to engage the REPL after "
            f"{iterations} iterations — answer is the model's last raw response]"
        )
    if termination == RlmTermination.EXHAUSTED:
        return (
            f"\n\n[warning: sub-agent hit the {iterations}-iteration cap "
            "without FINAL()]"
        )
    return ""


def _trace_summary(trace: list[Any]) -> str:
    if not trace:
        return "\n\n[trace: no REPL rounds executed]"
    lines = ["\n\n[RLM trace]"]
    for r in trace:
        head = r.code_summary.splitlines()[0] if r.code_summary else ""
        head = head[:80]
        err_marker = " (error)" if r.had_error else ""
        lines.append(
            f"\n  round {r.round}: {r.rpc_count} sub-LLM call(s), "
            f"{r.elapsed_ms}ms{err_marker} — {head}"
        )
    return "".join(lines)


__all__ = ["DEFAULT_CHILD_MODEL", "DEFAULT_MAX_DEPTH", "RlmTool"]


# ======================================================================
# From rlm/turn.py
# ======================================================================

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


import asyncio
import enum
import logging
import re
import time
from collections.abc import Awaitable, Callable

ProgressCallback = Callable[[int, str, int], None]
from dataclasses import dataclass, field
from typing import Any

from deepseek_tui.client.base import LLMClient
from deepseek_tui.protocol.messages import Message, Role, TextBlock
from deepseek_tui.protocol.messages import MessageRequest
from deepseek_tui.protocol.responses import (
    StreamDone,
    StreamError,
    StreamTextDelta,
    Usage,
)

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
    on_progress: ProgressCallback | None = None,
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
        if on_progress is not None:
            try:
                on_progress(
                    iteration + 1,
                    _summarize_code(code),
                    round_result.rpc_count,
                )
            except Exception:  # noqa: BLE001
                pass

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


# ======================================================================
# From rlm/prompt.py
# ======================================================================

"""RLM system prompt (paper-style strict contract).

Mirrors ``crates/tui/src/rlm/prompt.rs`` (137 LOC).

Same wording the Rust prompt uses, modulo the helper-name table which
lists the Python functions exposed by :mod:`deepseek_tui.tools.rlm`.
"""
# ruff: noqa: E501


RLM_SYSTEM_PROMPT = """You are the root of a Recursive Language Model (RLM). Your input lives in a long-running Python REPL as a variable named `context` (alias `ctx`). You DO NOT see `context` in your prompt — only its length and a short preview. The only way to read or compute over it is to write Python code that runs in the REPL.

The REPL exposes:
- `context` (alias `ctx`) — the full input string. Often huge — never `print(context)` in full.
- `llm_query(prompt, model=None, max_tokens=None, system=None)` — one-shot child LLM. Cheap. Use for chunk-level work.
- `llm_query_batched(prompts, model=None)` — concurrent fan-out. Returns `list[str]` in input order.
- `rlm_query(prompt, model=None)` — recursive sub-RLM. Use when a sub-task itself needs decomposition.
- `rlm_query_batched(prompts, model=None)` — concurrent recursive sub-RLMs.
- `SHOW_VARS()` — list user variables and their types.
- `repl_set(name, value)` / `repl_get(name)` — explicit cross-round storage.
- `chunk_context(max_chars=8000, overlap=0)` — split `context` into overlapping chunks; returns `list[str]`.
- `chunk_coverage(chunks)` — report how much of `context` the chunks cover (chars + chunk count).
- `print(...)` — diagnostic output. The driver feeds you a truncated preview next round.
- `FINAL(value)` — end the loop with this string answer.
- `FINAL_VAR(name)` — end the loop with the value of a named variable.

Variables, imports, and any other state PERSIST across rounds — the REPL is a single long-lived Python process for the whole turn.

Contract — every turn, output ONE ` ```repl ` block of Python. That's it. No prose-only turns. No "I will do X" — just emit the code that does X.

Strategy patterns

1. PREVIEW first.
```repl
print(f"len(context) = {len(context)}")
print(context[:500])
```

2. CHUNK + map-reduce with batched concurrent calls.
```repl
chunk_size = 8000
chunks = [context[i:i+chunk_size] for i in range(0, len(context), chunk_size)]
prompts = [f"Extract any mentions of X from this section:\\n\\n{c}" for c in chunks]
partials = llm_query_batched(prompts)
combined = "\\n\\n".join(partials)
answer = llm_query(f"Synthesize across these section-level extractions:\\n\\n{combined}")
print(answer[:500])
```
Then on the next turn:
```repl
FINAL(answer)
```

3. RECURSIVE decomposition for hard sub-problems.
```repl
trend = rlm_query(f"Analyze this dataset and conclude with one word — up, down, or stable: {data}")
recommendation = "Hold" if "stable" in trend.lower() else ("Hedge" if "down" in trend.lower() else "Increase")
print(trend, "→", recommendation)
```

4. PROGRAMMATIC computation + LLM interpretation.
```repl
import math
theta = math.degrees(math.atan2(v_perp, v_parallel))
final_answer = llm_query(f"Entry angle is {theta:.2f}°. Phrase the answer for a physics student.")
FINAL(final_answer)
```

Rules

- Emit exactly ONE ` ```repl ` block per turn. The block must contain Python code only.
- Never `print(context)` or otherwise dump it whole — slice, sample, or chunk.
- You MUST call `llm_query` / `llm_query_batched` / `rlm_query` at least once before `FINAL(...)`. Calling FINAL from a top-level prose answer (without ever running a `repl` block that touched `context` via a sub-LLM) is REJECTED — the driver will discard the FINAL and ask you to actually use the REPL.
- Sub-LLMs are powerful — feed them generous chunks (tens of thousands of chars), not tiny windows.
- Do NOT pad your output with prose like "Here is what I'll do:" — just emit the next ```repl block.
"""


def rlm_system_prompt() -> str:
    """Return the RLM system prompt as a stripped string.

    Mirror Rust ``rlm_system_prompt`` (prompt.rs:9).
    """
    return RLM_SYSTEM_PROMPT.strip()
