"""Ingress truncation must know how full the context actually is.

One constant used to do two jobs: bound a single pathological tool result,
and ration a context that is filling up. Only the second depends on how full
the window is, so at 5% used a 30k-char read_file was cut to a snippet for
no reason — and past the L0 prune point, where a mechanism is already
reclaiming space, fresh bulk was still admitted at full size.
"""

from __future__ import annotations

import inspect
import re

from deepseek_tui.engine.context import (
    TOOL_RESULT_CONTEXT_HARD_LIMIT_CHARS,
    _pressure_scale,
    compact_tool_result_for_context,
)
from deepseek_tui.engine.context_pressure import RATIO_AUTO_FLOOR, RATIO_L0_PRUNE
from deepseek_tui.tools.registry import ToolResult

MODEL = "gpt-4o"  # small-window branch: 12k hard limit
_BODY = "x" * (TOOL_RESULT_CONTEXT_HARD_LIMIT_CHARS + 5_000)


def _compact(ratio: float | None) -> str:
    return compact_tool_result_for_context(
        MODEL, "read_file", ToolResult(success=True, content=_BODY),
        pressure_ratio=ratio,
    )


# --- the scale itself ------------------------------------------------------


def test_an_empty_context_is_generous() -> None:
    assert _pressure_scale(0.05) > 1.0


def test_a_filling_context_is_unchanged() -> None:
    assert _pressure_scale((RATIO_AUTO_FLOOR + RATIO_L0_PRUNE) / 2) == 1.0


def test_past_the_prune_point_it_tightens() -> None:
    assert _pressure_scale(RATIO_L0_PRUNE) < 1.0
    assert _pressure_scale(0.9) < 1.0


def test_an_unknown_ratio_behaves_exactly_as_before() -> None:
    """First turn and post-cancel have no real token count. The estimate
    path runs low, so inferring "roomy" from it would loosen the limits at
    the one moment that is most likely to be wrong."""
    assert _pressure_scale(None) == 1.0


def test_the_thresholds_are_the_ladder_s_own() -> None:
    """Tuning 3.6 must move this with everything else, not separately.

    The multipliers are literals and should be; what must not be a literal
    is where the tiers sit, since a private copy of 0.20 or 0.50 here would
    silently drift out of step with the rest of the ladder.
    """
    source = inspect.getsource(_pressure_scale)
    assert "RATIO_AUTO_FLOOR" in source
    assert "RATIO_L0_PRUNE" in source
    compared_literals = re.findall(r"pressure_ratio\s*[<>]=?\s*([0-9.]+)", source)
    assert not compared_literals, f"thresholds must be named: {compared_literals}"


# --- end to end ------------------------------------------------------------


def test_a_large_read_survives_intact_in_an_empty_context() -> None:
    assert _compact(0.05) == _BODY


def test_the_same_read_is_compacted_once_the_context_fills() -> None:
    out = _compact(0.60)
    assert "compacted to protect context" in out
    assert len(out) < len(_BODY)


def test_omitting_the_ratio_preserves_the_old_behaviour() -> None:
    """Every existing caller and test passes no ratio; none may shift."""
    without = compact_tool_result_for_context(
        MODEL, "read_file", ToolResult(success=True, content=_BODY)
    )
    assert without == _compact(None)
    assert "compacted to protect context" in without


def test_high_pressure_keeps_a_smaller_snippet_than_normal() -> None:
    normal = _compact(0.30)
    squeezed = _compact(0.80)
    assert len(squeezed) < len(normal)


def test_a_short_result_is_never_touched() -> None:
    short = ToolResult(success=True, content="3 files changed")
    for ratio in (None, 0.05, 0.30, 0.95):
        assert compact_tool_result_for_context(
            MODEL, "exec_shell", short, pressure_ratio=ratio
        ) == "3 files changed"


def test_generosity_still_has_a_ceiling() -> None:
    """Roomy is not unbounded — a runaway result is still the other job."""
    runaway = ToolResult(success=True, content="y" * 500_000)
    out = compact_tool_result_for_context(
        MODEL, "exec_shell", runaway, pressure_ratio=0.01
    )
    assert "compacted to protect context" in out


# --- wiring ----------------------------------------------------------------


def test_both_tool_loops_pass_the_ratio() -> None:
    """Serial and parallel batches are separate code paths; a ratio wired
    into only one would leave parallel reads truncating as before."""
    from deepseek_tui.engine.orchestrator.tooling import ToolExecutionMixin

    for fn in (
        ToolExecutionMixin._execute_tool_calls,
        ToolExecutionMixin._execute_tools_parallel,
    ):
        source = inspect.getsource(fn)
        call = re.search(
            r"compact_tool_result_for_context\((.*?)\n\s*\)", source, re.DOTALL
        )
        assert call is not None, f"{fn.__name__} lost the compaction call"
        assert "pressure_ratio=self._ingress_pressure_ratio(" in call.group(1)


def test_the_ratio_is_none_until_the_provider_reports_tokens() -> None:
    from deepseek_tui.engine.orchestrator.tooling import ToolExecutionMixin

    class _Stub(ToolExecutionMixin):
        def __init__(self, tokens: int) -> None:
            self.last_real_input_tokens = tokens

    assert _Stub(0)._ingress_pressure_ratio(MODEL) is None
    ratio = _Stub(64_000)._ingress_pressure_ratio(MODEL)
    assert ratio is not None and 0.0 < ratio < 1.0
