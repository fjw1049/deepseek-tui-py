"""Session-level per-model usage aggregation."""

from __future__ import annotations

from deepseek_tui.server.threads import (
    accumulate_model_usage_from_turn,
    build_turn_usage_record,
    session_model_usage_response,
)
from deepseek_tui.protocol.responses import Usage


def test_accumulate_model_usage_from_turn_uses_models_map() -> None:
    session: dict[str, dict] = {}
    accumulate_model_usage_from_turn(
        session,
        {
            "input_tokens": 100,
            "output_tokens": 20,
            "models": {
                "deepseek-chat": {
                    "input_tokens": 60,
                    "output_tokens": 10,
                    "turns": 1,
                },
                "claude-sonnet-4-6": {
                    "input_tokens": 40,
                    "output_tokens": 10,
                    "turns": 1,
                },
            },
        },
        fallback_model="deepseek-chat",
    )
    assert session["deepseek-chat"]["total_tokens"] == 70
    assert session["claude-sonnet-4-6"]["total_tokens"] == 50


def test_accumulate_model_usage_from_turn_falls_back_to_thread_model() -> None:
    session: dict[str, dict] = {}
    accumulate_model_usage_from_turn(
        session,
        {
            "input_tokens": 12,
            "output_tokens": 3,
            "turns": 1,
        },
        fallback_model="deepseek-chat",
    )
    assert session["deepseek-chat"]["input_tokens"] == 12
    assert session["deepseek-chat"]["output_tokens"] == 3
    assert session["deepseek-chat"]["total_tokens"] == 15


def test_build_turn_usage_record_includes_models() -> None:
    record = build_turn_usage_record(
        usage=Usage(input_tokens=10, output_tokens=4),
        model="deepseek-chat",
    )
    assert "models" in record
    assert record["models"]["deepseek-chat"]["input_tokens"] == 10


def test_session_model_usage_response_sorts_by_total_tokens() -> None:
    response = session_model_usage_response(
        {
            "small": {
                "model": "small",
                "input_tokens": 10,
                "output_tokens": 1,
                "total_tokens": 11,
                "cost_usd": 0.0,
                "cost_cny": 0.0,
                "turns": 1,
            },
            "large": {
                "model": "large",
                "input_tokens": 100,
                "output_tokens": 20,
                "total_tokens": 120,
                "cost_usd": 0.01,
                "cost_cny": 0.07,
                "turns": 2,
            },
        }
    )
    assert response["group_by"] == "model"
    assert response["scope"] == "session"
    assert [bucket["model"] for bucket in response["buckets"]] == ["large", "small"]
    assert response["totals"]["total_tokens"] == 131
