"""Per-turn latency trace for Workbench / HTTP runtime diagnostics."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "TurnLatencyRound",
    "TurnLatencyTrace",
    "bind_turn_latency",
    "first_response_timeout_s",
    "get_turn_latency",
    "now_ms",
    "pop_turn_latency",
]

_traces: dict[str, TurnLatencyTrace] = {}


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class TurnLatencyRound:
    """One agent loop iteration: LLM stream (+ optional tool batch exec)."""

    round_idx: int
    started_at_ms: int
    llm_request_start_ms: int | None = None
    llm_first_sse_chunk_ms: int | None = None
    llm_stream_end_ms: int | None = None
    tool_calls: int = 0
    tool_exec_ms: int | None = None

    def llm_stream_ms(self) -> int | None:
        if self.llm_request_start_ms is None or self.llm_stream_end_ms is None:
            return None
        return max(0, self.llm_stream_end_ms - self.llm_request_start_ms)

    def llm_ttfb_ms(self) -> int | None:
        if self.llm_request_start_ms is None or self.llm_first_sse_chunk_ms is None:
            return None
        return max(0, self.llm_first_sse_chunk_ms - self.llm_request_start_ms)

    def to_payload(self) -> dict[str, Any]:
        return {
            "round_idx": self.round_idx,
            "started_at_ms": self.started_at_ms,
            "llm_request_start_ms": self.llm_request_start_ms,
            "llm_first_sse_chunk_ms": self.llm_first_sse_chunk_ms,
            "llm_stream_end_ms": self.llm_stream_end_ms,
            "llm_ttfb_ms": self.llm_ttfb_ms(),
            "llm_stream_ms": self.llm_stream_ms(),
            "tool_calls": self.tool_calls,
            "tool_exec_ms": self.tool_exec_ms,
        }


@dataclass
class TurnLatencyTrace:
    turn_id: str
    mode: str | None = None
    ui_submit_at_ms: int | None = None
    main_runtime_request_start_ms: int | None = None
    runtime_turn_created_ms: int | None = None
    engine_load_start_ms: int | None = None
    engine_load_end_ms: int | None = None
    engine_load_cache_hit: bool | None = None
    # First tool-catalog build only (MCP discover + registry merge).
    tool_catalog_start_ms: int | None = None
    tool_catalog_end_ms: int | None = None
    tool_catalog_build_ms: int | None = None
    catalog_refresh_count: int = 0
    catalog_refresh_total_ms: int = 0
    tools_count: int | None = None
    active_tools_count: int | None = None
    llm_payload_bytes: int | None = None
    llm_request_start_ms: int | None = None
    llm_first_sse_chunk_ms: int | None = None
    runtime_first_delta_emitted_ms: int | None = None
    turn_completed_ms: int | None = None
    first_response_timeout_s: float | None = None
    timeout_reason: str | None = None
    delta_events_emitted: int = 0
    approval_wait_total_ms: int = 0
    approval_wait_count: int = 0
    tool_exec_total_ms: int = 0
    tool_exec_count: int = 0
    rounds: list[TurnLatencyRound] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def mark(self, key: str, value: int | float | str | bool | None = None) -> None:
        if not hasattr(self, key):
            self.extra[key] = value
            return
        setattr(self, key, value)

    def note_catalog_build(self, build_start_ms: int, build_ms: int, tools_count: int) -> None:
        """Record catalog build; only the first build sets ``tool_catalog_*``."""
        if self.tool_catalog_build_ms is None:
            self.tool_catalog_start_ms = build_start_ms
            self.tool_catalog_end_ms = build_start_ms + build_ms
            self.tool_catalog_build_ms = build_ms
            self.tools_count = tools_count
        else:
            self.catalog_refresh_count += 1
            self.catalog_refresh_total_ms += build_ms

    def start_round(self, round_idx: int) -> TurnLatencyRound:
        round_trace = TurnLatencyRound(round_idx=round_idx, started_at_ms=now_ms())
        self.rounds.append(round_trace)
        return round_trace

    def current_round(self) -> TurnLatencyRound | None:
        if not self.rounds:
            return None
        return self.rounds[-1]

    def note_approval_wait(self, duration_ms: int) -> None:
        self.approval_wait_total_ms += max(0, duration_ms)
        self.approval_wait_count += 1

    def note_tool_exec(self, duration_ms: int) -> None:
        self.tool_exec_total_ms += max(0, duration_ms)
        self.tool_exec_count += 1

    def segments_ms(self) -> dict[str, int | None]:
        """Best-effort segment durations for log analysis."""

        def span(start: int | None, end: int | None) -> int | None:
            if start is None or end is None:
                return None
            return max(0, end - start)

        origin = self.ui_submit_at_ms or self.main_runtime_request_start_ms
        agent_origin = self.runtime_turn_created_ms or self.engine_load_end_ms
        agent_loop_ms = span(agent_origin, self.turn_completed_ms)
        if agent_loop_ms is not None:
            agent_loop_ms = max(
                0,
                agent_loop_ms
                - self.approval_wait_total_ms
                - self.tool_exec_total_ms,
            )

        return {
            "ui_to_main_ms": span(self.ui_submit_at_ms, self.main_runtime_request_start_ms),
            "main_to_runtime_ms": span(
                self.main_runtime_request_start_ms, self.runtime_turn_created_ms
            ),
            "engine_load_ms": span(self.engine_load_start_ms, self.engine_load_end_ms),
            "first_tool_catalog_ms": self.tool_catalog_build_ms,
            "catalog_refresh_ms": (
                self.catalog_refresh_total_ms if self.catalog_refresh_count else None
            ),
            "llm_ttfb_ms": span(self.llm_request_start_ms, self.llm_first_sse_chunk_ms),
            "llm_to_first_delta_ms": span(
                self.llm_first_sse_chunk_ms, self.runtime_first_delta_emitted_ms
            ),
            "approval_wait_ms": self.approval_wait_total_ms or None,
            "tool_exec_ms": self.tool_exec_total_ms or None,
            "agent_loop_ms": agent_loop_ms,
            "end_to_end_ms": span(origin, self.turn_completed_ms),
        }

    def to_payload(self) -> dict[str, Any]:
        data = asdict(self)
        data["segments_ms"] = self.segments_ms()
        data["rounds"] = [round_trace.to_payload() for round_trace in self.rounds]
        return data

    def log_summary(self) -> None:
        logger.info("turn_latency_trace %s", json.dumps(self.to_payload(), ensure_ascii=False))


def bind_turn_latency(trace: TurnLatencyTrace) -> None:
    _traces[trace.turn_id] = trace


def get_turn_latency(turn_id: str) -> TurnLatencyTrace | None:
    return _traces.get(turn_id)


def pop_turn_latency(turn_id: str) -> TurnLatencyTrace | None:
    return _traces.pop(turn_id, None)


def first_response_timeout_s(mode: str | None) -> float:
    """Tiered watchdog limit before the first engine response event."""
    normalized = (mode or "agent").strip().lower()
    if normalized in ("chat", "ask"):
        return 30.0
    if normalized in ("agent", "code", "yolo", "plan"):
        return 120.0
    return 60.0


def first_response_timeout_message(trace: TurnLatencyTrace | None) -> str:
    if trace is None:
        return "模型首包响应超时，请稍后重试。"
    if trace.llm_request_start_ms is None:
        return "Engine/session/tool 准备超时，请检查 MCP 配置或稍后重试。"
    if trace.llm_first_sse_chunk_ms is None:
        return "模型首包响应超时，请稍后重试。"
    return "模型首包响应超时，请稍后重试。"
