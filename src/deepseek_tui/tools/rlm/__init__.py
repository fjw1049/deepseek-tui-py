"""Recursive Language Model (RLM) — in-process Python REPL variant.

Mirrors ``crates/tui/src/rlm/`` and ``crates/tui/src/repl/`` (~2,300 LOC
across mod/turn/bridge/prompt/runtime/sandbox), reimplemented in Python
using the in-process ``exec()`` approach approved by the user
(`rlm_a` answer to the architectural prompt — see HANDOVER.md).

Why in-process instead of a subprocess + JSON-RPC bridge? The sandbox
cost in Rust (~877 LOC of bootstrap, sentinels, stdin/stdout protocol)
buys *concurrent isolation*, not OS-level safety: the user already
declined Seatbelt isolation, so subprocess overhead is pure cost. We
trade that for a single ~280 LOC Python module that:

- runs sub-agent code in the *same* process via ``exec()`` against a
  restricted-builtins namespace (`_build_restricted_builtins` below);
- exposes ``llm_query`` / ``llm_query_batched`` / ``rlm_query`` /
  ``rlm_query_batched`` / ``FINAL`` / ``FINAL_VAR`` / ``SHOW_VARS`` /
  ``repl_set`` / ``repl_get`` directly as namespace functions;
- persists state across rounds because the namespace lives between
  ``exec`` calls;
- captures stdout/stderr per round into bounded buffers.

Public API (parity with Rust):

- :func:`run_rlm_turn`        — full turn loop driver.
- :class:`RlmTurnResult`      — answer + trace + termination.
- :class:`RlmTermination`     — Final / NoCode / Exhausted / Error.
- :func:`rlm_system_prompt`   — paper-style strict prompt.
- :class:`RlmTool`            — :class:`ToolSpec` adapter.

Carried-over limitations vs. Rust (recorded in HANDOVER.md):

- No process isolation — buggy or hostile sub-agent code runs in the
  parent's process.
- ``rlm_query`` recursion is bounded only by ``max_depth`` and the same
  iteration cap as the parent loop. There is no separate process for
  nested sub-RLMs.
- ``round.elapsed`` / ``rpc_count`` are best-effort wall-clock counters
  rather than the Rust-precise ``tokio::time::Instant`` accounting.
"""

from __future__ import annotations

from deepseek_tui.tools.rlm.prompt import rlm_system_prompt
from deepseek_tui.tools.rlm.repl import ReplRound, ReplRuntime
from deepseek_tui.tools.rlm.tool import RlmTool
from deepseek_tui.tools.rlm.turn import (
    RlmTermination,
    RlmTurnResult,
    extract_repl_code,
    parse_text_final,
    run_rlm_turn,
)

__all__ = [
    "ReplRound",
    "ReplRuntime",
    "RlmTermination",
    "RlmTool",
    "RlmTurnResult",
    "extract_repl_code",
    "parse_text_final",
    "rlm_system_prompt",
    "run_rlm_turn",
]
