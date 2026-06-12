"""Tests for info sidebar per-turn filtering."""

from __future__ import annotations

from deepseek_tui.tui.sidebar import (
    filter_sidebar_agents,
    filter_sidebar_tasks,
    filter_sidebar_todos,
    parse_plan_markdown,
    plan_snapshot_from_metadata,
    reset_turn_sidebar_sources,
    sync_plan_store,
)


def test_filter_sidebar_tasks_hides_completed() -> None:
    tasks = [
        {"id": "task_a", "status": "completed"},
        {"id": "task_b", "status": "running"},
        {"id": "task_c", "status": "queued"},
    ]
    filtered = filter_sidebar_tasks(tasks)
    assert [t["id"] for t in filtered] == ["task_b", "task_c"]


def test_filter_sidebar_agents_shows_current_turn_only() -> None:
    agents = [
        {"agent_id": "agent_old", "status": "completed", "agent_type": "explore"},
        {"agent_id": "agent_new", "status": "completed", "agent_type": "explore"},
        {"agent_id": "agent_run", "status": "running", "agent_type": "implementer"},
    ]
    filtered = filter_sidebar_agents(
        agents, turn_agent_ids={"agent_new"}
    )
    ids = [a["agent_id"] for a in filtered]
    assert "agent_old" not in ids
    assert ids == ["agent_new", "agent_run"]


def test_filter_sidebar_todos_hides_completed() -> None:
    todos = [
        {"id": "1", "status": "completed", "content": "done"},
        {"id": "2", "status": "in_progress", "content": "active"},
        {"id": "3", "status": "pending", "content": "next"},
    ]
    filtered = filter_sidebar_todos(todos)
    assert [t["id"] for t in filtered] == ["2", "3"]


def test_reset_turn_sidebar_sources_clears_plan_and_todos() -> None:
    metadata: dict[str, object] = {
        "todos": {"items": [{"id": "1", "status": "pending", "content": "x"}], "next_id": 2},
        "plan": {
            "goal": "Old goal",
            "steps": [{"index": 1, "title": "Step", "status": "completed"}],
        },
    }
    reset_turn_sidebar_sources(metadata)
    todos = metadata["todos"]
    assert isinstance(todos, dict)
    assert todos["items"] == []
    assert todos["next_id"] == 1
    plan = metadata["plan"]
    assert isinstance(plan, dict)
    assert plan["goal"] is None
    assert plan["steps"] == []


def test_plan_snapshot_from_metadata() -> None:
    metadata = {
        "plan": {
            "goal": "Ship feature",
            "steps": [
                {"index": 1, "title": "Design", "status": "completed"},
                {"index": 2, "title": "Implement", "status": "in_progress"},
            ],
        }
    }
    goal, steps = plan_snapshot_from_metadata(metadata)
    assert goal == "Ship feature"
    assert len(steps) == 2
    assert steps[1]["title"] == "Implement"


def test_parse_plan_markdown_and_sync() -> None:
    text = "- [ ] First\n- [x] Done\n- [~] Active"
    steps = parse_plan_markdown(text)
    assert [s["status"] for s in steps] == ["pending", "completed", "in_progress"]
    metadata: dict[str, object] = {}
    sync_plan_store(metadata, explanation="My plan", plan_text=text)
    goal, stored = plan_snapshot_from_metadata(metadata)
    assert goal == "My plan"
    assert len(stored) == 3
