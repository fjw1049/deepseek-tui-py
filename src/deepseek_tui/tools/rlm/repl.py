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

from __future__ import annotations

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
